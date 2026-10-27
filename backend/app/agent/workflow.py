import json
import re
from datetime import date

from fastapi.encoders import jsonable_encoder

from app.agent.environments import (
    DocumentCheckEnvironment,
    WordEditEnvironment,
)
from app.agent.harness import HarnessResult, run_agent
from app.agent.runtime_store import (
    create_task,
    fail_task,
    finish_task,
    load_task,
)
from app.llm import USER_REPORT_FORMAT_RULES, call_llm
from app.services.session_memory import (
    append_turn,
    load_session_context,
    prepare_session,
)


DEFAULT_MAX_EDIT_CYCLES = 3
WORD_EDIT_RESULT_TOOL = "word_edit_result"
QUEUED_STATUS = "queued"


def route_task(*, message: str, requested_mode: str) -> tuple[str, list[str]]:
    """Route the two supported tasks without another LLM call."""
    mode = requested_mode.strip()
    if mode == "knowledge":
        raise ValueError("知识文档问答已移除；当前支持文档检查和文档修改")
    if mode == "clause_extract":
        raise ValueError("PDF 强条抽取已移除；当前只支持 Word 文档检查和修改")
    if mode == "word_edit":
        task_type = "word_edit"
    elif mode in ("standard", "document_check", "word_check"):
        task_type = "document_check"
    elif any(
        word in message
        for word in ("抽取强条", "提取强条", "抽取强制性条文", "提取强制性条文")
    ):
        raise ValueError("PDF 强条抽取已移除；可继续检查 Word 中的强条引用")
    elif any(word in message for word in ("修改", "修复", "修订", "生成副本")):
        task_type = "word_edit"
    else:
        task_type = "document_check"

    checks = ["consistency", "completeness"]
    if task_type == "document_check" and "全面" not in message:
        completeness = any(
            word in message for word in ("完整性", "模板", "章节", "标题", "占位符")
        )
        consistency = any(
            word in message for word in ("一致性", "引用", "标准", "规范", "依据")
        )
        if completeness and not consistency:
            checks = ["completeness"]
        elif consistency and not completeness:
            checks = ["consistency"]
    return task_type, checks


def agent_check(
    message: str,
    document_id: int | None = None,
    publish_date: date | None = None,
    owner_user_id: int | None = None,
    session_id: int | None = None,
    requested_mode: str = "",
    max_edit_cycles: int = DEFAULT_MAX_EDIT_CYCLES,
) -> dict[str, object]:
    """Create a task and run it inline in the calling thread."""
    task_id, _ = create_agent_task(
        message=message,
        document_id=document_id,
        publish_date=publish_date,
        owner_user_id=owner_user_id,
        session_id=session_id,
        requested_mode=requested_mode,
        max_edit_cycles=max_edit_cycles,
        status="running",
    )
    return run_agent_task(task_id)


def enqueue_agent_check(
    message: str,
    document_id: int | None = None,
    publish_date: date | None = None,
    owner_user_id: int | None = None,
    session_id: int | None = None,
    requested_mode: str = "",
    max_edit_cycles: int = DEFAULT_MAX_EDIT_CYCLES,
) -> dict[str, object]:
    """Create a queued task for a worker and return immediately."""
    task_id, task_session_id = create_agent_task(
        message=message,
        document_id=document_id,
        publish_date=publish_date,
        owner_user_id=owner_user_id,
        session_id=session_id,
        requested_mode=requested_mode,
        max_edit_cycles=max_edit_cycles,
        status=QUEUED_STATUS,
    )
    return {"task_id": task_id, "session_id": task_session_id, "status": QUEUED_STATUS}


def create_agent_task(
    *,
    message: str,
    document_id: int | None,
    publish_date: date | None,
    owner_user_id: int | None,
    session_id: int | None,
    requested_mode: str,
    max_edit_cycles: int,
    status: str,
) -> tuple[int, int]:
    """Validate the request and persist everything a worker needs to run it."""
    if owner_user_id is None:
        raise ValueError("缺少当前访客")
    session_context = prepare_session(
        owner_user_id=owner_user_id,
        session_id=session_id,
        message=message,
        document_id=document_id,
    )
    document_id = document_id or session_context.document_id
    task_type, checks = route_task(
        message=message,
        requested_mode=requested_mode,
    )

    if document_id is None:
        raise ValueError("请先上传或选择需要检查或修改的 Word 文档")
    input_data = {
        "document_id": document_id,
        "publish_date": publish_date.isoformat() if publish_date else None,
        "checks": checks,
        "max_edit_cycles": max_edit_cycles,
    }
    task_id = create_task(
        owner_user_id=owner_user_id,
        session_id=session_context.session_id,
        task_type=task_type,
        user_message=message,
        input_data=input_data,
        status=status,
    )
    return task_id, session_context.session_id


def run_agent_task(task_id: int) -> dict[str, object]:
    """Execute a persisted task; any crash is recorded on the task before re-raising."""
    try:
        return _run_agent_task(task_id)
    except Exception as exc:
        fail_task(task_id=task_id, error_message=f"{type(exc).__name__}: {exc}")
        raise


