import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import llm
from app.agent import workflow
from app.agent.contracts import EvaluationResult
from app.cli.worker import Worker
from app.db.models import AgentSession, AgentTask, Base, User
from app.services.session_memory import SessionContext


@compiles(JSONB, "sqlite")
def compile_jsonb_for_test(element, compiler, **kwargs):
    del element, compiler, kwargs
    return "JSON"


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine)
    with testing_session() as session:
        session.add(User(id=7, username="visitor", password_hash=""))
        session.add(AgentSession(id=9, owner_user_id=7, messages=[]))
        session.commit()
    with patch("app.agent.runtime_store.SessionLocal", testing_session):
        yield testing_session


def enqueue(**overrides):
    kwargs = {"message": "全面检查", "document_id": 3, "owner_user_id": 7, "session_id": 9}
    kwargs.update(overrides)
    with patch.object(
        workflow,
        "prepare_session",
        return_value=SessionContext(session_id=9, document_id=3, conversation="无"),
    ):
        return workflow.enqueue_agent_check(**kwargs)


def test_enqueue_persists_everything_the_worker_needs(db):
    queued = enqueue(requested_mode="word_edit", max_edit_cycles=2)

    assert queued["status"] == "queued"
    with db() as session:
        task = session.get(AgentTask, queued["task_id"])
        assert task.status == "queued"
        assert task.task_type == "word_edit"
        assert task.session_id == 9
        assert task.input_data["document_id"] == 3
        assert task.input_data["max_edit_cycles"] == 2


def test_enqueue_without_document_fails_before_creating_a_task(db):
    with patch.object(
        workflow,
        "prepare_session",
        return_value=SessionContext(session_id=9, document_id=None, conversation="无"),
    ), pytest.raises(ValueError, match="Word"):
        workflow.enqueue_agent_check(message="检查", owner_user_id=7, session_id=9)
    with db() as session:
        assert session.query(AgentTask).count() == 0


def test_crash_marks_task_error_instead_of_leaving_it_running(db):
    task_id = enqueue()["task_id"]

    with (
        patch.object(workflow, "load_session_context", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError),
    ):
        workflow.run_agent_task(task_id)

    with db() as session:
        task = session.get(AgentTask, task_id)
        assert task.status == "error"
        assert "boom" in task.error_message
        assert task.finished_at is not None


def test_finished_task_stores_response_for_pollers(db):
    task_id = enqueue()["task_id"]
    evaluation = EvaluationResult(status="success", summary="ok", evidence={})
    harness_result = SimpleNamespace(
        episode_id=11,
        attempt_no=1,
        evaluation=evaluation,
        output={"tool_results": []},
        environment=None,
    )

    with (
        patch.object(
            workflow,
            "load_session_context",
            return_value=SessionContext(session_id=9, document_id=3, conversation="无"),
        ),
        patch.object(workflow, "run_agent", return_value=harness_result),
        patch.object(workflow, "answer_for_result", return_value="本次检查共发现 0 个问题。"),
        patch.object(workflow, "append_turn"),
    ):
        response = workflow.run_agent_task(task_id)

    with db() as session:
        task = session.get(AgentTask, task_id)
        assert task.status == "success"
        assert task.response_payload["answer"] == response["answer"]
        assert task.response_payload["task_id"] == task_id


def test_llm_calls_never_exceed_the_concurrency_limit(monkeypatch):
    active = 0
    peak = 0
    lock = threading.Lock()

    def create(**_kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm, "_llm_slots", threading.BoundedSemaphore(2))
    monkeypatch.setattr(llm, "llm_client", lambda *_: client)
    monkeypatch.setattr(
        llm,
        "get_settings",
        lambda: SimpleNamespace(llm_api_key="k", llm_base_url="u", llm_model="m"),
    )

    threads = [
        threading.Thread(target=llm.call_llm_messages, args=([{"role": "user", "content": "x"}],))
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak == 2


def test_worker_heartbeats_while_task_runs_and_survives_crashes():
    beats: list[int] = []
    worker = Worker(concurrency=1, poll_interval=0.01, heartbeat_interval=0.01, stale_after=1)

    def slow_task(task_id):
        time.sleep(0.05)
        raise RuntimeError("crash")

    with (
        patch("app.cli.worker.run_agent_task", side_effect=slow_task),
        patch("app.cli.worker.heartbeat", side_effect=lambda task_id, _: beats.append(task_id) or True),
    ):
        worker.execute(5)

    assert beats and set(beats) == {5}


def test_worker_rejects_heartbeat_slower_than_stale_timeout():
    with pytest.raises(ValueError):
        Worker(concurrency=1, poll_interval=1, heartbeat_interval=40, stale_after=60)
