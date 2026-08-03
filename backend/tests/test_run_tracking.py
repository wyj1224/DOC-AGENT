from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.agent.workflow import run_type_for_plan
from app.services.session_memory import append_turn


def test_run_type_is_derived_from_the_actual_plan():
    assert run_type_for_plan({"mode": "word_edit", "steps": []}) == "word_edit"
    assert run_type_for_plan({"mode": "clause_extract", "steps": []}) == "clause_extract"
    assert run_type_for_plan(
        {"mode": "standard", "steps": [{"tool": "knowledge_query_tool"}]}
    ) == "knowledge"
    assert run_type_for_plan(
        {"mode": "standard", "steps": [{"tool": "word_check_tool"}]}
    ) == "word_check"


@patch("app.services.session_memory.summarize_if_needed")
@patch("app.services.session_memory.SessionLocal")
def test_only_word_check_updates_last_word_check_run(session_local, summarize):
    agent_session = SimpleNamespace(
        messages=[],
        active_document_id=8,
        active_clause_extraction_run_id=None,
        last_run_id=0,
        last_word_check_run_id=5,
    )
    database = MagicMock()
    database.query.return_value.filter.return_value.first.return_value = agent_session
    session_local.return_value.__enter__.return_value = database

    append_turn(3, 9, "知识问答", "回答", 10, "knowledge", 8)
    assert agent_session.last_run_id == 10
    assert agent_session.last_word_check_run_id == 5

    append_turn(3, 9, "检查 Word", "发现问题", 11, "word_check", 8)
    assert agent_session.last_run_id == 11
    assert agent_session.last_word_check_run_id == 11
    assert summarize.call_count == 2
