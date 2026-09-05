import pytest

from app.agent.contracts import AgentAction
from app.agent.environments import allowed_word_edit_actions
from app.agent.harness import validate_allowed


def state(status: str, *, cycle: int, document_id: int, pending: int = 0) -> dict:
    return {
        "status": status,
        "document_id": document_id,
        "output_document_id": document_id if document_id != 1 else None,
        "cycle": cycle,
        "pending_count": pending,
        "failed_count": 0,
    }


def test_pending_and_unverified_states_cannot_end_early():
    ready = allowed_word_edit_actions(
        state=state("ready", cycle=1, document_id=1, pending=1),
        latest_observation={"tool": "prepare_word_edit_tool", "result": {"planned_count": 1}},
        max_edit_cycles=3,
    )
    applied = allowed_word_edit_actions(
        state=state("applied", cycle=1, document_id=2),
        latest_observation={"tool": "apply_word_edit_tool", "result": {"applied_count": 1}},
        max_edit_cycles=3,
    )

    assert ready == [{"action": "call_tool", "tool": "apply_word_edit_tool"}]
    assert applied == [{"action": "call_tool", "tool": "verify_word_edit_tool"}]


def test_failed_change_prevents_finish_after_verification():
    failed_state = state("awaiting_decision", cycle=1, document_id=2)
    failed_state["failed_count"] = 1
    options = allowed_word_edit_actions(
        state=failed_state,
        latest_observation={
            "tool": "verify_word_edit_tool",
            "result": {"remaining_issue_count": 0, "auto_fixable_issue_count": 0},
        },
        max_edit_cycles=3,
    )

    assert {"action": "finish"} not in options
    assert {"action": "manual_review"} in options


def test_disallowed_action_fails_closed():
    action = AgentAction(action="call_tool", tool="apply_word_edit_tool")
    with pytest.raises(ValueError, match="不允许动作"):
        validate_allowed(
            action,
            [{"action": "call_tool", "tool": "inspect_consistency_issues_tool"}],
        )
