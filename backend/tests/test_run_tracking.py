from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.agent.workflow import route_task
from app.services.session_memory import append_turn


def test_two_business_types_are_routed_deterministically():
    assert route_task(message="修改这个文档", requested_mode="")[0] == "word_edit"
    assert route_task(message="全面检查文档", requested_mode="")[0] == "document_check"


def test_removed_clause_extraction_is_rejected():
    try:
        route_task(message="抽取强条", requested_mode="clause_extract")
    except ValueError as exc:
        assert "强条抽取已移除" in str(exc)
        return
    raise AssertionError("强条抽取请求应被拒绝")


@patch("app.services.session_memory.summarize_if_needed")
@patch("app.services.session_memory.SessionLocal")
def test_only_word_check_updates_last_word_check_run(session_local, summarize):
    agent_session = SimpleNamespace(
        messages=[],
        active_document_id=8,
        last_run_id=0,
        last_word_check_run_id=5,
        last_task_id=None,
        last_episode_id=None,
    )
    database = MagicMock()
    database.query.return_value.filter.return_value.first.return_value = agent_session
    session_local.return_value.__enter__.return_value = database

    append_turn(3, 9, "修改文档", "回答", 10, "word_edit", 8)
    assert agent_session.last_run_id == 10
    assert agent_session.last_word_check_run_id == 5

    append_turn(3, 9, "检查 Word", "发现问题", 11, "word_check", 8)
    assert agent_session.last_run_id == 11
    assert agent_session.last_word_check_run_id == 11
    assert summarize.call_count == 2
