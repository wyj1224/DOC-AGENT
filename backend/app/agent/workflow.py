import json
from datetime import date, datetime, timezone

from app.agent.registry import (
    CLAUSE_EXTRACTION_TOOL_NAMES,
    PLANNER_TOOL_NAMES,
    WORD_EDIT_TOOL_NAMES,
    clause_extraction_tool_prompt_text,
    run_tool,
    tool_prompt_text,
    word_edit_tool_prompt_text,
)
from app.db.database import SessionLocal
from app.db.models import CheckRun
from app.llm import USER_REPORT_FORMAT_RULES, call_llm
from app.services.session_memory import append_turn, prepare_session
from app.services.clause_extraction import (
    answer_clause_extraction_question,
    append_clause_extraction_trace,
    fail_clause_extraction_run,
    finalize_clause_extraction_run,
    get_clause_extraction_result,
    get_clause_extraction_state,
    start_clause_extraction_run,
)
from app.services.word_edit_workflow import (
    append_word_edit_trace,
    fail_word_edit_run,
    finalize_word_edit_run,
    get_word_edit_state,
    start_word_edit_run,
)


WORD_EDIT_RESULT_TOOL = "word_edit_result"
CLAUSE_EXTRACTION_RESULT_TOOL = "clause_extraction_result"
DEFAULT_MAX_EDIT_CYCLES = 3


def planner(
    message: str,
    document_id: int | None = None,
    file_path: str = "",
    conversation_context: str = "无",
    requested_mode: str = "",
) -> dict[str, object]:
    prompt = f"""
你是通信工程设计说明校核 Agent 的入口 planner。你只负责识别任务模式，不负责预先编排 Word 修改步骤。只能输出 JSON。

普通校核与问答工具：
{tool_prompt_text()}

任务模式：
- standard：知识问答、校核、完整性检查、查询已有问题。为这种模式生成 steps。
- word_edit：用户要求修改、修复或生成修订版 Word。此时 steps 必须为空，后续由 Agent Loop 根据每次观察自主选择工具。
- clause_extract：用户上传 PDF 并要求自动识别、提取、汇总强制性条文，或继续追问当前 PDF 抽取结果。steps 必须为空，由强条抽取 Agent Loop 执行。

check_scope 可选：basis_excel、body_basis、completeness。

规则：
- 如果用户是在查询知识库或询问上传资料中的事实，选择 standard 并调用 knowledge_query_tool。
- standard 模式下，没有 document_id 但有 file_path 时，第一步必须 parse_word_tool；已有 document_id 时不要重复解析。
- 只问完整性、模板、标题缺失、正文空白、占位符或关键章节模板差异时，调用 completeness_check_tool，再查询 completeness。
- 全面检查或生成校核报告时，调用 word_check_tool、completeness_check_tool，并查询三个 check_scope。
- 只查看已有问题时，可以只调用 get_issues_tool。
- 用户要求帮忙修改、修复或生成修订版时，必须选择 word_edit；不要在这里生成固定修改步骤。
- file_path 为 PDF 或用户明确要求从 PDF 提取强制性条文时，选择 clause_extract；不能把 PDF 写入知识库或 mandatory_clauses。
- requested_mode=clause_extract 时必须选择 clause_extract。
- 结合会话上下文理解“继续修改”“这个文档”“刚才的问题”等指代。

会话上下文：
{conversation_context}

用户输入：{message}
document_id：{document_id}
file_path：{file_path}
前端请求模式：{requested_mode or '未指定'}

输出格式：
{{
  "mode": "standard | word_edit | clause_extract",
  "steps": [
    {{"tool": "word_check_tool", "args": {{"document_id": {document_id or "null"}, "replace": true, "issue_limit": 1}}}}
  ]
}}
"""
    value = parse_json(call_llm(prompt))
    mode = str(value.get("mode") or "standard")
    if mode not in ("standard", "word_edit", "clause_extract"):
        raise ValueError("Planner 返回了无效任务模式")
    steps = list(value.get("steps") or [])
    if mode in ("word_edit", "clause_extract"):
        steps = []
    return {
        "mode": mode,
        "steps": steps,
    }


