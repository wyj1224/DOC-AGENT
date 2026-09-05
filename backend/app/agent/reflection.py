import json

from app.agent.contracts import EvaluationResult, ReflectionResult, parse_json_model
from app.llm import call_llm_messages


def reflect_on_failure(
    *, task_type: str, evaluation: EvaluationResult, trajectory: list[dict]
) -> ReflectionResult:
    """Distill observable failure evidence; never request hidden chain-of-thought."""
    messages = [
        {
            "role": "system",
            "content": (
                "你是失败经验总结器。只依据 action、trusted_args、observation 和确定性 Evaluator 结论，"
                "输出简短 JSON。不要推测或输出模型隐式思维链。lesson 必须是下次可执行的规则。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task_type": task_type,
                    "evaluation": evaluation.model_dump(),
                    "trajectory": trajectory,
                    "schema": {
                        "failure_code": "snake_case",
                        "failure_stage": "阶段",
                        "failure_summary": "失败事实",
                        "lesson": "可复用教训",
                        "retry_strategy": "下一次的具体策略",
                        "corrective_actions": ["动作1"],
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        raw = call_llm_messages(messages)
        return parse_json_model(raw, ReflectionResult)
    except Exception:
        code = evaluation.failed_checks[0].replace(":", "_") if evaluation.failed_checks else "episode_failed"
        return ReflectionResult(
            failure_code=code,
            failure_stage="evaluation",
            failure_summary=evaluation.summary,
            lesson="结束任务前逐项核对确定性 Evaluator 要求。",
            retry_strategy=evaluation.retry_strategy or "重新读取状态并完成缺失步骤。",
            corrective_actions=list(evaluation.failed_checks),
        )
