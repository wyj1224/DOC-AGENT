from datetime import date, datetime, timezone
from app.agent.contracts import AgentAction, EvaluationResult, ToolObservation
from app.agent.registry import (
    prompt_text,
    run_tool,
    word_edit_tool_prompt_text,
)
from app.db.database import SessionLocal
from app.db.models import CheckRun
from app.services.word_edit_workflow import (
    fail_word_edit_run,
    finalize_word_edit_run,
    get_word_edit_state,
    start_word_edit_run,
)


class AgentEnvironment:
    task_type = ""
    max_steps = 12

    def __init__(self, *, task_id: int, episode_id: int, owner_user_id: int, session_id: int | None):
        self.task_id = task_id
        self.episode_id = episode_id
        self.owner_user_id = owner_user_id
        self.session_id = session_id
        self.latest_observation: dict = {}
        self.final_output: dict = {}
        self.execution_error = ""
        self.last_trusted_args: dict = {}

    def start(self) -> None:
        raise NotImplementedError

    def state(self) -> dict:
        raise NotImplementedError

    def allowed_actions(self) -> list[dict]:
        raise NotImplementedError

    def trusted_args(self, action: AgentAction) -> dict:
        raise NotImplementedError

    def execute(self, action: AgentAction) -> ToolObservation:
        args = self.trusted_args(action)
        self.last_trusted_args = args
        try:
            result = run_tool(action.tool, args)
            observation = ToolObservation(ok=True, tool=action.tool, result=result)
        except Exception as exc:
            observation = ToolObservation(ok=False, tool=action.tool, error=str(exc))
            self.execution_error = str(exc)
        self.latest_observation = observation.model_dump()
        return observation

    def finish(self, action: AgentAction) -> dict:
        raise NotImplementedError

    def prompt(self) -> str:
        raise NotImplementedError

    def abort(self, error: str) -> None:
        self.execution_error = error

    def record_evaluation(self, evaluation: EvaluationResult) -> None:
        del evaluation


