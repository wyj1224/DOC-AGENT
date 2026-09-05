import json
from dataclasses import dataclass
from time import perf_counter
from typing import Callable

from app.agent.contracts import AgentAction, EvaluationResult, parse_json_model
from app.agent.environments import AgentEnvironment
from app.agent.evaluators import evaluate_environment
from app.agent.experience_memory import (
    activate_candidate,
    create_candidate,
    load_active_experiences,
    retire_candidate,
)
from app.agent.reflection import reflect_on_failure
from app.agent.runtime_store import (
    create_episode,
    finish_episode,
    load_episode_steps,
    save_step,
)
from app.llm import call_llm_messages


MAX_EPISODES = 2


@dataclass
class HarnessResult:
    task_id: int
    episode_id: int
    attempt_no: int
    evaluation: EvaluationResult
    output: dict
    environment: AgentEnvironment


class ExperienceMemoryModule:
    """Small replaceable boundary around the current insight memory implementation."""

    def load(self, *, owner_user_id: int, task_type: str) -> list[dict]:
        return load_active_experiences(owner_user_id=owner_user_id, task_type=task_type)

    def create(self, **kwargs) -> int:
        return create_candidate(**kwargs)

    def activate(self, experience_id: int, **kwargs) -> None:
        activate_candidate(experience_id, **kwargs)

    def retire(self, experience_id: int) -> None:
        retire_candidate(experience_id)


def run_agent(
    *,
    task_id: int,
    owner_user_id: int,
    task_type: str,
    user_message: str,
    conversation_context: str,
    environment_factory: Callable[[int], AgentEnvironment],
    model_call: Callable[[list[dict[str, str]]], str] | None = None,
    evaluator: Callable[..., EvaluationResult] | None = None,
    memory_module: ExperienceMemoryModule | None = None,
) -> HarnessResult:
    """Run at most two episodes. Active memory is loaded only once per task."""
    model_call = model_call or call_llm_messages
    evaluator = evaluator or evaluate_environment
    memory_module = memory_module or ExperienceMemoryModule()
    active_experiences = memory_module.load(
        owner_user_id=owner_user_id,
        task_type=task_type,
    )
    candidate_id: int | None = None
    retry_reflection: dict = {}

    for attempt_no in range(1, MAX_EPISODES + 1):
        experience_ids = [int(item["id"]) for item in active_experiences]
        if candidate_id:
            experience_ids.append(candidate_id)
        episode_id = create_episode(
            task_id=task_id,
            attempt_no=attempt_no,
            experience_ids=experience_ids,
        )
        env = environment_factory(episode_id)
        final_action = ""
        runner_error = ""
        reached_max_steps = False

        try:
            env.start()
        except Exception as exc:
            runner_error = str(exc)
            save_step(
                episode_id=episode_id,
                step_index=1,
                model_input=[],
                raw_model_output="",
                action={"action": "environment_start"},
                trusted_args={},
                observation={"ok": False, "error": runner_error},
                state_before={},
                state_after={},
                status="failed",
                error_message=runner_error,
                duration_ms=0,
            )

        if not runner_error:
            for step_index in range(1, env.max_steps + 1):
                state_before = env.state()
                allowed = env.allowed_actions()
                messages = build_messages(
                    env=env,
                    user_message=user_message,
                    conversation_context=conversation_context,
                    state=state_before,
                    allowed_actions=allowed,
                    active_experiences=active_experiences,
                    retry_reflection=retry_reflection,
                    attempt_no=attempt_no,
                    step_index=step_index,
                )
                started = perf_counter()
                raw = ""
                action_data: dict = {}
                trusted_args: dict = {}
                observation: dict = {}
                step_error = ""
                try:
                    raw = model_call(messages)
                    action = parse_json_model(raw, AgentAction)
                    validate_allowed(action, allowed)
                    action_data = action.model_dump()
                    if action.action == "call_tool":
                        tool_observation = env.execute(action)
                        trusted_args = env.last_trusted_args
                        observation = tool_observation.model_dump()
                        if not tool_observation.ok:
                            step_error = tool_observation.error
                            runner_error = step_error
                    else:
                        final_action = action.action
                        env.finish(action)
                except Exception as exc:
                    step_error = str(exc)
                    runner_error = step_error
                    observation = {"ok": False, "error": step_error}

                state_after = safe_state(env)
                save_step(
                    episode_id=episode_id,
                    step_index=step_index,
                    model_input=messages,
                    raw_model_output=raw,
                    action=action_data,
                    trusted_args=trusted_args,
                    observation=observation,
                    state_before=state_before,
                    state_after=state_after,
                    status="failed" if step_error else "completed",
                    error_message=step_error,
                    duration_ms=int((perf_counter() - started) * 1000),
                )
                if final_action or runner_error:
                    break
            else:
                reached_max_steps = True

        if runner_error:
            env.abort(runner_error)
        elif reached_max_steps:
            env.abort("Agent 达到最大步数但任务尚未结束")

        evaluation = evaluator(
            env,
            final_action=final_action,
            runner_error=runner_error,
            reached_max_steps=reached_max_steps,
        )
        output = env.final_output or safe_state(env)

        if evaluation.status == "retryable_failure" and attempt_no < MAX_EPISODES:
            env.record_evaluation(evaluation)
            trajectory = load_episode_steps(episode_id)
            reflection = reflect_on_failure(
                task_type=task_type,
                evaluation=evaluation,
                trajectory=trajectory,
            )
            candidate_id = memory_module.create(
                owner_user_id=owner_user_id,
                task_type=task_type,
                episode_id=episode_id,
                reflection=reflection,
                evidence=evaluation.evidence,
            )
            finish_episode(
                episode_id=episode_id,
                evaluation=evaluation,
                final_output=output,
                reflection=reflection,
            )
            retry_reflection = reflection.model_dump()
            continue

        if evaluation.status == "retryable_failure" and attempt_no == MAX_EPISODES:
            evaluation = EvaluationResult(
                status="terminal_failure",
                summary=f"已达到 {MAX_EPISODES} 次 Episode 上限：{evaluation.summary}",
                failed_checks=evaluation.failed_checks,
                evidence={**evaluation.evidence, "retry_budget_exhausted": True},
            )

        env.record_evaluation(evaluation)
        finish_episode(
            episode_id=episode_id,
            evaluation=evaluation,
            final_output=output,
        )
        if candidate_id:
            if evaluation.status == "success":
                memory_module.activate(
                    candidate_id,
                    successful_episode_id=episode_id,
                    success_summary=evaluation.summary,
                )
            else:
                memory_module.retire(candidate_id)
        return HarnessResult(
            task_id=task_id,
            episode_id=episode_id,
            attempt_no=attempt_no,
            evaluation=evaluation,
            output=output,
            environment=env,
        )

    raise RuntimeError("Agent Harness 未产生结果")


