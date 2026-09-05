from pathlib import Path

from app.agent.contracts import EvaluationResult
from app.agent.environments import (
    AgentEnvironment,
    DocumentCheckEnvironment,
    WordEditEnvironment,
)
from app.db.database import SessionLocal
from app.db.models import CheckRun, WordDocument, WordEditRun


TERMINAL_INPUT_ERRORS = (
    "不存在",
    "不属于当前访客",
    "只支持 .docx",
    "没有可解析",
    "请先上传",
)


def evaluate_environment(
    env: AgentEnvironment,
    *,
    final_action: str,
    runner_error: str,
    reached_max_steps: bool,
) -> EvaluationResult:
    common = common_failure(
        final_action=final_action,
        runner_error=runner_error or env.execution_error,
        reached_max_steps=reached_max_steps,
    )
    if common:
        return common
    if isinstance(env, DocumentCheckEnvironment):
        return evaluate_document_check(env, final_action)
    if isinstance(env, WordEditEnvironment):
        return evaluate_word_edit(env, final_action)
    return EvaluationResult(status="terminal_failure", summary="没有对应的业务 Evaluator")


def common_failure(
    *, final_action: str, runner_error: str, reached_max_steps: bool
) -> EvaluationResult | None:
    if reached_max_steps:
        return EvaluationResult(
            status="retryable_failure",
            summary="Agent 达到最大步数但任务尚未结束",
            failed_checks=["max_steps"],
            retry_strategy="减少重复工具调用，优先完成尚未执行的必要步骤。",
        )
    if runner_error:
        status = (
            "terminal_failure"
            if any(marker in runner_error for marker in TERMINAL_INPUT_ERRORS)
            else "retryable_failure"
        )
        return EvaluationResult(
            status=status,
            summary=f"执行失败：{runner_error}",
            failed_checks=["runner_or_tool_error"],
            evidence={"error": runner_error},
            retry_strategy="重新读取当前状态，只调用 allowed_actions 中满足前置条件的动作。",
        )
    if final_action == "manual_review":
        return EvaluationResult(
            status="manual_review",
            summary="Agent 发现当前证据不足或自动操作不安全，已转人工复核",
            evidence={"final_action": final_action},
        )
    if final_action != "finish":
        return EvaluationResult(
            status="retryable_failure",
            summary="Agent 未产生有效终止动作",
            failed_checks=["missing_terminal_action"],
            retry_strategy="完成必要工具调用后明确输出 finish 或 manual_review。",
        )
    return None


def evaluate_document_check(
    env: DocumentCheckEnvironment, final_action: str
) -> EvaluationResult:
    del final_action
    tools = [item["tool"] for item in env.tool_results]
    missing = []
    if "consistency" in env.checks and "word_check_tool" not in tools:
        missing.append("word_check_tool")
    if "completeness" in env.checks and "completeness_check_tool" not in tools:
        missing.append("completeness_check_tool")
    if missing:
        return EvaluationResult(
            status="retryable_failure",
            summary="文档检查尚未执行全部必需工具",
            failed_checks=[f"missing:{name}" for name in missing],
            evidence={"completed_tools": tools, "required_checks": env.checks},
            retry_strategy=f"执行缺失工具：{', '.join(missing)}，然后再 finish。",
        )
    with SessionLocal() as session:
        document = session.get(WordDocument, env.document_id)
        if not document or document.owner_user_id != env.owner_user_id:
            return EvaluationResult(
                status="terminal_failure",
                summary="输出文档不存在或不属于当前用户",
                failed_checks=["document_ownership"],
            )
        if document.parse_status != "parsed":
            return EvaluationResult(
                status="retryable_failure",
                summary="Word 文档没有成功解析",
                failed_checks=["document_parse_status"],
                evidence={"parse_status": document.parse_status},
                retry_strategy="重新解析 Word 后再执行检查。",
            )
    wrong_document = [
        item["tool"]
        for item in env.tool_results
        if item["result"].get("document_id") != env.document_id
    ]
    if wrong_document:
        return EvaluationResult(
            status="terminal_failure",
            summary="工具结果与当前文档不一致",
            failed_checks=["document_id_consistency"],
            evidence={"wrong_document_tools": wrong_document},
        )
    return EvaluationResult(
        status="success",
        summary="文档已完成所需检查，数据库和工具结果一致",
        evidence={"document_id": env.document_id, "tools": tools, "issue_count": env.issue_count()},
    )


def evaluate_word_edit(env: WordEditEnvironment, final_action: str) -> EvaluationResult:
    del final_action
    if env.edit_run_id is None:
        return EvaluationResult(status="terminal_failure", summary="WordEditRun 未创建")
    with SessionLocal() as session:
        run = session.get(WordEditRun, env.edit_run_id)
        if not run or run.owner_user_id != env.owner_user_id:
            return EvaluationResult(status="terminal_failure", summary="WordEditRun 不存在或越权")
        if run.status == "manual_review":
            return EvaluationResult(
                status="manual_review",
                summary="修改存在不可安全定位或仍需人工确认的问题",
                evidence={"edit_run_id": run.id, "status": run.status},
            )
        if run.status != "completed":
            return EvaluationResult(
                status="retryable_failure",
                summary=f"Word 修改流程未完成，当前状态为 {run.status}",
                failed_checks=["edit_run_status"],
                evidence={"edit_run_id": run.id, "status": run.status},
                retry_strategy="从数据库重新读取修改状态，完成 apply/verify 后再结束。",
            )
        changes = list(run.changes or [])
        if any(item.get("status") in ("pending", "failed") for item in changes):
            return EvaluationResult(
                status="terminal_failure",
                summary="修改任务虽然结束，但仍存在 pending/failed change",
                failed_checks=["change_status"],
            )
        document_id = run.output_document_id or run.source_document_id
        document = session.get(WordDocument, document_id)
        if not document or document.owner_user_id != env.owner_user_id:
            return EvaluationResult(status="terminal_failure", summary="修改后的文档不存在或越权")
        if document.parse_status != "parsed":
            return EvaluationResult(
                status="retryable_failure",
                summary="修改后的 Word 副本未成功解析",
                failed_checks=["output_parse_status"],
                retry_strategy="重新生成并解析副本，再执行复检。",
            )
        if run.output_document_id:
            if not run.verification_run_id:
                return EvaluationResult(
                    status="retryable_failure",
                    summary="生成了修订副本但没有复检记录",
                    failed_checks=["missing_verification"],
                    retry_strategy="对最新副本执行 verify_word_edit_tool。",
                )
            verification = session.get(CheckRun, run.verification_run_id)
            if not verification or verification.status != "completed":
                return EvaluationResult(
                    status="retryable_failure",
                    summary="修订副本复检记录无效",
                    failed_checks=["verification_status"],
                    retry_strategy="重新复检最新副本。",
                )
        file_exists = bool(document.file_path and Path(document.file_path).exists())
        if not file_exists:
            return EvaluationResult(
                status="terminal_failure",
                summary="数据库记录存在，但输出文件不存在",
                failed_checks=["output_file_exists"],
            )
    return EvaluationResult(
        status="success",
        summary="Word 修改完成，输出文件、修改状态和复检记录一致",
        evidence={"edit_run_id": env.edit_run_id, "document_id": document_id},
    )
