from unittest.mock import call, patch

from app.agent.contracts import AgentAction, EvaluationResult, ReflectionResult
from app.agent.environments import AgentEnvironment
from app.agent.harness import run_agent


class DummyEnvironment(AgentEnvironment):
    task_type = "document_check"
    max_steps = 1

    def start(self):
        pass

    def state(self):
        return {"ready": True}

    def allowed_actions(self):
        return [{"action": "finish"}]

    def trusted_args(self, _action: AgentAction):
        return {}

    def finish(self, _action: AgentAction):
        self.final_output = {"done": True}
        return self.final_output

    def prompt(self):
        return "测试环境"


def make_environment(episode_id: int):
    return DummyEnvironment(task_id=1, episode_id=episode_id, owner_user_id=7, session_id=9)


@patch("app.agent.harness.activate_candidate")
@patch("app.agent.harness.retire_candidate")
@patch("app.agent.harness.finish_episode")
@patch("app.agent.harness.create_candidate", return_value=88)
@patch("app.agent.harness.reflect_on_failure")
@patch("app.agent.harness.load_episode_steps", return_value=[{"step": 1}])
@patch("app.agent.harness.save_step")
@patch("app.agent.harness.create_episode", side_effect=[11, 12])
@patch("app.agent.harness.load_active_experiences", return_value=[{"id": 5, "lesson": "先检查"}])
@patch("app.agent.harness.call_llm_messages", return_value='{"action":"finish","reason_summary":"完成"}')
@patch("app.agent.harness.evaluate_environment")
def test_retry_uses_current_reflection_and_activates_candidate_after_success(
    evaluate,
    call_llm,
    load_experiences,
    create_episode,
    save_step,
    _load_steps,
    reflect,
    create_candidate,
    _finish_episode,
    retire,
    activate,
):
    evaluate.side_effect = [
        EvaluationResult(
            status="retryable_failure",
            summary="缺步骤",
            failed_checks=["missing_tool"],
            retry_strategy="补齐步骤",
        ),
        EvaluationResult(status="success", summary="通过"),
    ]
    reflection = ReflectionResult(
        failure_code="missing_tool",
        failure_summary="缺步骤",
        lesson="结束前检查必需工具",
        retry_strategy="补齐步骤",
    )
    reflect.return_value = reflection

    result = run_agent(
        task_id=1,
        owner_user_id=7,
        task_type="document_check",
        user_message="全面检查",
        conversation_context="无",
        environment_factory=make_environment,
    )

    assert result.attempt_no == 2
    assert result.evaluation.status == "success"
    load_experiences.assert_called_once_with(owner_user_id=7, task_type="document_check")
    assert create_episode.call_args_list == [
        call(task_id=1, attempt_no=1, experience_ids=[5]),
        call(task_id=1, attempt_no=2, experience_ids=[5, 88]),
    ]
    create_candidate.assert_called_once()
    activate.assert_called_once_with(88, successful_episode_id=12, success_summary="通过")
    retire.assert_not_called()
    assert call_llm.call_count == 2
    assert save_step.call_count == 2


def test_agent_action_rejects_model_controlled_args_on_finish():
    try:
        AgentAction(action="finish", args={"document_id": 99})
    except ValueError:
        return
    raise AssertionError("finish 携带资源参数时应拒绝")