def execute_tools(
    tool_plan: dict[str, object],
    publish_date: date | None = None,
    owner_user_id: int | None = None,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    current_document_id: int | None = None
    for step in list(tool_plan.get("steps") or []):
        tool_name = str(step.get("tool") or "")
        if tool_name not in PLANNER_TOOL_NAMES:
            raise ValueError(f"普通任务不允许调用工具：{tool_name}")
        args = dict(step.get("args") or {})
        if current_document_id and not args.get("document_id"):
            args["document_id"] = current_document_id
        if tool_name == "word_check_tool":
            args["publish_date"] = publish_date
        if tool_name == "parse_word_tool":
            args = {key: args[key] for key in ("file_path", "document_id") if key in args}
        if tool_name in {
            "parse_word_tool",
            "word_check_tool",
            "completeness_check_tool",
            "get_issues_tool",
        }:
            args["owner_user_id"] = owner_user_id
        result = run_tool(tool_name, args)
        if tool_name == "parse_word_tool":
            current_document_id = int(result["document_id"])
        results.append({"tool": tool_name, "args": args, "result": result})
    return results


def run_word_edit_loop(
    *,
    message: str,
    document_id: int,
    owner_user_id: int,
    session_id: int | None = None,
    max_edit_cycles: int = 3,
    max_steps: int | None = None,
) -> dict[str, object]:
    """Run the outer Agent Loop; Word tools execute only one durable action at a time."""
    max_edit_cycles = clamp_int(max_edit_cycles, default=3, minimum=1, maximum=5)
    max_steps = clamp_int(
        max_steps,
        default=max(8, max_edit_cycles * 4 + 4),
        minimum=4,
        maximum=32,
    )
    started = start_word_edit_run(
        document_id=document_id,
        owner_user_id=owner_user_id,
        session_id=session_id,
    )
    edit_run_id = int(started["edit_run_id"])
    latest_observation: dict[str, object] = {
        "tool": "start_word_edit_run",
        "result": compact_word_edit_state(started),
    }
    remaining_issues: list[dict[str, object]] = []

    try:
        for loop_step in range(1, max_steps + 1):
            state = get_word_edit_state(edit_run_id=edit_run_id, owner_user_id=owner_user_id)
            options = allowed_word_edit_actions(
                state=state,
                latest_observation=latest_observation,
                max_edit_cycles=max_edit_cycles,
            )
            decision = decide_next_word_edit_action(
                message=message,
                state=state,
                latest_observation=latest_observation,
                allowed_actions=options,
                loop_step=loop_step,
                max_steps=max_steps,
                max_edit_cycles=max_edit_cycles,
            )
            append_word_edit_trace(
                edit_run_id=edit_run_id,
                owner_user_id=owner_user_id,
                phase=phase_for_decision(decision),
                actor="llm",
                name="next_word_edit_action",
                output=decision,
                summary=str(decision.get("reason") or "Agent 已选择下一动作。"),
            )

            action = str(decision["action"])
            if action in ("finish", "manual_review"):
                return finalize_word_edit_run(
                    edit_run_id=edit_run_id,
                    owner_user_id=owner_user_id,
                    remaining_issues=remaining_issues,
                    action=action,
                    reason=str(decision.get("reason") or ""),
                )

            tool_name = str(decision.get("tool") or "")
            tool_args = trusted_word_edit_args(
                tool_name=tool_name,
                decision=decision,
                state=state,
                latest_observation=latest_observation,
                owner_user_id=owner_user_id,
            )
            result = run_tool(tool_name, tool_args)
            compact_result = compact_word_edit_observation(tool_name, result)
            append_word_edit_trace(
                edit_run_id=edit_run_id,
                owner_user_id=owner_user_id,
                phase=phase_for_tool(tool_name),
                actor="tool",
                name=tool_name,
                output=compact_result,
                summary=summarize_word_edit_tool(tool_name, result),
            )
            latest_observation = {"tool": tool_name, "result": compact_result}
            if tool_name == "inspect_consistency_issues_tool":
                remaining_issues = list(result.get("issues") or [])
            elif tool_name == "verify_word_edit_tool":
                remaining_issues = list(result.get("remaining_issues") or [])

        return finalize_word_edit_run(
            edit_run_id=edit_run_id,
            owner_user_id=owner_user_id,
            remaining_issues=remaining_issues,
            action="manual_review",
            reason=f"Agent Loop 已达到 {max_steps} 步安全预算。",
        )
    except Exception as exc:
        fail_word_edit_run(
            edit_run_id=edit_run_id,
            owner_user_id=owner_user_id,
            error_message=str(exc),
        )
        raise


def run_clause_extraction_loop(
    *,
    message: str,
    file_path: str,
    owner_user_id: int,
    session_id: int | None = None,
    max_steps: int = 8,
) -> dict[str, object]:
    """Run a small durable Agent Loop around the fixed PDF extraction tools."""
    started = start_clause_extraction_run(
        file_path=file_path,
        owner_user_id=owner_user_id,
        session_id=session_id,
    )
    extraction_run_id = int(started["extraction_run_id"])
    if str(started.get("status")) in ("completed", "manual_review"):
        return get_clause_extraction_result(
            extraction_run_id=extraction_run_id,
            owner_user_id=owner_user_id,
        )

    latest_observation: dict[str, object] = {
        "tool": "start_clause_extraction_run",
        "result": compact_clause_extraction_state(started),
    }
    try:
        for loop_step in range(1, max_steps + 1):
            state = get_clause_extraction_state(
                extraction_run_id=extraction_run_id,
                owner_user_id=owner_user_id,
            )
            options = allowed_clause_extraction_actions(state)
            decision = decide_next_clause_extraction_action(
                message=message,
                state=state,
                latest_observation=latest_observation,
                allowed_actions=options,
                loop_step=loop_step,
                max_steps=max_steps,
            )
            append_clause_extraction_trace(
                extraction_run_id=extraction_run_id,
                owner_user_id=owner_user_id,
                phase=phase_for_clause_decision(decision),
                actor="llm",
                name="next_clause_extraction_action",
                output=decision,
                summary=str(decision.get("reason") or "Agent 已选择下一动作。"),
            )

            action = str(decision["action"])
            if action in ("finish", "manual_review"):
                return finalize_clause_extraction_run(
                    extraction_run_id=extraction_run_id,
                    owner_user_id=owner_user_id,
                    action=action,
                    reason=str(decision.get("reason") or ""),
                )

            tool_name = str(decision.get("tool") or "")
            tool_args = trusted_clause_extraction_args(
                tool_name=tool_name,
                extraction_run_id=extraction_run_id,
                owner_user_id=owner_user_id,
            )
            result = run_tool(tool_name, tool_args)
            compact_result = compact_clause_extraction_observation(tool_name, result)
            append_clause_extraction_trace(
                extraction_run_id=extraction_run_id,
                owner_user_id=owner_user_id,
                phase=phase_for_clause_tool(tool_name),
                actor="tool",
                name=tool_name,
                output=compact_result,
                summary=summarize_clause_extraction_tool(tool_name, result),
            )
            latest_observation = {"tool": tool_name, "result": compact_result}

        raise ValueError(f"强条抽取 Agent Loop 已达到 {max_steps} 步安全预算")
    except Exception as exc:
        fail_clause_extraction_run(
            extraction_run_id=extraction_run_id,
            owner_user_id=owner_user_id,
            error_message=str(exc),
        )
        raise


def allowed_clause_extraction_actions(
    state: dict[str, object],
) -> list[dict[str, object]]:
    status = str(state.get("status") or "")
    if status == "planning":
        return [{"action": "call_tool", "tool": "inspect_clause_pdf_tool"}]
    if status == "inspected":
        return [{"action": "call_tool", "tool": "extract_clause_candidates_tool"}]
    if status == "extracted":
        return [{"action": "call_tool", "tool": "verify_clause_candidates_tool"}]
    if status == "verified":
        if state.get("requires_review"):
            return [{"action": "manual_review"}]
        return [{"action": "finish"}, {"action": "manual_review"}]
    return []


def decide_next_clause_extraction_action(
    *,
    message: str,
    state: dict[str, object],
    latest_observation: dict[str, object],
    allowed_actions: list[dict[str, object]],
    loop_step: int,
    max_steps: int,
) -> dict[str, object]:
    if not allowed_actions:
        raise ValueError(f"强条抽取任务状态 {state.get('status')} 没有可执行动作")
    prompt = f"""
你是 PDF 强制性条文抽取 Agent。你处于真实的单步 Agent Loop 中，只能根据数据库状态和上一条工具观察选择一个下一动作，只输出 JSON。

可用工具：
{clause_extraction_tool_prompt_text()}

规则：
- 只能从 allowed_actions 中选择，每次最多调用一个工具。
- 类型必须自动识别，不能要求用户选择“公告列出”“黑体标识”或“无强条”。
- 先检查 PDF，再抽取候选，之后必须验证；验证通过才能 finish。
- 工具结果提示证据缺失或冲突时选择 manual_review，不得编造强条。
- 本任务结果只写 ClauseExtractionRun，不写知识库和 mandatory_clauses。

用户目标：{message}
Loop 步数：{loop_step}/{max_steps}
数据库状态：
{json.dumps(compact_clause_extraction_state(state), ensure_ascii=False)}
上一条观察：
{json.dumps(latest_observation, ensure_ascii=False)}
allowed_actions：
{json.dumps(allowed_actions, ensure_ascii=False)}

输出格式：
{{
  "action": "call_tool | finish | manual_review",
  "tool": "inspect_clause_pdf_tool",
  "args": {{}},
  "reason": "简短中文理由"
}}
"""
    errors: list[str] = []
    for attempt in range(2):
        correction = ""
        if errors:
            correction = f"\n上一份输出无效：{errors[-1]}。请严格从 allowed_actions 中选择。"
        try:
            raw = parse_json(call_llm(prompt + correction))
            return normalize_clause_extraction_decision(raw, allowed_actions)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))
            if attempt == 1:
                raise ValueError(f"LLM 连续两次返回无效的强条抽取决策：{exc}") from exc
    raise ValueError("LLM 未返回强条抽取决策")


