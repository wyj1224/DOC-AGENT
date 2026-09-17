from collections import Counter, defaultdict
from pathlib import Path

from app.agent.contracts import EvaluationResult
from app.agent.environments import (
    AgentEnvironment,
    DocumentCheckEnvironment,
    WordEditEnvironment,
)
from app.db.database import SessionLocal
from app.db.models import CheckIssue, CheckRun, WordDocument, WordEditRun, WordReference
from app.services.word_editor import (
    locator_key,
    resolve_word_document_path,
    validate_word_change_diff,
)


TERMINAL_INPUT_ERRORS = (
    "不存在",
    "不属于当前访客",
    "只支持 .docx",
    "没有可解析",
    "请先上传",
)

TOOL_RESULT_FIELDS = {
    "word_check_tool": {
        "document_id",
        "check_scope",
        "reference_count",
        "basis_reference_count",
        "body_reference_count",
        "issue_count",
        "returned_issue_count",
        "issues",
        "grouped_issues",
    },
    "completeness_check_tool": {
        "document_id",
        "template_id",
        "template_file_name",
        "template_year",
        "template_type",
        "template_type_label",
        "check_scope",
        "template_heading_count",
        "document_section_count",
        "key_section_results",
        "issue_count",
        "returned_issue_count",
        "issues",
    },
    "get_issues_tool": {
        "document_id",
        "check_scope",
        "issue_type",
        "severity",
        "issue_count",
        "returned_issue_count",
        "issues",
    },
}

ISSUE_FIELDS = {
    "issue_id",
    "check_scope",
    "issue_type",
    "severity",
    "word_reference_id",
    "matched_clause_id",
    "matched_standard_record_id",
    "section_title",
    "paragraph_index",
    "standard_no",
    "standard_name",
    "clause_no",
    "original_text",
    "reason",
    "suggestion",
    "fix_data",
}

