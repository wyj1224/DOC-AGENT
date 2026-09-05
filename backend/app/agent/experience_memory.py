import json

from app.agent.contracts import ReflectionResult
from app.db.database import SessionLocal
from app.db.models import AgentExperience


MAX_EXPERIENCES = 8
MAX_EXPERIENCE_CHARS = 8000


def load_active_experiences(*, owner_user_id: int, task_type: str) -> list[dict]:
    """Load only validated insights owned by the current user; no vector search."""
    with SessionLocal() as session:
        rows = (
            session.query(AgentExperience)
            .filter(
                AgentExperience.owner_user_id == owner_user_id,
                AgentExperience.task_type == task_type,
                AgentExperience.status == "active",
            )
            .order_by(AgentExperience.updated_at.desc())
            .limit(MAX_EXPERIENCES)
            .all()
        )
        result = []
        total_chars = 0
        for row in rows:
            item = {
                "id": row.id,
                "failure_code": row.failure_code,
                "failure_summary": row.failure_summary,
                "lesson": row.lesson,
                "retry_strategy": row.retry_strategy,
                "success_summary": row.success_summary,
            }
            item_chars = len(json.dumps(item, ensure_ascii=False))
            if total_chars + item_chars > MAX_EXPERIENCE_CHARS:
                break
            row.use_count += 1
            result.append(item)
            total_chars += item_chars
        session.commit()
        return result


def create_candidate(
    *, owner_user_id: int, task_type: str, episode_id: int, reflection: ReflectionResult, evidence: dict
) -> int:
    with SessionLocal() as session:
        row = AgentExperience(
            owner_user_id=owner_user_id,
            task_type=task_type,
            status="candidate",
            failure_code=reflection.failure_code,
            failure_stage=reflection.failure_stage,
            failure_summary=reflection.failure_summary,
            lesson=reflection.lesson,
            retry_strategy=reflection.retry_strategy,
            corrective_actions=reflection.corrective_actions,
            evidence=evidence,
            failed_episode_id=episode_id,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def activate_candidate(
    experience_id: int, *, successful_episode_id: int, success_summary: str
) -> None:
    with SessionLocal() as session:
        row = session.get(AgentExperience, experience_id)
        if row and row.status == "candidate":
            row.status = "active"
            row.successful_episode_id = successful_episode_id
            row.success_summary = success_summary
            row.success_after_use_count += 1
            session.commit()


def retire_candidate(experience_id: int) -> None:
    with SessionLocal() as session:
        row = session.get(AgentExperience, experience_id)
        if row and row.status == "candidate":
            row.status = "retired"
            session.commit()