def normalize_clause_extraction_decision(
    raw: dict[str, object], allowed_actions: list[dict[str, object]]
) -> dict[str, object]:
    action = str(raw.get("action") or "")
    tool_name = str(raw.get("tool") or "")
    pair = (action, tool_name if action == "call_tool" else "")
    allowed_pairs = {
        (str(item.get("action") or ""), str(item.get("tool") or ""))
        for item in allowed_actions
    }
    if pair not in allowed_pairs:
        raise ValueError(f"LLM 返回了当前状态不允许的动作：{action}/{tool_name}")
    return {
        "action": action,
        "tool": tool_name if action == "call_tool" else "",
        "args": {},
        "reason": str(raw.get("reason") or ""),
    }


def trusted_clause_extraction_args(
    *, tool_name: str, extraction_run_id: int, owner_user_id: int
) -> dict[str, object]:
    if tool_name not in CLAUSE_EXTRACTION_TOOL_NAMES:
        raise ValueError(f"强条抽取 Agent Loop 不允许调用工具：{tool_name}")
    return {
        "extraction_run_id": extraction_run_id,
        "owner_user_id": owner_user_id,
    }


def allowed_word_edit_actions(
    *,
    state: dict[str, object],
    latest_observation: dict[str, object],
    max_edit_cycles: int,
) -> list[dict[str, object]]:
    """Expose only actions whose data preconditions are currently satisfied."""
    status = str(state.get("status") or "")
    observation_tool = str(latest_observation.get("tool") or "")
    observation = dict(latest_observation.get("result") or {})
    options: list[dict[str, object]] = []

    if status == "planning":
        options.append({"action": "call_tool", "tool": "inspect_consistency_issues_tool"})
    elif status == "awaiting_plan":
        issue_count = int(observation.get("issue_count") or 0)
        auto_fixable_count = int(observation.get("auto_fixable_issue_count") or 0)
        if observation_tool == "inspect_consistency_issues_tool" and issue_count == 0:
            options.append({"action": "finish"})
        if auto_fixable_count > 0 and int(state.get("cycle") or 0) < max_edit_cycles:
            options.append({"action": "call_tool", "tool": "prepare_word_edit_tool"})
    elif status == "ready" and int(state.get("pending_count") or 0) > 0:
        options.append({"action": "call_tool", "tool": "apply_word_edit_tool"})
    elif status == "applied" and state.get("output_document_id"):
        options.append({"action": "call_tool", "tool": "verify_word_edit_tool"})
    elif status == "awaiting_decision":
        remaining_count = int(observation.get("remaining_issue_count") or 0)
        auto_fixable_count = int(observation.get("auto_fixable_issue_count") or 0)
        if (
            observation_tool == "verify_word_edit_tool"
            and remaining_count == 0
            and int(state.get("failed_count") or 0) == 0
        ):
            options.append({"action": "finish"})
        if auto_fixable_count > 0 and int(state.get("cycle") or 0) < max_edit_cycles:
            options.append({"action": "call_tool", "tool": "prepare_word_edit_tool"})

    if status in ("planning", "awaiting_plan", "awaiting_decision", "failed"):
        options.append({"action": "manual_review"})
    return options


