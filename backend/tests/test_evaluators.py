from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from app.agent.environments import (
    DocumentCheckEnvironment,
    WordEditEnvironment,
)
from app.agent.evaluators import evaluate_environment
from app.db.models import CheckIssue, CheckRun, WordDocument, WordEditRun


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_conditions):
        return self

    def all(self):
        return self.rows


class FakeDatabase:
    def __init__(self, values, issues=None):
        self.values = values
        self.issues = issues or []

    def get(self, model, row_id):
        return self.values.get((model, row_id))

    def query(self, model):
        assert model is CheckIssue
        return FakeQuery(self.issues)


def issue_row(issue_id: int, scope: str, paragraph_index: int):
    return SimpleNamespace(
        id=issue_id,
        check_scope=scope,
        issue_type=f"type_{issue_id}",
        severity="warning",
        word_reference_id=issue_id,
        matched_clause_id=None,
        matched_standard_record_id=None,
        section_title="测试章节",
        paragraph_index=paragraph_index,
        standard_no="",
        standard_name="",
        clause_no="",
        original_text=f"原文 {issue_id}",
        reason=f"原因 {issue_id}",
        suggestion="建议",
        fix_data={},
    )


def issue_result(row):
    return {
        "issue_id": row.id,
        "check_scope": row.check_scope,
        "issue_type": row.issue_type,
        "severity": row.severity,
        "word_reference_id": row.word_reference_id,
        "matched_clause_id": None,
        "matched_standard_record_id": None,
        "section_title": row.section_title,
        "paragraph_index": row.paragraph_index,
        "standard_no": "",
        "standard_name": "",
        "clause_no": "",
        "original_text": row.original_text,
        "reason": row.reason,
        "suggestion": row.suggestion,
        "fix_data": {},
    }


def tool_result(
    tool: str, document_id: int, issues: list, issue_count: int | None = None
):
    items = [issue_result(row) for row in issues]
    count = len(items) if issue_count is None else issue_count
    common = {
        "document_id": document_id,
        "check_scope": "all" if tool == "word_check_tool" else "completeness",
        "issue_count": count,
        "returned_issue_count": len(items),
        "issues": items,
    }
    if tool == "word_check_tool":
        common.update(
            {
                "reference_count": 10,
                "basis_reference_count": 4,
                "body_reference_count": 6,
                "grouped_issues": {"test": items},
            }
        )
    else:
        common.update(
            {
                "template_id": 1,
                "template_file_name": "template.docx",
                "template_year": 2026,
                "template_type": "700m",
                "template_type_label": "700M",
                "template_heading_count": 20,
                "document_section_count": 19,
                "key_section_results": [],
            }
        )
    return {"tool": tool, "args": {"document_id": document_id}, "result": common}


def test_document_check_evaluator_requires_all_selected_checks():
    env = DocumentCheckEnvironment(
        task_id=1,
        episode_id=2,
        owner_user_id=7,
        session_id=9,
        message="全面检查",
        document_id=3,
        publish_date=None,
        checks=["consistency", "completeness"],
    )
    env.tool_results = [
        {"tool": "word_check_tool", "result": {"document_id": 3, "issue_count": 0}}
    ]

    result = evaluate_environment(
        env, final_action="finish", runner_error="", reached_max_steps=False
    )

    assert result.status == "retryable_failure"
    assert result.failed_checks == ["missing:completeness_check_tool"]


def test_document_check_actions_do_not_repeat_completed_tools():
    env = DocumentCheckEnvironment(
        task_id=1,
        episode_id=2,
        owner_user_id=7,
        session_id=9,
        message="全面检查",
        document_id=3,
        publish_date=None,
        checks=["consistency", "completeness"],
    )

    initial_tools = {item.get("tool") for item in env.allowed_actions()}
    assert initial_tools == {"word_check_tool", "completeness_check_tool", None}

    env.tool_results = [
        {"tool": "word_check_tool", "result": {}},
        {"tool": "completeness_check_tool", "result": {}},
        {"tool": "get_issues_tool", "result": {}},
    ]
    assert env.allowed_actions() == [
        {"action": "finish"},
        {"action": "manual_review"},
    ]


def test_document_check_evaluator_accepts_database_consistent_result():
    env = DocumentCheckEnvironment(
        task_id=1,
        episode_id=2,
        owner_user_id=7,
        session_id=9,
        message="全面检查",
        document_id=3,
        publish_date=None,
        checks=["consistency", "completeness"],
    )
    env.check_run_id = 10
    issues = [
        issue_row(1, "basis_excel", 1),
        issue_row(2, "completeness", 2),
        issue_row(3, "completeness", 3),
    ]
    env.tool_results = [
        tool_result("word_check_tool", 3, issues[:1]),
        tool_result("completeness_check_tool", 3, issues[1:]),
    ]
    database = FakeDatabase(
        {
            (WordDocument, 3): SimpleNamespace(owner_user_id=7, parse_status="parsed"),
            (CheckRun, 10): SimpleNamespace(
                owner_user_id=7,
                document_id=3,
                task_id=1,
                episode_id=2,
            ),
        },
        issues,
    )
    with patch("app.agent.evaluators.SessionLocal", return_value=nullcontext(database)):
        result = evaluate_environment(
            env, final_action="finish", runner_error="", reached_max_steps=False
        )

    assert result.status == "success"
    assert result.evidence["issue_count"] == 3