CHANGE_FIELDS = {
    "change_id",
    "cycle",
    "input_document_id",
    "output_document_id",
    "verification_run_id",
    "issue_id",
    "issue_type",
    "severity",
    "locator",
    "span",
    "before",
    "after",
    "status",
    "verification_status",
}


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
    return EvaluationResult(
        status="terminal_failure", summary="没有对应的业务 Evaluator"
    )


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
    if final_action not in ("finish", "manual_review"):
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
    tools = [
        str(item.get("tool") or "")
        for item in env.tool_results
        if isinstance(item, dict)
    ]
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
    schema_failures, truncated_tools = validate_tool_results(env.tool_results)
    if schema_failures:
        return EvaluationResult(
            status="retryable_failure",
            summary="检查工具返回结构或统计不完整",
            failed_checks=schema_failures,
            evidence={"tools": tools, "truncated_tools": truncated_tools},
            retry_strategy="重新执行检查工具，并使用数据库中的完整问题总数。",
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
        check_run = (
            session.get(CheckRun, env.check_run_id) if env.check_run_id else None
        )
        if not check_run or any(
            (
                check_run.owner_user_id != env.owner_user_id,
                check_run.document_id != env.document_id,
                check_run.task_id != env.task_id,
                check_run.episode_id != env.episode_id,
            )
        ):
            return EvaluationResult(
                status="retryable_failure",
                summary="检查记录没有关联到当前文档版本、任务或 Episode",
                failed_checks=["check_run_context"],
                retry_strategy="为当前文档版本重新创建检查记录后再执行工具。",
            )

        required_scopes = set()
        if "consistency" in env.checks:
            required_scopes.update(("basis_excel", "body_basis"))
        if "completeness" in env.checks:
            required_scopes.add("completeness")
        all_issues = (
            session.query(CheckIssue)
            .filter(CheckIssue.document_id == env.document_id)
            .all()
        )
        issues = [issue for issue in all_issues if issue.check_scope in required_scopes]
        scope_counts = Counter(issue.check_scope for issue in issues)
        count_failures = validate_document_counts(
            env.tool_results, all_issues, scope_counts
        )
        duplicates = duplicate_issue_ids(issues)
        conflicts = conflicting_issue_fixes(issues)

    wrong_document = [
        str(item.get("tool") or "")
        for item in env.tool_results
        if dict(item.get("result") or {}).get("document_id") != env.document_id
        or dict(item.get("args") or {}).get("document_id") != env.document_id
    ]
    if wrong_document or count_failures:
        failed_checks = count_failures[:]
        if wrong_document:
            failed_checks.append("document_id_consistency")
        return EvaluationResult(
            status="retryable_failure",
            summary="工具统计、数据库问题或当前文档版本不一致",
            failed_checks=failed_checks,
            evidence={
                "wrong_document_tools": wrong_document,
                "database_issue_count": len(issues),
                "tool_issue_count": env.issue_count(),
                "scope_counts": dict(scope_counts),
                "truncated_tools": truncated_tools,
            },
            retry_strategy="重新读取当前文档版本并执行所需检查，不要根据截断明细自行计数。",
        )
    if duplicates or conflicts:
        return EvaluationResult(
            status="manual_review",
            summary="检查结果存在重复或相互矛盾的问题，需要人工复核",
            failed_checks=[
                name
                for name, values in (
                    ("duplicate_issues", duplicates),
                    ("conflicting_fixes", conflicts),
                )
                if values
            ],
            evidence={
                "duplicate_issue_ids": duplicates,
                "conflicting_fixes": conflicts,
            },
        )
    if final_action == "manual_review":
        return EvaluationResult(
            status="manual_review",
            summary="检查事实一致，但 Agent 认为仍有证据需要人工确认",
            evidence={"final_action": final_action, "truncated_tools": truncated_tools},
        )
    return EvaluationResult(
        status="success",
        summary="文档已完成所需检查，数据库和工具结果一致",
        evidence={
            "document_id": env.document_id,
            "tools": tools,
            "issue_count": len(issues),
            "scope_counts": dict(scope_counts),
            "truncated_tools": truncated_tools,
        },
    )


def evaluate_word_edit(env: WordEditEnvironment, final_action: str) -> EvaluationResult:
    if env.edit_run_id is None:
        return EvaluationResult(status="terminal_failure", summary="WordEditRun 未创建")
    with SessionLocal() as session:
        run = session.get(WordEditRun, env.edit_run_id)
        if not run or run.owner_user_id != env.owner_user_id:
            return EvaluationResult(
                status="terminal_failure", summary="WordEditRun 不存在或越权"
            )
        if run.status not in ("completed", "manual_review"):
            return EvaluationResult(
                status="retryable_failure",
                summary=f"Word 修改流程未完成，当前状态为 {run.status}",
                failed_checks=["edit_run_status"],
                evidence={"edit_run_id": run.id, "status": run.status},
                retry_strategy="从数据库重新读取修改状态，完成 apply/verify 后再结束。",
            )
        changes = list(run.changes or [])
        change_failures = validate_change_records(changes)
        if change_failures:
            return EvaluationResult(
                status="retryable_failure",
                summary="修改记录没有全部完成并通过复检",
                failed_checks=change_failures,
                evidence={"edit_run_id": run.id, "change_count": len(changes)},
                retry_strategy="从原文档重新检查，只执行具有完整定位信息的修改并完成复检。",
            )
        document_id = run.output_document_id or run.source_document_id
        document = session.get(WordDocument, document_id)
        if not document or document.owner_user_id != env.owner_user_id:
            return EvaluationResult(
                status="terminal_failure", summary="修改后的文档不存在或越权"
            )
        if document.parse_status != "parsed":
            return EvaluationResult(
                status="retryable_failure",
                summary="修改后的 Word 副本未成功解析",
                failed_checks=["output_parse_status"],
                retry_strategy="重新生成并解析副本，再执行复检。",
            )
        verification = None
        if run.output_document_id:
            if not run.verification_run_id:
                return EvaluationResult(
                    status="retryable_failure",
                    summary="生成了修订副本但没有复检记录",
                    failed_checks=["missing_verification"],
                    retry_strategy="对最新副本执行 verify_word_edit_tool。",
                )
            verification = session.get(CheckRun, run.verification_run_id)
            if (
                not verification
                or verification.status != "completed"
                or verification.owner_user_id != env.owner_user_id
                or verification.document_id != document_id
                or verification.task_id != env.task_id
                or verification.episode_id != env.episode_id
            ):
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

        diff_results, diff_failures = validate_edit_diffs(session, run, changes)
        remaining_targets, new_high_risk, verification_count_failure = (
            validate_edit_issues(
                session,
                run,
                changes,
                verification,
            )
        )
        if verification_count_failure:
            diff_failures.append(verification_count_failure)
        if remaining_targets:
            diff_failures.append("target_issue_remaining")
        if new_high_risk:
            diff_failures.append("new_high_risk_issue")
        final_counts = dict(env.final_output or {})
        if final_counts:
            if int(final_counts.get("planned_count") or 0) != len(changes):
                diff_failures.append("planned_count_mismatch")
            if int(final_counts.get("applied_count") or 0) != len(changes):
                diff_failures.append("applied_count_mismatch")

        if diff_failures:
            return EvaluationResult(
                status="retryable_failure",
                summary="修改结果与计划、数据库记录或实际 Word 差异不一致",
                failed_checks=list(dict.fromkeys(diff_failures)),
                evidence={
                    "edit_run_id": run.id,
                    "diff_results": diff_results,
                    "remaining_target_issues": remaining_targets,
                    "new_high_risk_issues": new_high_risk,
                },
                retry_strategy="丢弃不可信的修订副本，从原文档重新规划、修改并复检。",
            )

        if run.status == "manual_review" or final_action == "manual_review":
            return EvaluationResult(
                status="manual_review",
                summary="修改事实校验完成，剩余问题需要人工确认",
                evidence={"edit_run_id": run.id, "status": run.status},
            )
    return EvaluationResult(
        status="success",
        summary="Word 修改完成，目标问题、实际差异和复检记录一致",
        evidence={
            "edit_run_id": env.edit_run_id,
            "document_id": document_id,
            "completed_change_count": len(changes),
            "diff_results": diff_results,
        },
    )


def validate_tool_results(tool_results: list[dict]) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    truncated_tools: list[str] = []
    for index, item in enumerate(tool_results):
        if (
            not isinstance(item, dict)
            or not {"tool", "args", "result"}.issubset(item)
            or not isinstance(item.get("args"), dict)
        ):
            failures.append(f"tool_result_envelope:{index}")
            continue
        tool = str(item.get("tool") or "")
        result = item.get("result")
        required = TOOL_RESULT_FIELDS.get(tool)
        if required is None or not isinstance(result, dict):
            failures.append(f"tool_result_type:{tool or index}")
            continue
        missing = sorted(required - set(result))
        if missing:
            failures.append(f"tool_result_fields:{tool}:{','.join(missing)}")
            continue
        issues = result.get("issues")
        try:
            issue_count = int(result.get("issue_count"))
            returned_count = int(result.get("returned_issue_count"))
        except (TypeError, ValueError):
            failures.append(f"tool_result_counts:{tool}")
            continue
        if not isinstance(issues, list) or issue_count < 0 or returned_count < 0:
            failures.append(f"tool_result_counts:{tool}")
            continue
        if returned_count != len(issues) or returned_count > issue_count:
            failures.append(f"tool_result_returned_count:{tool}")
        if any(
            not isinstance(issue, dict) or not ISSUE_FIELDS.issubset(issue)
            for issue in issues
        ):
            failures.append(f"tool_issue_fields:{tool}")
        if returned_count < issue_count:
            truncated_tools.append(tool)
        if tool == "word_check_tool":
            grouped = result.get("grouped_issues")
            if (
                not isinstance(grouped, dict)
                or any(not isinstance(value, list) for value in grouped.values())
                or sum(
                    len(value) for value in grouped.values() if isinstance(value, list)
                )
                != returned_count
            ):
                failures.append("tool_grouped_issue_count:word_check_tool")
    return list(dict.fromkeys(failures)), list(dict.fromkeys(truncated_tools))


def validate_document_counts(
    tool_results: list[dict],
    issues: list[CheckIssue],
    scope_counts: Counter,
) -> list[str]:
    failures: list[str] = []
    for item in tool_results:
        tool = str(item.get("tool") or "")
        result = dict(item.get("result") or {})
        expected = None
        if tool == "word_check_tool":
            expected = scope_counts["basis_excel"] + scope_counts["body_basis"]
        elif tool == "completeness_check_tool":
            expected = scope_counts["completeness"]
        elif tool == "get_issues_tool":
            selected = issues
            for key in ("check_scope", "issue_type", "severity"):
                value = str(result.get(key) or "")
                if value:
                    selected = [
                        issue for issue in selected if str(getattr(issue, key)) == value
                    ]
            expected = len(selected)
        if expected is not None and int(result.get("issue_count") or 0) != expected:
            failures.append(f"database_issue_count:{tool}")
    return failures


def duplicate_issue_ids(issues: list[CheckIssue]) -> list[int]:
    seen: dict[tuple, int] = {}
    duplicates: list[int] = []
    for issue in issues:
        key = (
            issue.check_scope,
            issue.issue_type,
            issue.word_reference_id,
            issue.matched_clause_id,
            issue.matched_standard_record_id,
            issue.section_title,
            issue.paragraph_index,
            issue.original_text,
            issue.reason,
        )
        if key in seen:
            duplicates.extend((seen[key], issue.id))
        else:
            seen[key] = issue.id
    return list(dict.fromkeys(duplicates))


def conflicting_issue_fixes(issues: list[CheckIssue]) -> list[dict[str, object]]:
    targets: dict[tuple, set[str]] = defaultdict(set)
    for issue in issues:
        for replacement in dict(issue.fix_data or {}).get("replacements") or []:
            key = (
                issue.word_reference_id or (issue.section_title, issue.paragraph_index),
                str(replacement.get("target") or ""),
                str(replacement.get("before") or ""),
            )
            targets[key].add(str(replacement.get("after") or ""))
    return [
        {"target": list(key), "after_values": sorted(values)}
        for key, values in targets.items()
        if len(values) > 1
    ]


def validate_change_records(changes: list[dict]) -> list[str]:
    failures: list[str] = []
    for index, change in enumerate(changes):
        if not isinstance(change, dict) or not CHANGE_FIELDS.issubset(change):
            failures.append(f"change_fields:{index}")
            continue
        if change.get("status") not in ("applied", "completed"):
            failures.append(f"change_status:{index}")
        if (
            change.get("verification_status") != "checked"
            or not change.get("verification_run_id")
            or not change.get("output_document_id")
        ):
            failures.append(f"change_verification:{index}")
    return failures


def validate_edit_diffs(
    session, run: WordEditRun, changes: list[dict]
) -> tuple[list[dict], list[str]]:
    batches: dict[tuple[int, int, int], list[dict]] = defaultdict(list)
    failures: list[str] = []
    results: list[dict] = []
    for change in changes:
        key = (
            int(change.get("cycle") or 0),
            int(change.get("input_document_id") or 0),
            int(change.get("output_document_id") or 0),
        )
        batches[key].append(change)

    for (cycle, input_id, output_id), batch in batches.items():
        source = session.get(WordDocument, input_id)
        output = session.get(WordDocument, output_id)
        if (
            not source
            or not output
            or source.owner_user_id != run.owner_user_id
            or output.owner_user_id != run.owner_user_id
            or output.edit_run_id != run.id
            or output.edit_cycle != cycle
        ):
            failures.append(f"change_document_chain:{cycle}")
            continue
        try:
            result = validate_word_change_diff(
                resolve_word_document_path(source),
                resolve_word_document_path(output),
                batch,
            )
        except Exception as exc:
            failures.append(f"word_diff_error:{cycle}")
            results.append({"cycle": cycle, "ok": False, "error": str(exc)})
            continue
        results.append({"cycle": cycle, **result})
        if not result["ok"]:
            failures.extend(str(value) for value in result["errors"])
        if int(result["verified_change_count"]) != len(batch):
            failures.append(f"change_count_mismatch:{cycle}")
    return results, failures


def validate_edit_issues(
    session,
    run: WordEditRun,
    changes: list[dict],
    verification: CheckRun | None,
) -> tuple[list[tuple], list[tuple], str]:
    if not run.output_document_id:
        return [], [], ""
    scopes = ("basis_excel", "body_basis")
    source_issues = (
        session.query(CheckIssue)
        .filter(
            CheckIssue.document_id == run.source_document_id,
            CheckIssue.check_scope.in_(scopes),
        )
        .all()
    )
    output_issues = (
        session.query(CheckIssue)
        .filter(
            CheckIssue.document_id == run.output_document_id,
            CheckIssue.check_scope.in_(scopes),
        )
        .all()
    )
    target_keys = set()
    for change in changes:
        try:
            location = locator_key(dict(change.get("locator") or {}))
        except (KeyError, TypeError, ValueError):
            continue
        target_keys.add((str(change.get("issue_type") or ""), location))
    output_keys = {issue_location_key(session, issue) for issue in output_issues}
    source_high = {
        issue_location_key(session, issue)
        for issue in source_issues
        if issue.severity == "high"
    }
    output_high = {
        issue_location_key(session, issue)
        for issue in output_issues
        if issue.severity == "high"
    }
    count_failure = ""
    if verification and int(verification.issue_count or 0) != len(output_issues):
        count_failure = "verification_issue_count"
    return (
        sorted(target_keys & output_keys, key=str),
        sorted(output_high - source_high, key=str),
        count_failure,
    )


def issue_location_key(session, issue: CheckIssue) -> tuple:
    reference = (
        session.get(WordReference, issue.word_reference_id)
        if issue.word_reference_id
        else None
    )
    if reference:
        try:
            location = locator_key(dict(reference.locator or {}))
        except (KeyError, TypeError, ValueError):
            location = ("paragraph", issue.paragraph_index)
    else:
        location = ("paragraph", issue.paragraph_index)
    return (issue.issue_type, location)