def decide_next_word_edit_action(
    *,
    message: str,
    state: dict[str, object],
    latest_observation: dict[str, object],
    allowed_actions: list[dict[str, object]],
    loop_step: int,
    max_steps: int,
    max_edit_cycles: int,
) -> dict[str, object]:
    prompt = f"""
你是 Word 修订 Agent。你位于真正的 Agent Loop 中：每次只能根据数据库记忆和上一条工具观察选择一个下一动作，只输出 JSON。

可用的单步工具：
{word_edit_tool_prompt_text()}

安全约束：
- 只能从 allowed_actions 中选择；不能预先输出一串固定步骤。
- LLM 只能选择工具和 auto_fixable=true 的 issue_id，不能生成 before、after、locator、owner_user_id 或 document_id。
- 有明确可修问题时优先 prepare；有 pending changes 时执行 apply；写入副本后应 verify。
- 观察中问题为 0 时 finish；有问题但无法安全修改或预算不足时 manual_review。
- 修改工具会从 WordEditRun.changes 读取可信指令，每轮都基于最新输出副本。

用户目标：{message}
当前 Loop 步数：{loop_step}/{max_steps}
最大修改轮数安全预算：{max_edit_cycles}
数据库状态：
{json.dumps(compact_word_edit_state(state), ensure_ascii=False)}
上一条观察：
{json.dumps(latest_observation, ensure_ascii=False)}
allowed_actions：
{json.dumps(allowed_actions, ensure_ascii=False)}

输出格式：
{{
  "action": "call_tool | finish | manual_review",
  "tool": "prepare_word_edit_tool",
  "args": {{"selected_issue_ids": [1, 2]}},
  "reason": "简短中文理由"
}}
"""
    errors: list[str] = []
    for decision_attempt in range(2):
        correction = ""
        if errors:
            correction = f"\n上一份输出无效：{errors[-1]}。请严格从 allowed_actions 选择并重新输出 JSON。"
        try:
            raw = parse_json(call_llm(prompt + correction))
            return normalize_word_edit_decision(raw, allowed_actions, latest_observation)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))
            if decision_attempt == 1:
                raise ValueError(f"LLM 连续两次返回无效的 Word 修订决策：{exc}") from exc
    raise ValueError("LLM 未返回 Word 修订决策")


