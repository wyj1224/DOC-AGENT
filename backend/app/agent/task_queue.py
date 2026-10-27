"""PostgreSQL-backed task queue for AgentTask rows.

The agent_tasks table is the queue: no separate broker, so a task's queue state
and its business state can never disagree.

Claiming uses ``FOR UPDATE SKIP LOCKED`` so concurrent workers never pick the
same row and never block on each other. Tasks of one session run strictly one at
a time and in order, because they share and append to the same conversation.
"""

from sqlalchemy import text

from app.db.database import SessionLocal


QUEUED = "queued"
RUNNING = "running"
STALE = "stale"

# Locking the session row (``FOR UPDATE OF s``) serialises two workers that race
# for different tasks of the same session; the NOT EXISTS clauses keep a session
# blocked while one of its tasks runs and enforce FIFO order inside the session.
CLAIM_SQL = text(
    """
    WITH candidate AS (
        SELECT t.id
        FROM agent_tasks AS t
        JOIN agent_sessions AS s ON s.id = t.session_id
        WHERE t.status = 'queued'
          AND NOT EXISTS (
              SELECT 1 FROM agent_tasks AS r
              WHERE r.session_id = t.session_id AND r.status = 'running'
          )
          AND NOT EXISTS (
              SELECT 1 FROM agent_tasks AS e
              WHERE e.session_id = t.session_id AND e.status = 'queued' AND e.id < t.id
          )
        ORDER BY t.id
        LIMIT 1
        FOR UPDATE OF t, s SKIP LOCKED
    )
    UPDATE agent_tasks AS t
    SET status = 'running',
        worker_id = :worker_id,
        claimed_at = now(),
        heartbeat_at = now(),
        started_at = now()
    FROM candidate
    WHERE t.id = candidate.id
    RETURNING t.id
    """
)

HEARTBEAT_SQL = text(
    """
    UPDATE agent_tasks
    SET heartbeat_at = now()
    WHERE id = :task_id AND worker_id = :worker_id AND status = 'running'
    """
)

# A worker that dies mid-task stops sending heartbeats; its task is marked stale
# instead of being re-run, because agent steps (LLM calls, Word edits) are not idempotent.
REAP_SQL = text(
    """
    UPDATE agent_tasks
    SET status = 'stale',
        error_message = 'worker ' || worker_id || ' stopped sending heartbeats',
        finished_at = now()
    WHERE status = 'running'
      AND heartbeat_at IS NOT NULL
      AND heartbeat_at < now() - make_interval(secs => :timeout_seconds)
    RETURNING id
    """
)

POSITION_SQL = text(
    """
    SELECT count(*) FROM agent_tasks
    WHERE status = 'queued' AND id < :task_id
    """
)


def claim_next_task(worker_id: str) -> int | None:
    with SessionLocal() as session:
        task_id = session.execute(CLAIM_SQL, {"worker_id": worker_id}).scalar()
        session.commit()
        return task_id


def heartbeat(task_id: int, worker_id: str) -> bool:
    """Return False if the task no longer belongs to this worker (e.g. it was reaped)."""
    with SessionLocal() as session:
        updated = session.execute(
            HEARTBEAT_SQL, {"task_id": task_id, "worker_id": worker_id}
        ).rowcount
        session.commit()
        return updated == 1


def reap_stale_tasks(timeout_seconds: float) -> list[int]:
    with SessionLocal() as session:
        ids = list(
            session.execute(REAP_SQL, {"timeout_seconds": timeout_seconds}).scalars()
        )
        session.commit()
        return ids


def queue_position(task_id: int) -> int:
    """Number of queued tasks ahead of this one across all sessions."""
    with SessionLocal() as session:
        return int(session.execute(POSITION_SQL, {"task_id": task_id}).scalar() or 0)
