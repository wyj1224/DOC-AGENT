from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from app.agent.environments import (
    DocumentCheckEnvironment,
    WordEditEnvironment,
)
from app.agent.evaluators import evaluate_environment
from app.db.models import CheckRun, WordDocument, WordEditRun


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
    env.tool_results = [
        {"tool": "word_check_tool", "result": {"document_id": 3, "issue_count": 1}},
        {"tool": "completeness_check_tool", "result": {"document_id": 3, "issue_count": 2}},
    ]
    database = SimpleNamespace(
        get=lambda _model, _row_id: SimpleNamespace(owner_user_id=7, parse_status="parsed")
    )
    with patch("app.agent.evaluators.SessionLocal", return_value=nullcontext(database)):
        result = evaluate_environment(
            env, final_action="finish", runner_error="", reached_max_steps=False
        )

    assert result.status == "success"
    assert result.evidence["issue_count"] == 3


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
    run = SimpleNamespace(
        id=10,
        owner_user_id=7,
        status="completed",
        changes=[{"status": "applied"}],
        output_document_id=4,
        source_document_id=3,
        verification_run_id=20,
    )
    document = SimpleNamespace(owner_user_id=7, parse_status="parsed", file_path=str(output))
    verification = SimpleNamespace(status="completed")

    def get(model, _row_id):
        if model is WordEditRun:
            return run
        if model is WordDocument:
            return document
        if model is CheckRun:
            return verification
        return None

    with patch(
        "app.agent.evaluators.SessionLocal",
        return_value=nullcontext(SimpleNamespace(get=get)),
    ):
        result = evaluate_environment(
            env, final_action="finish", runner_error="", reached_max_steps=False
        )

    assert result.status == "success"