def normalize_word_edit_decision(
    raw: dict[str, object],
    allowed_actions: list[dict[str, object]],
    latest_observation: dict[str, object],
) -> dict[str, object]:
    action = str(raw.get("action") or "")
    tool_name = str(raw.get("tool") or "")
    allowed_pairs = {(str(item.get("action") or ""), str(item.get("tool") or "")) for item in allowed_actions}
    pair = (action, tool_name if action == "call_tool" else "")
    if pair not in allowed_pairs:
        raise ValueError(f"LLM 返回了当前状态不允许的动作：{action}/{tool_name}")

    args = dict(raw.get("args") or {})
    decision: dict[str, object] = {
        "action": action,
        "tool": tool_name if action == "call_tool" else "",
        "args": {},
        "reason": str(raw.get("reason") or ""),
    }
    if tool_name == "prepare_word_edit_tool":
        allowed_ids = auto_fixable_issue_ids(latest_observation)
        selected_ids = []
        for value in list(args.get("selected_issue_ids") or []):
            try:
                issue_id = int(value)
            except (TypeError, ValueError):
                continue
            if issue_id in allowed_ids and issue_id not in selected_ids:
                selected_ids.append(issue_id)
        if not selected_ids:
            raise ValueError("LLM 选择 prepare，但没有选择当前观察中的可修改问题")
        decision["args"] = {"selected_issue_ids": selected_ids}
    return decision


def trusted_word_edit_args(
    *,
    tool_name: str,
    decision: dict[str, object],
    state: dict[str, object],
    latest_observation: dict[str, object],
    owner_user_id: int,
) -> dict[str, object]:
    if tool_name not in WORD_EDIT_TOOL_NAMES:
        raise ValueError(f"Word Agent Loop 不允许调用工具：{tool_name}")
    args: dict[str, object] = {
        "edit_run_id": int(state["edit_run_id"]),
        "owner_user_id": owner_user_id,
    }
    if tool_name == "prepare_word_edit_tool":
        observation = dict(latest_observation.get("result") or {})
        expected_document_id = int(observation.get("document_id") or state["document_id"])
        args.update(
            {
                "selected_issue_ids": list(dict(decision.get("args") or {})["selected_issue_ids"]),
                "expected_document_id": expected_document_id,
            }
        )
    return args


def final_answer(
    message: str,
    tool_results: list[dict[str, object]],
    conversation_context: str = "无",
) -> str:
    for item in tool_results:
        if item["tool"] == "knowledge_query_tool":
            return str(item["result"]["answer"])
        if item["tool"] == CLAUSE_EXTRACTION_RESULT_TOOL:
            return answer_clause_extraction_question(
                message=message,
                result=dict(item["result"]),
                conversation_context=conversation_context,
            )
        if item["tool"] in (WORD_EDIT_RESULT_TOOL, "fix_consistency_issues_tool"):
            return str(item["result"]["message"])

    prompt = f"""
你是“灵枢·规鉴”——基于大模型的通信工程强制性条文智能检测系统。
请根据工具返回的结构化结果生成简洁、稳定、易读的中文报告，不要编造。

{USER_REPORT_FORMAT_RULES}

校核报告还必须遵守：
1. 先给一段简短总览，再按“依据章节”“正文一致性”“完整性”分类；没有结果的分类不要输出。
2. 优先展示高风险和警告；提示类问题只做简要归纳。

格式示例：
## 完整性
- **关键章节相似度不足（2处）**
  1. 安全生产要求：文字相似度为 92.4%，低于 95%。
  2. 工程验收：缺少模板中的一段验收说明。

用户问题：{message}
会话上下文：{conversation_context}
工具结果 JSON：
{json.dumps(tool_results, ensure_ascii=False)}
"""
    return call_llm(prompt)


