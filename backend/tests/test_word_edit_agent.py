import json
import unittest
from unittest.mock import call, patch

from app.agent.workflow import allowed_word_edit_actions, infer_document_id, run_word_edit_loop


def issue(issue_id: int) -> dict[str, object]:
    return {
        "issue_id": issue_id,
        "issue_type": "body_standard_no_mismatch",
        "severity": "warning",
        "check_scope": "body_basis",
        "section_title": "设计说明 / 设备安装",
        "auto_fixable": True,
        "proposed_replacements": [
            {"target": "standard_no", "before": "YD 5003-2014", "after": "YD/T 5003-2025"}
        ],
    }


def state(status: str, *, cycle: int, document_id: int, pending: int = 0) -> dict[str, object]:
    return {
        "edit_run_id": 10,
        "status": status,
        "source_document_id": 1,
        "document_id": document_id,
        "output_document_id": document_id if document_id != 1 else None,
        "verification_run_id": None,
        "cycle": cycle,
        "pending_count": pending,
        "applied_count": cycle,
        "failed_count": 0,
        "changes": [],
        "decision_trace": [],
        "error_message": "",
    }


class WordEditAgentLoopTest(unittest.TestCase):
    @patch("app.agent.workflow.fail_word_edit_run")
    @patch("app.agent.workflow.finalize_word_edit_run")
    @patch("app.agent.workflow.append_word_edit_trace")
    @patch("app.agent.workflow.run_tool")
    @patch("app.agent.workflow.get_word_edit_state")
    @patch("app.agent.workflow.start_word_edit_run")
    @patch("app.agent.workflow.call_llm")
    def test_agent_replans_with_one_durable_edit_run(
        self,
        call_llm,
        start_run,
        get_state,
        run_tool,
        append_trace,
        finalize,
        fail_run,
    ):
        call_llm.side_effect = [
            json.dumps({"action": "call_tool", "tool": "inspect_consistency_issues_tool", "args": {}, "reason": "先检查"}),
            json.dumps({"action": "call_tool", "tool": "prepare_word_edit_tool", "args": {"selected_issue_ids": [1]}, "reason": "规划第一轮"}),
            json.dumps({"action": "call_tool", "tool": "apply_word_edit_tool", "args": {}, "reason": "执行第一轮"}),
            json.dumps({"action": "call_tool", "tool": "verify_word_edit_tool", "args": {}, "reason": "复检第一轮"}),
            json.dumps({"action": "call_tool", "tool": "prepare_word_edit_tool", "args": {"selected_issue_ids": [2]}, "reason": "规划第二轮"}),
            json.dumps({"action": "call_tool", "tool": "apply_word_edit_tool", "args": {}, "reason": "执行第二轮"}),
            json.dumps({"action": "call_tool", "tool": "verify_word_edit_tool", "args": {}, "reason": "复检第二轮"}),
            json.dumps({"action": "finish", "tool": "", "args": {}, "reason": "复检通过"}),
        ]
        start_run.return_value = state("planning", cycle=0, document_id=1)
        get_state.side_effect = [
            state("planning", cycle=0, document_id=1),
            state("awaiting_plan", cycle=0, document_id=1),
            state("ready", cycle=1, document_id=1, pending=1),
            state("applied", cycle=1, document_id=2),
            state("awaiting_decision", cycle=1, document_id=2),
            state("ready", cycle=2, document_id=2, pending=1),
            state("applied", cycle=2, document_id=3),
            state("awaiting_decision", cycle=2, document_id=3),
        ]

        tool_results = {
            "inspect_consistency_issues_tool": {
                "edit_run_id": 10,
                "document_id": 1,
                "issue_count": 1,
                "auto_fixable_issue_count": 1,
                "issues": [issue(1)],
            },
            "prepare_word_edit_tool": [
                {"edit_run_id": 10, "document_id": 1, "cycle": 1, "selected_issue_ids": [1], "planned_count": 1, "changes": [], "status": "ready"},
                {"edit_run_id": 10, "document_id": 2, "cycle": 2, "selected_issue_ids": [2], "planned_count": 1, "changes": [], "status": "ready"},
            ],
            "apply_word_edit_tool": [
                {"edit_run_id": 10, "status": "applied", "source_document_id": 1, "document_id": 2, "output_document_id": 2, "output_file_name": "测试-已修订.docx", "cycle": 1, "planned_count": 1, "applied_count": 1, "failed_count": 0, "error_message": ""},
                {"edit_run_id": 10, "status": "applied", "source_document_id": 1, "document_id": 3, "output_document_id": 3, "output_file_name": "测试-二次修订.docx", "cycle": 2, "planned_count": 1, "applied_count": 1, "failed_count": 0, "error_message": ""},
            ],
            "verify_word_edit_tool": [
                {"edit_run_id": 10, "document_id": 2, "output_document_id": 2, "verification_run_id": 20, "remaining_issue_count": 1, "auto_fixable_issue_count": 1, "remaining_issues": [issue(2)]},
                {"edit_run_id": 10, "document_id": 3, "output_document_id": 3, "verification_run_id": 21, "remaining_issue_count": 0, "auto_fixable_issue_count": 0, "remaining_issues": []},
            ],
        }
        counters = {"prepare_word_edit_tool": 0, "apply_word_edit_tool": 0, "verify_word_edit_tool": 0}

        def dispatch(name, args):
            value = tool_results[name]
            if isinstance(value, list):
                index = counters[name]
                counters[name] += 1
                return value[index]
            return value

        run_tool.side_effect = dispatch
        finalize.return_value = {"status": "completed", "edit_run_id": 10, "output_document_id": 3}

        result = run_word_edit_loop(
            message="帮我修改",
            document_id=1,
            owner_user_id=7,
            session_id=9,
            max_edit_cycles=3,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["edit_run_id"], 10)
        start_run.assert_called_once_with(document_id=1, owner_user_id=7, session_id=9)
        self.assertEqual([item.args[0] for item in run_tool.call_args_list], [
            "inspect_consistency_issues_tool",
            "prepare_word_edit_tool",
            "apply_word_edit_tool",
            "verify_word_edit_tool",
            "prepare_word_edit_tool",
            "apply_word_edit_tool",
            "verify_word_edit_tool",
        ])
        prepare_calls = [item for item in run_tool.call_args_list if item.args[0] == "prepare_word_edit_tool"]
        self.assertEqual(prepare_calls[0].args[1]["expected_document_id"], 1)
        self.assertEqual(prepare_calls[1].args[1]["expected_document_id"], 2)
        self.assertTrue(all(item.args[1]["edit_run_id"] == 10 for item in run_tool.call_args_list))
        finalize.assert_called_once_with(
            edit_run_id=10,
            owner_user_id=7,
            remaining_issues=[],
            action="finish",
            reason="复检通过",
        )
        self.assertGreater(append_trace.call_count, run_tool.call_count)
        fail_run.assert_not_called()

    @patch("app.agent.workflow.fail_word_edit_run")
    @patch("app.agent.workflow.get_word_edit_state")
    @patch("app.agent.workflow.start_word_edit_run")
    @patch("app.agent.workflow.call_llm")
    def test_disallowed_llm_action_fails_closed(self, call_llm, start_run, get_state, fail_run):
        start_run.return_value = state("planning", cycle=0, document_id=1)
        get_state.return_value = state("planning", cycle=0, document_id=1)
        call_llm.return_value = json.dumps(
            {"action": "call_tool", "tool": "apply_word_edit_tool", "args": {}, "reason": "越过检查"}
        )

        with self.assertRaisesRegex(ValueError, "不允许的动作"):
            run_word_edit_loop(message="修改", document_id=1, owner_user_id=7)

        fail_run.assert_called_once()

    def test_infer_document_id_prefers_terminal_output(self):
        results = [
            {"tool": "parse_word_tool", "result": {"document_id": 1}},
            {"tool": "word_edit_result", "result": {"document_id": 3, "output_document_id": 3}},
        ]
        self.assertEqual(infer_document_id(results), 3)

    def test_pending_and_unverified_states_cannot_end_early(self):
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

        self.assertEqual(ready, [{"action": "call_tool", "tool": "apply_word_edit_tool"}])
        self.assertEqual(applied, [{"action": "call_tool", "tool": "verify_word_edit_tool"}])

    def test_failed_change_prevents_finish_after_verification(self):
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

        self.assertNotIn({"action": "finish"}, options)
        self.assertIn({"action": "manual_review"}, options)


if __name__ == "__main__":
    unittest.main()
