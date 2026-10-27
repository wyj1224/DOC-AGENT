"""Queue semantics against a real PostgreSQL (SKIP LOCKED has no SQLite equivalent).

Skipped unless TEST_DATABASE_URL points at a disposable database, e.g.
    TEST_DATABASE_URL=postgresql+psycopg://clause_agent:clause_agent@localhost:5432/clause_agent_test
"""

import os
import threading
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.agent import task_queue
from app.db.models import AgentSession, AgentTask, Base, User

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set")


def reset_schema(engine) -> None:
    # The schema has FK cycles (tasks <-> sessions <-> runs), so drop the whole schema.
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


@pytest.fixture
def db():
    engine = create_engine(TEST_DATABASE_URL)
    reset_schema(engine)
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine)
    with testing_session() as session:
        session.add(User(id=1, username="visitor", password_hash=""))
        session.flush()
        session.add_all([AgentSession(id=sid, owner_user_id=1) for sid in (1, 2, 3)])
        session.commit()
    with patch.object(task_queue, "SessionLocal", testing_session):
        yield testing_session
    reset_schema(engine)
    engine.dispose()


def add_tasks(db, *session_ids: int) -> list[int]:
    with db() as session:
        rows = [
            AgentTask(
                owner_user_id=1,
                session_id=sid,
                task_type="document_check",
                user_message="检查",
                status="queued",
            )
            for sid in session_ids
        ]
        session.add_all(rows)
        session.commit()
        return [row.id for row in rows]


def statuses(db) -> dict[int, str]:
    with db() as session:
        return {row.id: row.status for row in session.query(AgentTask).all()}


def test_concurrent_workers_never_claim_the_same_task(db):
    add_tasks(db, *range(1, 4), *range(1, 4), *range(1, 4))
    claimed: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker(index: int):
        barrier.wait()
        task_id = task_queue.claim_next_task(f"w{index}")
        if task_id is not None:
            with lock:
                claimed.append(task_id)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(claimed) == len(set(claimed))
    # Only one task per session may run at a time, and there are three sessions.
    assert len(claimed) == 3


def test_session_tasks_run_one_at_a_time_in_order(db):
    first, second = add_tasks(db, 1, 1)

    assert task_queue.claim_next_task("w1") == first
    assert task_queue.claim_next_task("w2") is None

    with db() as session:
        session.get(AgentTask, first).status = "success"
        session.commit()
    assert task_queue.claim_next_task("w2") == second


def test_other_sessions_are_not_blocked(db):
    first, _, other = add_tasks(db, 1, 1, 2)

    assert task_queue.claim_next_task("w1") == first
    assert task_queue.claim_next_task("w2") == other


def test_claim_records_worker_and_heartbeat(db):
    (task_id,) = add_tasks(db, 1)
    task_queue.claim_next_task("host:42")

    with db() as session:
        row = session.get(AgentTask, task_id)
        assert row.status == "running"
        assert row.worker_id == "host:42"
        assert row.heartbeat_at is not None
    assert task_queue.heartbeat(task_id, "host:42") is True
    assert task_queue.heartbeat(task_id, "someone-else") is False


def test_stale_running_task_is_reaped_not_requeued(db):
    task_id, fresh = add_tasks(db, 1, 2)
    task_queue.claim_next_task("dead")
    task_queue.claim_next_task("alive")
    with db() as session:
        session.execute(
            text("UPDATE agent_tasks SET heartbeat_at = now() - interval '5 minutes' WHERE id = :id"),
            {"id": task_id},
        )
        session.commit()

    assert task_queue.reap_stale_tasks(60) == [task_id]
    assert statuses(db) == {task_id: "stale", fresh: "running"}
    assert task_queue.heartbeat(task_id, "dead") is False


def test_queue_position_counts_tasks_ahead(db):
    ids = add_tasks(db, 1, 2, 3)
    assert [task_queue.queue_position(task_id) for task_id in ids] == [0, 1, 2]