def agent_check(
    message: str,
    document_id: int | None = None,
    file_path: str = "",
    publish_date: date | None = None,
    owner_user_id: int | None = None,
    session_id: int | None = None,
    requested_mode: str = "",
) -> dict[str, object]:
    if owner_user_id is None:
        raise ValueError("缺少当前访客")
    session_context = prepare_session(
        owner_user_id=owner_user_id,
        session_id=session_id,
        message=message,
        document_id=document_id,
    )
    document_id = session_context.document_id
    started_at = datetime.now(timezone.utc)
    run_type = requested_mode if requested_mode in ("knowledge", "clause_extract") else "unknown"
    plan: dict[str, object] = {}
    run_id = create_check_run(
        owner_user_id,
        session_context.session_id,
        document_id,
        message,
        started_at,
        run_type,
    )
    try:
        if requested_mode == "clause_extract":
            plan = {"mode": "clause_extract", "steps": []}
        elif requested_mode == "knowledge":
            plan = {
                "mode": "standard",
                "steps": [{"tool": "knowledge_query_tool", "args": {"question": message, "limit": 5}}],
            }
        else:
            plan = planner(
                message=message,
                document_id=document_id,
                file_path=file_path,
                conversation_context=session_context.conversation,
                requested_mode=requested_mode,
            )
        run_type = run_type_for_plan(plan)
        clause_extraction_run_id: int | None = None
        if plan["mode"] == "word_edit":
            tool_results: list[dict[str, object]] = []
            if document_id is None:
                if not file_path:
                    raise ValueError("请先上传或选择需要修改的 Word 文档")
                parse_args = {"file_path": file_path, "owner_user_id": owner_user_id}
                parsed = run_tool("parse_word_tool", parse_args)
                document_id = int(parsed["document_id"])
                tool_results.append({"tool": "parse_word_tool", "args": parse_args, "result": parsed})
            edit_result = run_word_edit_loop(
                message=message,
                document_id=document_id,
                owner_user_id=owner_user_id,
                session_id=session_context.session_id,
                max_edit_cycles=DEFAULT_MAX_EDIT_CYCLES,
            )
            tool_results.append(
                {
                    "tool": WORD_EDIT_RESULT_TOOL,
                    "args": {"document_id": document_id},
                    "result": edit_result,
                }
            )
        elif plan["mode"] == "clause_extract":
            if file_path:
                clause_result = run_clause_extraction_loop(
                    message=message,
                    file_path=file_path,
                    owner_user_id=owner_user_id,
                    session_id=session_context.session_id,
                )
            elif session_context.clause_extraction_run_id:
                clause_result = get_clause_extraction_result(
                    extraction_run_id=session_context.clause_extraction_run_id,
                    owner_user_id=owner_user_id,
                )
            else:
                raise ValueError("请先附加需要自动提取强条的 PDF")
            clause_extraction_run_id = int(clause_result["extraction_run_id"])
            tool_results = [
                {
                    "tool": CLAUSE_EXTRACTION_RESULT_TOOL,
                    "args": {"extraction_run_id": clause_extraction_run_id},
                    "result": clause_result,
                }
            ]
        else:
            tool_results = execute_tools(
                plan,
                publish_date=publish_date,
                owner_user_id=owner_user_id,
            )

        answer = final_answer(message, tool_results, conversation_context=session_context.conversation)
        issue_count = count_issues(tool_results)
        finish_check_run(run_id, "success", run_type, plan, tool_results, answer, "", started_at, issue_count)
        final_document_id = infer_document_id(tool_results) or document_id
        append_turn(
            owner_user_id=owner_user_id,
            session_id=session_context.session_id,
            user_message=message,
            assistant_message=answer,
            run_id=run_id,
            run_type=run_type,
            document_id=final_document_id,
            clause_extraction_run_id=clause_extraction_run_id,
        )
        return {
            "session_id": session_context.session_id,
            "run_id": run_id,
            "tool_plan": plan,
            "tool_results": tool_results,
            "answer": answer,
        }
    except Exception as exc:
        finish_check_run(run_id, "failed", run_type, plan, [], "", str(exc), started_at, 0)
        try:
            append_turn(
                owner_user_id=owner_user_id,
                session_id=session_context.session_id,
                user_message=message,
                assistant_message=f"请求未完成：{exc}",
                run_id=run_id,
                run_type=run_type,
                document_id=document_id,
                clause_extraction_run_id=session_context.clause_extraction_run_id,
            )
        except Exception:
            pass
        raise


def create_check_run(
    owner_user_id: int,
    session_id: int,
    document_id: int | None,
    message: str,
    started_at: datetime,
    run_type: str,
) -> int:
    with SessionLocal() as session:
        check_run = CheckRun(
            owner_user_id=owner_user_id,
            session_id=session_id,
            document_id=document_id,
            run_type=run_type,
            user_message=message,
            started_at=started_at,
            status="running",
        )
        session.add(check_run)
        session.commit()
        session.refresh(check_run)
        return check_run.id


def finish_check_run(
    run_id: int,
    status: str,
    run_type: str,
    plan: dict[str, object],
    tool_results: list[dict[str, object]],
    answer: str,
    error_message: str,
    started_at: datetime,
    issue_count: int,
) -> None:
    finished_at = datetime.now(timezone.utc)
    with SessionLocal() as session:
        check_run = session.get(CheckRun, run_id)
        if not check_run:
            return
        check_run.run_type = run_type
        check_run.tool_plan = json_safe(plan)
        check_run.tool_results = json_safe(tool_results)
        check_run.answer = answer
        check_run.status = status
        check_run.error_message = error_message
        check_run.document_id = infer_document_id(tool_results) or check_run.document_id
        check_run.finished_at = finished_at
        check_run.duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        check_run.issue_count = issue_count
        session.commit()