def build_messages(
    *,
    env: AgentEnvironment,
    user_message: str,
    conversation_context: str,
    state: dict,
    allowed_actions: list[dict],
    active_experiences: list[dict],
    retry_reflection: dict,
    attempt_no: int,
    step_index: int,
) -> list[dict[str, str]]:
    system = """
你是“灵枢·规鉴”的执行 Agent。按 observe -> decide -> act -> observe 循环工作。
每次只能输出一个 JSON 对象，不要输出 Markdown，不要输出隐式思维过程。
格式：{"action":"call_tool|finish|manual_review","tool":"工具名或空字符串","args":{},"reason_summary":"简短理由"}
只能从 allowed_actions 中选择。工具的资源 ID、用户 ID 和文件路径由系统根据可信状态注入。
finish 只是申请结束；独立的确定性 Evaluator 会检查数据库、文件和工具事实。
""".strip()
    payload = {
        "user_goal": user_message,
        "conversation_context": conversation_context,
        "episode": attempt_no,
        "step": step_index,
        "state_and_last_observation": state,
        "allowed_actions": allowed_actions,
        "active_experience_insights": active_experiences,
        "current_task_retry_reflection": retry_reflection or None,
    }
    return [
        {"role": "system", "content": system},
        {"role": "system", "content": env.prompt()},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ]


def validate_allowed(action: AgentAction, allowed_actions: list[dict]) -> None:
    pair = (action.action, action.tool if action.action == "call_tool" else "")
    allowed_pairs = {
        (str(item.get("action") or ""), str(item.get("tool") or ""))
        for item in allowed_actions
    }
    if pair not in allowed_pairs:
        raise ValueError(f"当前状态不允许动作：{pair[0]}/{pair[1]}")


def safe_state(env: AgentEnvironment) -> dict:
    try:
        return env.state()
    except Exception as exc:
        return {"state_error": str(exc)}