def test_document_check_evaluator_retries_when_tool_count_differs_from_database():
    env = DocumentCheckEnvironment(
        task_id=1,
        episode_id=2,
        owner_user_id=7,
        session_id=9,
        message="检查一致性",
        document_id=3,
        publish_date=None,
        checks=["consistency"],
    )
    env.check_run_id = 10
    issues = [issue_row(1, "basis_excel", 1)]
    env.tool_results = [tool_result("word_check_tool", 3, issues, issue_count=2)]
    database = FakeDatabase(
        {
            (WordDocument, 3): SimpleNamespace(owner_user_id=7, parse_status="parsed"),
            (CheckRun, 10): SimpleNamespace(
                owner_user_id=7, document_id=3, task_id=1, episode_id=2
            ),
        },
        issues,
    )
    with patch("app.agent.evaluators.SessionLocal", return_value=nullcontext(database)):
        result = evaluate_environment(
            env, final_action="finish", runner_error="", reached_max_steps=False
        )

    assert result.status == "retryable_failure"
    assert "database_issue_count:word_check_tool" in result.failed_checks


def test_document_check_evaluator_records_but_accepts_truncated_details():
    env = DocumentCheckEnvironment(
        task_id=1,
        episode_id=2,
        owner_user_id=7,
        session_id=9,
        message="检查一致性",
        document_id=3,
        publish_date=None,
        checks=["consistency"],
    )
    env.check_run_id = 10
    issues = [issue_row(1, "basis_excel", 1), issue_row(2, "body_basis", 2)]
    env.tool_results = [tool_result("word_check_tool", 3, issues[:1], issue_count=2)]
    database = FakeDatabase(
        {
            (WordDocument, 3): SimpleNamespace(owner_user_id=7, parse_status="parsed"),
            (CheckRun, 10): SimpleNamespace(
                owner_user_id=7, document_id=3, task_id=1, episode_id=2
            ),
        },
        issues,
    )
    with patch("app.agent.evaluators.SessionLocal", return_value=nullcontext(database)):
        result = evaluate_environment(
            env, final_action="finish", runner_error="", reached_max_steps=False
        )

    assert result.status == "success"
    assert result.evidence["truncated_tools"] == ["word_check_tool"]


def test_word_edit_evaluator_checks_output_file_and_verification(tmp_path):
    output = tmp_path / "fixed.docx"
    output.write_bytes(b"docx")
    env = WordEditEnvironment(
        task_id=1,
        episode_id=2,
        owner_user_id=7,
        session_id=9,
        message="修改",
        document_id=3,
    )
    env.edit_run_id = 10
    change = {
        "change_id": "10:1:test",
        "cycle": 1,
        "input_document_id": 3,
        "output_document_id": 4,
        "verification_run_id": 20,
        "issue_id": 30,
        "issue_type": "standard_no_mismatch",
        "severity": "warning",
        "locator": {"container": "body_paragraph", "paragraph_index": 1},
        "span": {"start": 0, "end": 3, "text": "旧值"},
        "before": "旧值",
        "after": "新值",
        "status": "applied",
        "verification_status": "checked",
    }
    run = SimpleNamespace(
        id=10,
        owner_user_id=7,
        status="completed",
        changes=[change],
        output_document_id=4,
        source_document_id=3,
        verification_run_id=20,
    )
    document = SimpleNamespace(
        owner_user_id=7, parse_status="parsed", file_path=str(output)
    )
    verification = SimpleNamespace(
        status="completed",
        owner_user_id=7,
        document_id=4,
        task_id=1,
        episode_id=2,
        issue_count=0,
    )

    def get(model, _row_id):
        if model is WordEditRun:
            return run
        if model is WordDocument:
            return document
        if model is CheckRun:
            return verification
        return None

    with (
        patch(
            "app.agent.evaluators.SessionLocal",
            return_value=nullcontext(FakeDatabase({})),
        ) as session_local,
        patch(
            "app.agent.evaluators.validate_edit_diffs",
            return_value=([{"ok": True}], []),
        ),
        patch("app.agent.evaluators.validate_edit_issues", return_value=([], [], "")),
    ):
        session_local.return_value = nullcontext(SimpleNamespace(get=get))
        env.final_output = {"planned_count": 1, "applied_count": 1}
        result = evaluate_environment(
            env, final_action="finish", runner_error="", reached_max_steps=False
        )

    assert result.status == "success"


def test_word_edit_evaluator_retries_incomplete_change(tmp_path):
    output = tmp_path / "fixed.docx"
    output.write_bytes(b"docx")
    env = WordEditEnvironment(
        task_id=1,
        episode_id=2,
        owner_user_id=7,
        session_id=9,
        message="修改",
        document_id=3,
    )
    env.edit_run_id = 10
    run = SimpleNamespace(
        id=10,
        owner_user_id=7,
        status="completed",
        changes=[{"status": "pending"}],
        output_document_id=4,
        source_document_id=3,
        verification_run_id=20,
    )
    database = SimpleNamespace(
        get=lambda model, _row_id: run if model is WordEditRun else None
    )
    with patch("app.agent.evaluators.SessionLocal", return_value=nullcontext(database)):
        result = evaluate_environment(
            env, final_action="finish", runner_error="", reached_max_steps=False
        )

    assert result.status == "retryable_failure"
    assert result.failed_checks == ["change_fields:0"]