def run_type_for_plan(plan: dict[str, object]) -> str:
    mode = str(plan.get("mode") or "")
    if mode in ("word_edit", "clause_extract"):
        return mode
    tools = {str(step.get("tool") or "") for step in list(plan.get("steps") or [])}
    if "knowledge_query_tool" in tools:
        return "knowledge"
    if tools & {"parse_word_tool", "word_check_tool", "completeness_check_tool", "get_issues_tool"}:
        return "word_check"
    return "general"


def count_issues(tool_results: list[dict[str, object]]) -> int:
    for item in reversed(tool_results):
        if item["tool"] in (WORD_EDIT_RESULT_TOOL, "fix_consistency_issues_tool"):
            return int(item["result"].get("remaining_issue_count", 0))
        if item["tool"] == "word_check_tool":
            return int(item["result"].get("issue_count", 0))
    return sum(
        int(item["result"].get("issue_count", 0))
        for item in tool_results
        if item["tool"] == "get_issues_tool"
    )


def infer_document_id(tool_results: list[dict[str, object]]) -> int | None:
    for item in reversed(tool_results):
        result = dict(item.get("result") or {})
        document_id = result.get("output_document_id") or result.get("document_id")
        if document_id:
            return int(document_id)
    return None


def auto_fixable_issue_ids(latest_observation: dict[str, object]) -> set[int]:
    observation = dict(latest_observation.get("result") or {})
    issues = list(observation.get("issues") or observation.get("remaining_issues") or [])
    return {
        int(issue["issue_id"])
        for issue in issues
        if issue.get("auto_fixable") and issue.get("issue_id") is not None
    }


def compact_word_edit_state(state: dict[str, object]) -> dict[str, object]:
    changes = []
    for item in list(state.get("changes") or []):
        changes.append(
            {
                "change_id": item.get("change_id"),
                "cycle": item.get("cycle"),
                "input_document_id": item.get("input_document_id"),
                "output_document_id": item.get("output_document_id"),
                "issue_id": item.get("issue_id"),
                "target": item.get("target"),
                "before": item.get("before"),
                "after": item.get("after"),
                "status": item.get("status"),
                "verification_status": item.get("verification_status"),
                "error": item.get("error"),
            }
        )
    return {
        "edit_run_id": state.get("edit_run_id"),
        "status": state.get("status"),
        "source_document_id": state.get("source_document_id"),
        "document_id": state.get("document_id"),
        "output_document_id": state.get("output_document_id"),
        "verification_run_id": state.get("verification_run_id"),
        "cycle": state.get("cycle"),
        "pending_count": state.get("pending_count"),
        "applied_count": state.get("applied_count"),
        "failed_count": state.get("failed_count"),
        "changes": changes,
        "error_message": state.get("error_message"),
    }


def compact_word_edit_observation(tool_name: str, value: dict[str, object]) -> dict[str, object]:
    if tool_name == "inspect_consistency_issues_tool":
        return {
            "edit_run_id": value.get("edit_run_id"),
            "document_id": value.get("document_id"),
            "issue_count": value.get("issue_count"),
            "auto_fixable_issue_count": value.get("auto_fixable_issue_count"),
            "issues": compact_issues_for_llm(list(value.get("issues") or [])),
        }
    if tool_name == "prepare_word_edit_tool":
        return {
            "edit_run_id": value.get("edit_run_id"),
            "document_id": value.get("document_id"),
            "cycle": value.get("cycle"),
            "selected_issue_ids": value.get("selected_issue_ids"),
            "planned_count": value.get("planned_count"),
            "status": value.get("status"),
            "changes": compact_changes(list(value.get("changes") or [])),
        }
    if tool_name == "apply_word_edit_tool":
        return {
            key: value.get(key)
            for key in (
                "edit_run_id",
                "status",
                "source_document_id",
                "document_id",
                "output_document_id",
                "output_file_name",
                "cycle",
                "planned_count",
                "applied_count",
                "failed_count",
                "error_message",
            )
        }
    if tool_name == "verify_word_edit_tool":
        return {
            "edit_run_id": value.get("edit_run_id"),
            "document_id": value.get("document_id"),
            "output_document_id": value.get("output_document_id"),
            "verification_run_id": value.get("verification_run_id"),
            "remaining_issue_count": value.get("remaining_issue_count"),
            "auto_fixable_issue_count": value.get("auto_fixable_issue_count"),
            "remaining_issues": compact_issues_for_llm(list(value.get("remaining_issues") or [])),
        }
    return json_safe(value)


def compact_issues_for_llm(issues: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "issue_id": issue.get("issue_id"),
            "issue_type": issue.get("issue_type"),
            "severity": issue.get("severity"),
            "check_scope": issue.get("check_scope"),
            "section_title": issue.get("section_title"),
            "auto_fixable": issue.get("auto_fixable"),
            "proposed_replacements": issue.get("proposed_replacements"),
        }
        for issue in issues
    ]