class DocumentCheckEnvironment(AgentEnvironment):
    task_type = "document_check"
    max_steps = 10

    def __init__(
        self,
        *,
        task_id: int,
        episode_id: int,
        owner_user_id: int,
        session_id: int | None,
        message: str,
        document_id: int,
        publish_date: date | None,
        checks: list[str],
    ):
        super().__init__(
            task_id=task_id,
            episode_id=episode_id,
            owner_user_id=owner_user_id,
            session_id=session_id,
        )
        self.message = message
        self.document_id = document_id
        self.publish_date = publish_date
        self.checks = checks or ["consistency", "completeness"]
        self.tool_results: list[dict] = []
        self.check_run_id: int | None = None

    def start(self) -> None:
        with SessionLocal() as session:
            row = CheckRun(
                owner_user_id=self.owner_user_id,
                session_id=self.session_id,
                task_id=self.task_id,
                episode_id=self.episode_id,
                document_id=self.document_id,
                run_type="word_check",
                user_message=self.message,
                tool_plan={"checks": self.checks},
                status="running",
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            self.check_run_id = row.id

    def state(self) -> dict:
        return {
            "document_id": self.document_id,
            "required_checks": self.checks,
            "completed_tools": [item["tool"] for item in self.tool_results],
            "last_observation": self.latest_observation,
        }

    def allowed_actions(self) -> list[dict]:
        completed = {item["tool"] for item in self.tool_results}
        actions = []
        if "consistency" in self.checks and "word_check_tool" not in completed:
            actions.append({"action": "call_tool", "tool": "word_check_tool"})
        if "completeness" in self.checks and "completeness_check_tool" not in completed:
            actions.append({"action": "call_tool", "tool": "completeness_check_tool"})

        required_tools = {
            "consistency": "word_check_tool",
            "completeness": "completeness_check_tool",
        }
        required_done = all(required_tools[check] in completed for check in self.checks)
        if required_done:
            if "get_issues_tool" not in completed:
                actions.append({"action": "call_tool", "tool": "get_issues_tool"})
            actions.append({"action": "finish"})
        actions.append({"action": "manual_review"})
        return actions

    def trusted_args(self, action: AgentAction) -> dict:
        if action.tool == "word_check_tool":
            return {
                "document_id": self.document_id,
                "publish_date": self.publish_date,
                "replace": True,
                "issue_limit": 50,
                "owner_user_id": self.owner_user_id,
            }
        if action.tool == "completeness_check_tool":
            return {
                "document_id": self.document_id,
                "replace": True,
                "issue_limit": 50,
                "owner_user_id": self.owner_user_id,
            }
        if action.tool == "get_issues_tool":
            scope = str(action.args.get("check_scope") or "")
            if scope not in ("", "basis_excel", "body_basis", "completeness"):
                scope = ""
            return {
                "document_id": self.document_id,
                "check_scope": scope,
                "issue_limit": 50,
                "owner_user_id": self.owner_user_id,
            }
        raise ValueError(f"文档检查不允许调用工具：{action.tool}")

    def execute(self, action: AgentAction) -> ToolObservation:
        observation = super().execute(action)
        if observation.ok:
            self.tool_results.append(
                {"tool": action.tool, "args": self.last_trusted_args, "result": observation.result}
            )
        return observation

    def finish(self, action: AgentAction) -> dict:
        self.final_output = {
            "check_run_id": self.check_run_id,
            "document_id": self.document_id,
            "checks": self.checks,
            "tool_results": self.tool_results,
            "final_action": action.action,
            "reason_summary": action.reason_summary,
        }
        return self.final_output

    def prompt(self) -> str:
        tools = prompt_text(
            ("word_check_tool", "completeness_check_tool", "get_issues_tool")
        )
        return f"""
你负责 Word 文档检查。可自由选择下一项工具，但一次只能执行一个动作。
可用工具：
{tools}
- consistency 需要 word_check_tool；completeness 需要 completeness_check_tool。
- 需要查看问题明细时调用 get_issues_tool。
- 所需检查都完成后 finish；证据冲突、文件不可信或无法安全判断时 manual_review。
- args 只填写 get_issues_tool 可选的 check_scope，其他资源参数由系统注入。
""".strip()

    def persist_business_result(self, *, status: str, answer: str, error: str = "") -> None:
        with SessionLocal() as session:
            row = session.get(CheckRun, self.check_run_id)
            if not row:
                return
            row.document_id = self.document_id
            row.tool_results = self.tool_results
            row.answer = answer
            row.status = "completed" if status == "success" else status
            row.error_message = error
            row.finished_at = datetime.now(timezone.utc)
            row.issue_count = self.issue_count()
            session.commit()

    def record_evaluation(self, evaluation: EvaluationResult) -> None:
        self.persist_business_result(
            status=evaluation.status,
            answer=evaluation.summary,
            error="" if evaluation.status == "success" else evaluation.summary,
        )

    def issue_count(self) -> int:
        values = [
            int(item["result"].get("issue_count") or 0)
            for item in self.tool_results
            if item["tool"] in ("word_check_tool", "completeness_check_tool")
        ]
        return sum(values)


class WordEditEnvironment(AgentEnvironment):
    task_type = "word_edit"
    max_steps = 16
    max_edit_cycles = 3

    def __init__(self, *, message: str, document_id: int, **kwargs):
        super().__init__(**kwargs)
        self.message = message
        self.document_id = document_id
        self.edit_run_id: int | None = None

    def start(self) -> None:
        started = start_word_edit_run(
            document_id=self.document_id,
            owner_user_id=self.owner_user_id,
            session_id=self.session_id,
            task_id=self.task_id,
            episode_id=self.episode_id,
        )
        self.edit_run_id = int(started["edit_run_id"])
        self.latest_observation = {"ok": True, "tool": "start_word_edit_run", "result": started, "error": ""}

    def state(self) -> dict:
        if self.edit_run_id is None:
            return {}
        state = get_word_edit_state(edit_run_id=self.edit_run_id, owner_user_id=self.owner_user_id)
        state.pop("changes", None)
        state["last_observation"] = compact_word_edit_observation(self.latest_observation)
        return state

    def allowed_actions(self) -> list[dict]:
        return allowed_word_edit_actions(
            state=self.state(),
            latest_observation=self.latest_observation,
            max_edit_cycles=self.max_edit_cycles,
        )

    def trusted_args(self, action: AgentAction) -> dict:
        if self.edit_run_id is None:
            raise ValueError("WordEditRun 尚未创建")
        args = {"edit_run_id": self.edit_run_id, "owner_user_id": self.owner_user_id}
        if action.tool == "prepare_word_edit_tool":
            observation = dict(self.latest_observation.get("result") or {})
            allowed_ids = {
                int(item["issue_id"])
                for item in list(observation.get("issues") or observation.get("remaining_issues") or [])
                if item.get("auto_fixable") and item.get("issue_id")
            }
            selected = []
            for value in list(action.args.get("selected_issue_ids") or []):
                try:
                    issue_id = int(value)
                except (TypeError, ValueError):
                    continue
                if issue_id in allowed_ids and issue_id not in selected:
                    selected.append(issue_id)
            if not selected:
                raise ValueError("没有选择当前观察中可自动修改的问题")
            args.update(
                {
                    "selected_issue_ids": selected,
                    "expected_document_id": int(observation.get("document_id") or self.state()["document_id"]),
                }
            )
        elif action.tool not in (
            "inspect_consistency_issues_tool",
            "apply_word_edit_tool",
            "verify_word_edit_tool",
        ):
            raise ValueError(f"文档修改不允许调用工具：{action.tool}")
        return args

    def finish(self, action: AgentAction) -> dict:
        if self.edit_run_id is None:
            raise ValueError("WordEditRun 尚未创建")
        self.final_output = finalize_word_edit_run(
            edit_run_id=self.edit_run_id,
            owner_user_id=self.owner_user_id,
            remaining_issues=[],
            action=action.action,
            reason=action.reason_summary,
        )
        return self.final_output

    def prompt(self) -> str:
        return f"""
你负责安全修改 Word。严格依据当前状态和上一条观察选择一个动作。
可用工具：
{word_edit_tool_prompt_text()}
- 先 inspect；只可把观察中 auto_fixable=true 的 issue_id 交给 prepare。
- prepare 后 apply，生成副本后必须 verify；复检无剩余问题才 finish。
- 不能生成 before/after/locator/document_id/owner_user_id，这些由确定性代码提供。
- 不可安全定位、仍有人工问题或预算不足时 manual_review。
""".strip()

    def abort(self, error: str) -> None:
        super().abort(error)
        if self.edit_run_id is not None:
            fail_word_edit_run(
                edit_run_id=self.edit_run_id,
                owner_user_id=self.owner_user_id,
                error_message=error,
            )


def allowed_word_edit_actions(
    *, state: dict, latest_observation: dict, max_edit_cycles: int
) -> list[dict]:
    status = str(state.get("status") or "")
    observation = dict(latest_observation.get("result") or {})
    if status == "planning":
        return [
            {"action": "call_tool", "tool": "inspect_consistency_issues_tool"},
            {"action": "manual_review"},
        ]
    if status in ("awaiting_plan", "awaiting_decision"):
        options = []
        issue_key = "remaining_issue_count" if status == "awaiting_decision" else "issue_count"
        if int(observation.get(issue_key) or 0) == 0 and int(state.get("failed_count") or 0) == 0:
            options.append({"action": "finish"})
        if (
            int(observation.get("auto_fixable_issue_count") or 0) > 0
            and int(state.get("cycle") or 0) < max_edit_cycles
        ):
            options.append({"action": "call_tool", "tool": "prepare_word_edit_tool"})
        options.append({"action": "manual_review"})
        return options
    if status == "ready" and int(state.get("pending_count") or 0) > 0:
        return [{"action": "call_tool", "tool": "apply_word_edit_tool"}]
    if status == "applied" and state.get("output_document_id"):
        return [{"action": "call_tool", "tool": "verify_word_edit_tool"}]
    return [{"action": "manual_review"}]


def compact_word_edit_observation(observation: dict) -> dict:
    """Keep the durable trajectory complete while sending only decision facts to the LLM."""
    compact = {
        "ok": observation.get("ok"),
        "tool": observation.get("tool"),
        "error": observation.get("error", ""),
    }
    result = dict(observation.get("result") or {})
    keep = (
        "edit_run_id",
        "status",
        "document_id",
        "output_document_id",
        "cycle",
        "issue_count",
        "remaining_issue_count",
        "auto_fixable_issue_count",
        "planned_count",
        "applied_count",
        "failed_count",
        "verification_run_id",
        "error_message",
    )
    compact_result = {key: result[key] for key in keep if key in result}
    issue_key = "remaining_issues" if "remaining_issues" in result else "issues"
    if issue_key in result:
        compact_result[issue_key] = [
            {
                "issue_id": item.get("issue_id"),
                "issue_type": item.get("issue_type"),
                "severity": item.get("severity"),
                "auto_fixable": True,
            }
            for item in result[issue_key]
            if item.get("auto_fixable") and item.get("issue_id")
        ][:50]
    compact["result"] = compact_result
    return compact
