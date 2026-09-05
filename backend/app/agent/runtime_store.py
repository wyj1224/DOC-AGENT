from datetime import datetime, timezone

from app.agent.contracts import EvaluationResult, ReflectionResult
from app.db.database import SessionLocal
from app.db.models import AgentEpisode, AgentStep, AgentTask


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_task(
    *, owner_user_id: int, session_id: int | None, task_type: str, user_message: str, input_data: dict
) -> int:
    with SessionLocal() as session:
        row = AgentTask(
            owner_user_id=owner_user_id,
            session_id=session_id,
            task_type=task_type,
            user_message=user_message,
            input_data=input_data,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def create_episode(*, task_id: int, attempt_no: int, experience_ids: list[int]) -> int:
    with SessionLocal() as session:
        row = AgentEpisode(
            task_id=task_id,
            attempt_no=attempt_no,
            retrieved_experience_ids=experience_ids,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def save_step(
    *,
    episode_id: int,
    step_index: int,
    model_input: list[dict],
    raw_model_output: str,
    action: dict,
    trusted_args: dict,
    observation: dict,
    state_before: dict,
    state_after: dict,
    status: str,
    error_message: str,
    duration_ms: int,
) -> None:
    with SessionLocal() as session:
        session.add(
            AgentStep(
                episode_id=episode_id,
                step_index=step_index,
                model_input=model_input,
                raw_model_output=raw_model_output,
                action=action,
                trusted_args=trusted_args,
                observation=observation,
                state_before=state_before,
                state_after=state_after,
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
            )
        )
        session.commit()


def finish_episode(
    *,
    episode_id: int,
    evaluation: EvaluationResult,
    final_output: dict,
    reflection: ReflectionResult | None = None,
) -> None:
    with SessionLocal() as session:
        row = session.get(AgentEpisode, episode_id)
        if not row:
            raise ValueError("AgentEpisode 不存在")
        row.status = evaluation.status
        row.evaluation = evaluation.model_dump()
        row.reflection = reflection.model_dump() if reflection else {}
        row.final_output = final_output
        row.finished_at = utcnow()
        session.commit()


def finish_task(*, task_id: int, episode_id: int, evaluation: EvaluationResult, output: dict) -> None:
    with SessionLocal() as session:
        row = session.get(AgentTask, task_id)
        if not row:
            raise ValueError("AgentTask 不存在")
        row.status = evaluation.status
        row.final_episode_id = episode_id
        row.final_output = output
        row.error_message = "" if evaluation.status == "success" else evaluation.summary
        row.finished_at = utcnow()
        session.commit()


def load_episode_steps(episode_id: int) -> list[dict]:
    with SessionLocal() as session:
        rows = (
            session.query(AgentStep)
            .filter(AgentStep.episode_id == episode_id)
            .order_by(AgentStep.step_index.asc())
            .all()
        )
        return [
            {
                "step": row.step_index,
                "action": row.action,
                "trusted_args": row.trusted_args,
                "observation": row.observation,
                "status": row.status,
                "error": row.error_message,
            }
            for row in rows
        ]