def compact_changes(changes: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "change_id": item.get("change_id"),
            "cycle": item.get("cycle"),
            "issue_id": item.get("issue_id"),
            "target": item.get("target"),
            "before": item.get("before"),
            "after": item.get("after"),
            "status": item.get("status"),
        }
        for item in changes
    ]


def phase_for_decision(decision: dict[str, object]) -> str:
    if decision.get("action") in ("finish", "manual_review"):
        return "判断继续或结束"
    tool_name = str(decision.get("tool") or "")
    return {
        "inspect_consistency_issues_tool": "理解用户意图并选择检查",
        "prepare_word_edit_tool": "根据观察生成修订计划",
        "apply_word_edit_tool": "选择执行 Word 修改",
        "verify_word_edit_tool": "选择重新解析和复检",
    }.get(tool_name, "选择下一动作")


def phase_for_tool(tool_name: str) -> str:
    return {
        "inspect_consistency_issues_tool": "读取结构化问题",
        "prepare_word_edit_tool": "持久化结构化修改指令",
        "apply_word_edit_tool": "执行 Word 修改",
        "verify_word_edit_tool": "重新解析并复检",
    }.get(tool_name, "执行工具")


def summarize_word_edit_tool(tool_name: str, value: dict[str, object]) -> str:
    if tool_name == "inspect_consistency_issues_tool":
        return f"发现 {value.get('issue_count', 0)} 个一致性问题，其中 {value.get('auto_fixable_issue_count', 0)} 个可精确修改。"
    if tool_name == "prepare_word_edit_tool":
        return f"已向 changes 追加 {value.get('planned_count', 0)} 条可信修改指令。"
    if tool_name == "apply_word_edit_tool":
        return f"已写入 {value.get('applied_count', 0)} 处，失败 {value.get('failed_count', 0)} 处。"
    if tool_name == "verify_word_edit_tool":
        return f"复检后剩余 {value.get('remaining_issue_count', 0)} 个一致性问题。"
    return "工具执行完成。"


def compact_clause_extraction_state(state: dict[str, object]) -> dict[str, object]:
    return {
        key: state.get(key)
        for key in (
            "extraction_run_id",
            "status",
            "file_name",
            "mandatory_status",
            "detection_methods",
            "page_count",
            "clause_count",
            "listed_clause_count",
            "missing_clause_count",
            "requires_review",
            "error_message",
            "reused",
        )
    }


def compact_clause_extraction_observation(
    tool_name: str, value: dict[str, object]
) -> dict[str, object]:
    fields = {
        "inspect_clause_pdf_tool": (
            "extraction_run_id",
            "file_name",
            "page_count",
            "detection_methods",
            "listed_clause_count",
            "bold_candidate_count",
            "parse_quality",
            "status",
        ),
        "extract_clause_candidates_tool": (
            "extraction_run_id",
            "file_name",
            "clause_count",
            "missing_clause_nos",
            "status",
        ),
        "verify_clause_candidates_tool": (
            "extraction_run_id",
            "file_name",
            "clause_count",
            "missing_clause_nos",
            "mandatory_status",
            "requires_review",
            "warnings",
            "status",
        ),
    }
    return {key: value.get(key) for key in fields.get(tool_name, tuple(value.keys()))}


def phase_for_clause_decision(decision: dict[str, object]) -> str:
    if decision.get("action") in ("finish", "manual_review"):
        return "判断完成或转人工"
    return {
        "inspect_clause_pdf_tool": "选择检查 PDF 证据",
        "extract_clause_candidates_tool": "选择抽取强条候选",
        "verify_clause_candidates_tool": "选择验证抽取结果",
    }.get(str(decision.get("tool") or ""), "选择下一动作")


def phase_for_clause_tool(tool_name: str) -> str:
    return {
        "inspect_clause_pdf_tool": "自动识别 PDF 类型和证据",
        "extract_clause_candidates_tool": "按条号和粗体回查正文",
        "verify_clause_candidates_tool": "核对缺失条号和证据冲突",
    }.get(tool_name, "执行强条抽取工具")


def summarize_clause_extraction_tool(
    tool_name: str, value: dict[str, object]
) -> str:
    if tool_name == "inspect_clause_pdf_tool":
        methods = "、".join(str(item) for item in value.get("detection_methods") or [])
        return f"已解析 {value.get('page_count', 0)} 页，自动识别方法：{methods or '未发现明确证据'}。"
    if tool_name == "extract_clause_candidates_tool":
        return f"已提取 {value.get('clause_count', 0)} 条候选，缺失 {len(value.get('missing_clause_nos') or [])} 个公告条号。"
    if tool_name == "verify_clause_candidates_tool":
        return f"验证完成，状态为 {value.get('mandatory_status', 'unknown')}，共 {value.get('clause_count', 0)} 条。"
    return "强条抽取工具执行完成。"


def clamp_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value) if value is not None else default
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def parse_json(text: str) -> dict[str, object]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM 没有返回 JSON 对象")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("LLM 返回结果不是 JSON 对象")
    return value
