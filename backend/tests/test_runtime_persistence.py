from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.agent.contracts import AgentAction, EvaluationResult, ReflectionResult
from app.agent.environments import AgentEnvironment
from app.agent.harness import run_agent
from app.db.models import AgentEpisode, AgentExperience, AgentSession, AgentStep, AgentTask, Base, User


@compiles(JSONB, "sqlite")
def compile_jsonb_for_test(element, compiler, **kwargs):
    del element, compiler, kwargs
    return "JSON"


class StoredEnvironment(AgentEnvironment):
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
        return "测试"


def test_retry_trajectory_and_experience_are_persisted():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with testing_session() as session:
        session.add(User(id=7, username="visitor", password_hash=""))
        session.add(AgentSession(id=9, owner_user_id=7))
        session.add(
            AgentTask(
                id=1,
                owner_user_id=7,
                session_id=9,
                task_type="document_check",
                user_message="全面检查",
            )
        )
        session.commit()

    outcomes = iter(
        [
            EvaluationResult(
                status="retryable_failure",
                summary="缺少检查",
                failed_checks=["missing_tool"],
                retry_strategy="补齐检查",
            ),
            EvaluationResult(status="success", summary="第二次检查通过"),
        ]
    )
    reflection = ReflectionResult(
        failure_code="missing_tool",
        failure_summary="缺少检查",
        lesson="结束前核对工具",
        retry_strategy="补齐检查",
    )

    def factory(episode_id: int):
        return StoredEnvironment(
            task_id=1,
            episode_id=episode_id,
            owner_user_id=7,
            session_id=9,
        )

    with (
        patch("app.agent.runtime_store.SessionLocal", testing_session),
        patch("app.agent.experience_memory.SessionLocal", testing_session),
        patch("app.agent.harness.reflect_on_failure", return_value=reflection),
    ):
        result = run_agent(
            task_id=1,
            owner_user_id=7,
            task_type="document_check",
            user_message="全面检查",
            conversation_context="无",
            environment_factory=factory,
            model_call=lambda _messages: '{"action":"finish"}',
            evaluator=lambda _env, **_kwargs: next(outcomes),
        )

    with testing_session() as session:
        episodes = session.query(AgentEpisode).order_by(AgentEpisode.attempt_no).all()
        steps = session.query(AgentStep).order_by(AgentStep.id).all()
        experience = session.query(AgentExperience).one()

    assert result.evaluation.status == "success"
    assert [episode.status for episode in episodes] == ["retryable_failure", "success"]
    assert len(steps) == 2
    assert experience.status == "active"
    assert experience.failure_summary == "缺少检查"
    assert experience.success_summary == "第二次检查通过"