def _run_agent_task(task_id: int) -> dict[str, object]:
    task = load_task(task_id)
    owner_user_id = task.owner_user_id
    message = task.user_message
    task_type = task.task_type
    input_data = dict(task.input_data or {})
    document_id = input_data["document_id"]
    checks = list(input_data.get("checks") or [])
    publish_date = (
        date.fromisoformat(input_data["publish_date"])
        if input_data.get("publish_date")
        else None
    )
    max_edit_cycles = int(input_data.get("max_edit_cycles") or DEFAULT_MAX_EDIT_CYCLES)
    if task.session_id is None:
        raise ValueError("任务所属会话已被删除")
    session_context = load_session_context(owner_user_id, task.session_id)

    def environment_factory(episode_id: int):
        common = {
            "task_id": task_id,
            "episode_id": episode_id,
            "owner_user_id": owner_user_id,
            "session_id": session_context.session_id,
            "message": message,
        }
        if task_type == "document_check":
            return DocumentCheckEnvironment(
                **common,
                document_id=document_id,
                publish_date=publish_date,
                checks=checks,
            )
        if task_type == "word_edit":
            env = WordEditEnvironment(**common, document_id=int(document_id))
            env.max_edit_cycles = max(1, min(int(max_edit_cycles), 5))
            env.max_steps = max(8, env.max_edit_cycles * 4 + 4)
            return env
        raise ValueError(f"不支持的任务类型：{task_type}")

    result = run_agent(
        task_id=task_id,
        owner_user_id=owner_user_id,
        task_type=task_type,
        user_message=message,
        conversation_context=session_context.conversation,
        environment_factory=environment_factory,
    )
    answer = answer_for_result(
        message=message,
        result=result,
    )
    output = {**result.output, "answer": answer}

    run_id, tool_results, final_document_id = legacy_result_fields(result)
    if isinstance(result.environment, DocumentCheckEnvironment):
        result.environment.persist_business_result(
            status=result.evaluation.status,
            answer=answer,
            error=""
            if result.evaluation.status == "success"
            else result.evaluation.summary,
        )
    append_turn(
        owner_user_id=owner_user_id,
        session_id=session_context.session_id,
        user_message=message,
        assistant_message=answer,
        run_id=run_id,
        run_type="word_check" if task_type == "document_check" else task_type,
        document_id=final_document_id or document_id,
        task_id=task_id,
        episode_id=result.episode_id,
    )
    response = {
        "session_id": session_context.session_id,
        "task_id": task_id,
        "episode_id": result.episode_id,
        "attempt_no": result.attempt_no,
        "status": result.evaluation.status,
        "evaluation": result.evaluation.model_dump(),
        "run_id": run_id,
        "tool_plan": {"mode": task_type, "checks": checks},
        "tool_results": tool_results,
        "answer": answer,
    }
    # Terminal status is written last so pollers never see a finished task without its response.
    finish_task(
        task_id=task_id,
        episode_id=result.episode_id,
        evaluation=result.evaluation,
        output=output,
        response=jsonable_encoder(response),
    )
    return response


def answer_for_result(*, message: str, result: HarnessResult) -> str:
    if result.evaluation.status != "success":
        business_message = str(result.output.get("message") or "")
        return business_message or result.evaluation.summary
    if isinstance(result.environment, WordEditEnvironment):
        return str(result.output.get("message") or result.evaluation.summary)
    issue_count = int(result.evaluation.evidence.get("issue_count") or 0)
    scope_counts = dict(result.evaluation.evidence.get("scope_counts") or {})
    tool_results = [
        item
        for item in list(result.output.get("tool_results") or [])
        if item.get("tool") in ("word_check_tool", "completeness_check_tool")
    ]
    prompt = f"""
你是“灵枢·规鉴”的文档检查报告生成器。只能依据工具结果总结，不能编造。
{USER_REPORT_FORMAT_RULES}
第一行必须写“本次检查共发现 {issue_count} 个问题。”，不得根据截断的 issues 列表重新计算总数。
再按一致性与完整性列出高风险、警告和必要明细；没有执行的检查不要声称已检查。
用户问题：{message}
确定性数据库统计：总数 {issue_count}，分 scope {json.dumps(scope_counts, ensure_ascii=False)}
工具结果：{json.dumps(tool_results, ensure_ascii=False, default=str)}
"""
    try:
        return ensure_answer_issue_count(call_llm(prompt), issue_count)
    except Exception:
        return f"本次检查共发现 {issue_count} 个问题。"


def ensure_answer_issue_count(answer: str, issue_count: int) -> str:
    """Keep the report headline consistent with the deterministic DB count."""
    expected = f"本次检查共发现 {issue_count} 个问题。"
    lines = answer.strip().splitlines()
    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first is None:
        return expected
    if re.search(r"共(?:计|发现|返回|记录)?\s*\d+\s*(?:个|条|处)\s*问题", lines[first]):
        lines[first] = expected
        return "\n".join(lines)
    return f"{expected}\n\n{answer.strip()}"


def legacy_result_fields(
    result: HarnessResult,
) -> tuple[int | None, list[dict], int | None]:
    env = result.environment
    if isinstance(env, DocumentCheckEnvironment):
        return env.check_run_id, list(env.tool_results), env.document_id
    if isinstance(env, WordEditEnvironment):
        return (
            None,
            [{"tool": WORD_EDIT_RESULT_TOOL, "args": {}, "result": result.output}],
            result.output.get("document_id"),
        )
    return None, [], None


def run_word_edit_loop(
    *,
    message: str,
    document_id: int,
    owner_user_id: int,
    session_id: int | None = None,
    max_edit_cycles: int = DEFAULT_MAX_EDIT_CYCLES,
    max_steps: int | None = None,
) -> dict[str, object]:
    del max_steps
    result = agent_check(
        message=message,
        document_id=document_id,
        owner_user_id=owner_user_id,
        session_id=session_id,
        requested_mode="word_edit",
        max_edit_cycles=max_edit_cycles,
    )
    return dict(result["tool_results"][-1]["result"])
