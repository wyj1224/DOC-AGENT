import asyncio
from datetime import date
import json

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import StreamingResponse

from app.agent.workflow import agent_check
from app.db.database import SessionLocal
from app.db.models import (
    AgentEpisode,
    AgentExperience,
    AgentSession,
    AgentStep,
    AgentTask,
    CheckRun,
    User,
    WordDocument,
)
from app.visitor import get_current_visitor


router = APIRouter(
    prefix="/agent",
    tags=["Agent"],
    dependencies=[Depends(get_current_visitor)],
)
@router.post("/check")
def check_with_agent(
    message: str = Form("请全面检查这个文档有没有问题"),
    document_id: int | None = Form(None),
    session_id: int | None = Form(None),
    publish_date: str = Form(""),
    mode: str = Form(""),
    user: User = Depends(get_current_visitor),
):
    parsed_publish_date = date.fromisoformat(publish_date) if publish_date else None
    return agent_check(
        message=message,
        document_id=document_id,
        publish_date=parsed_publish_date,
        owner_user_id=user.id,
        session_id=session_id,
        requested_mode=mode,
    )


@router.post("/check/stream")
async def check_with_agent_stream(
    message: str = Form("请全面检查这个文档有没有问题"),
    document_id: int | None = Form(None),
    session_id: int | None = Form(None),
    publish_date: str = Form(""),
    mode: str = Form(""),
    user: User = Depends(get_current_visitor),
):
    parsed_publish_date = date.fromisoformat(publish_date) if publish_date else None

    async def event_stream():
        yield sse_event("status", {"content": "正在理解问题并执行所需工具…"})
        try:
            result = await asyncio.to_thread(
                agent_check,
                message=message,
                document_id=document_id,
                publish_date=parsed_publish_date,
                owner_user_id=user.id,
                session_id=session_id,
                requested_mode=mode,
            )
            yield sse_event(
                "result",
                {
                    "session_id": result.get("session_id"),
                    "task_id": result.get("task_id"),
                    "episode_id": result.get("episode_id"),
                    "attempt_no": result.get("attempt_no"),
                    "status": result.get("status"),
                    "evaluation": result.get("evaluation"),
                    "run_id": result.get("run_id"),
                    "tool_plan": result.get("tool_plan"),
                    "tool_results": result.get("tool_results"),
                },
            )
            answer = str(result.get("answer", ""))
            for start in range(0, len(answer), 24):
                yield sse_event("delta", {"content": answer[start : start + 24]})
                await asyncio.sleep(0.01)
            yield sse_event("done", {})
        except Exception as exc:
            yield sse_event("error", {"content": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions")
def list_agent_sessions(limit: int = 30, user: User = Depends(get_current_visitor)):
    with SessionLocal() as session:
        items = (
            session.query(AgentSession)
            .filter(AgentSession.owner_user_id == user.id)
            .order_by(AgentSession.updated_at.desc(), AgentSession.id.desc())
            .limit(limit)
            .all()
        )
        document_ids = [item.active_document_id for item in items if item.active_document_id]
        documents = (
            session.query(WordDocument).filter(WordDocument.id.in_(document_ids)).all()
            if document_ids
            else []
        )
        file_names = {item.id: item.file_name for item in documents}
        return {
            "count": len(items),
            "items": [
                agent_session_summary(
                    item,
                    file_names.get(item.active_document_id, ""),
                )
                for item in items
            ],
        }


@router.get("/sessions/{session_id}")
def get_agent_session(session_id: int, user: User = Depends(get_current_visitor)):
    with SessionLocal() as session:
        agent_session = (
            session.query(AgentSession)
            .filter(
                AgentSession.id == session_id,
                AgentSession.owner_user_id == user.id,
            )
            .first()
        )
        if not agent_session:
            raise HTTPException(status_code=404, detail="会话不存在")
        document = (
            session.get(WordDocument, agent_session.active_document_id)
            if agent_session.active_document_id
            else None
        )
        return agent_session_detail(
            agent_session,
            document.file_name if document else "",
        )


@router.delete("/sessions/{session_id}")
def delete_agent_session(session_id: int, user: User = Depends(get_current_visitor)):
    with SessionLocal() as session:
        agent_session = (
            session.query(AgentSession)
            .filter(
                AgentSession.id == session_id,
                AgentSession.owner_user_id == user.id,
            )
            .first()
        )
        if not agent_session:
            raise HTTPException(status_code=404, detail="会话不存在")
        session.delete(agent_session)
        session.commit()
        return {"deleted": True, "session_id": session_id}


@router.get("/runs")
def list_agent_runs(
    document_id: int | None = None,
    session_id: int | None = None,
    run_type: str = "",
    limit: int = 20,
    user: User = Depends(get_current_visitor),
):
    with SessionLocal() as session:
        query = session.query(CheckRun).filter(CheckRun.owner_user_id == user.id)
        if document_id:
            query = query.filter(CheckRun.document_id == document_id)
        if session_id:
            query = query.filter(CheckRun.session_id == session_id)
        if run_type:
            query = query.filter(CheckRun.run_type == run_type)
        runs = query.order_by(CheckRun.id.desc()).limit(limit).all()
        document_ids = [item.document_id for item in runs if item.document_id]
        documents = (
            session.query(WordDocument).filter(WordDocument.id.in_(document_ids)).all()
            if document_ids
            else []
        )
        file_names = {item.id: item.file_name for item in documents}
        return {
            "count": len(runs),
            "items": [check_run_summary(item, file_names.get(item.document_id, "")) for item in runs],
        }


@router.get("/runs/{run_id}")
def get_agent_run(run_id: int, user: User = Depends(get_current_visitor)):
    with SessionLocal() as session:
        check_run = (
            session.query(CheckRun)
            .filter(CheckRun.id == run_id, CheckRun.owner_user_id == user.id)
            .first()
        )
        if not check_run:
            raise HTTPException(status_code=404, detail="check run not found")
        document = session.get(WordDocument, check_run.document_id) if check_run.document_id else None
        return check_run_detail(check_run, document.file_name if document else "")


@router.delete("/runs/{run_id}")
def delete_agent_run(run_id: int, user: User = Depends(get_current_visitor)):
    with SessionLocal() as session:
        check_run = (
            session.query(CheckRun)
            .filter(CheckRun.id == run_id, CheckRun.owner_user_id == user.id)
            .first()
        )
        if not check_run:
            raise HTTPException(status_code=404, detail="对话不存在")
        session.delete(check_run)
        session.commit()
        return {"deleted": True, "run_id": run_id}


@router.get("/tasks")
def list_agent_tasks(
    session_id: int | None = None,
    task_type: str = "",
    limit: int = 20,
    user: User = Depends(get_current_visitor),
):
    with SessionLocal() as session:
        query = session.query(AgentTask).filter(AgentTask.owner_user_id == user.id)
        if session_id:
            query = query.filter(AgentTask.session_id == session_id)
        if task_type:
            query = query.filter(AgentTask.task_type == task_type)
        rows = query.order_by(AgentTask.id.desc()).limit(limit).all()
        return {"count": len(rows), "items": [agent_task_item(row) for row in rows]}


@router.get("/tasks/{task_id}")
def get_agent_task(task_id: int, user: User = Depends(get_current_visitor)):
    with SessionLocal() as session:
        task = (
            session.query(AgentTask)
            .filter(AgentTask.id == task_id, AgentTask.owner_user_id == user.id)
            .first()
        )
        if not task:
            raise HTTPException(status_code=404, detail="AgentTask 不存在")
        episodes = (
            session.query(AgentEpisode)
            .filter(AgentEpisode.task_id == task.id)
            .order_by(AgentEpisode.attempt_no.asc())
            .all()
        )
        episode_items = []
        for episode in episodes:
            steps = (
                session.query(AgentStep)
                .filter(AgentStep.episode_id == episode.id)
                .order_by(AgentStep.step_index.asc())
                .all()
            )
            episode_items.append(
                {
                    "episode_id": episode.id,
                    "attempt_no": episode.attempt_no,
                    "status": episode.status,
                    "retrieved_experience_ids": episode.retrieved_experience_ids,
                    "evaluation": episode.evaluation,
                    "reflection": episode.reflection,
                    "steps": [agent_step_item(step) for step in steps],
                    "started_at": episode.started_at,
                    "finished_at": episode.finished_at,
                }
            )
        return {**agent_task_item(task), "input_data": task.input_data, "episodes": episode_items}


@router.get("/experiences")
def list_agent_experiences(
    task_type: str = "",
    status: str = "active",
    limit: int = 50,
    user: User = Depends(get_current_visitor),
):
    with SessionLocal() as session:
        query = session.query(AgentExperience).filter(AgentExperience.owner_user_id == user.id)
        if task_type:
            query = query.filter(AgentExperience.task_type == task_type)
        if status:
            query = query.filter(AgentExperience.status == status)
        rows = query.order_by(AgentExperience.id.desc()).limit(limit).all()
        return {
            "count": len(rows),
            "items": [
                {
                    "experience_id": row.id,
                    "task_type": row.task_type,
                    "status": row.status,
                    "failure_code": row.failure_code,
                    "failure_summary": row.failure_summary,
                    "lesson": row.lesson,
                    "retry_strategy": row.retry_strategy,
                    "success_summary": row.success_summary,
                    "failed_episode_id": row.failed_episode_id,
                    "successful_episode_id": row.successful_episode_id,
                    "use_count": row.use_count,
                }
                for row in rows
            ],
        }


def agent_session_summary(
    agent_session: AgentSession,
    document_file_name: str = "",
) -> dict[str, object]:
    return {
        "session_id": agent_session.id,
        "title": agent_session.title,
        "active_document_id": agent_session.active_document_id,
        "document_file_name": document_file_name,
        "last_run_id": agent_session.last_run_id,
        "last_task_id": agent_session.last_task_id,
        "last_episode_id": agent_session.last_episode_id,
        "message_count": len(agent_session.messages or []),
        "created_at": agent_session.created_at,
        "updated_at": agent_session.updated_at,
    }


def agent_session_detail(
    agent_session: AgentSession,
    document_file_name: str = "",
) -> dict[str, object]:
    return {
        **agent_session_summary(agent_session, document_file_name),
        "messages": agent_session.messages or [],
        "summary": agent_session.summary,
        "summarized_message_count": agent_session.summarized_message_count,
        "last_word_check_run_id": agent_session.last_word_check_run_id,
    }


def check_run_summary(check_run: CheckRun, document_file_name: str = "") -> dict[str, object]:
    return {
        "run_id": check_run.id,
        "session_id": check_run.session_id,
        "task_id": check_run.task_id,
        "episode_id": check_run.episode_id,
        "run_type": check_run.run_type,
        "document_id": check_run.document_id,
        "document_file_name": document_file_name,
        "status": check_run.status,
        "issue_count": check_run.issue_count,
        "duration_ms": check_run.duration_ms,
        "started_at": check_run.started_at,
        "finished_at": check_run.finished_at,
        "user_message": check_run.user_message,
    }


def check_run_detail(check_run: CheckRun, document_file_name: str = "") -> dict[str, object]:
    return {
        **check_run_summary(check_run, document_file_name),
        "tool_plan": check_run.tool_plan,
        "tool_results": check_run.tool_results,
        "answer": check_run.answer,
        "error_message": check_run.error_message,
    }


def agent_task_item(task: AgentTask) -> dict[str, object]:
    return {
        "task_id": task.id,
        "session_id": task.session_id,
        "task_type": task.task_type,
        "status": task.status,
        "user_message": task.user_message,
        "final_episode_id": task.final_episode_id,
        "final_output": task.final_output,
        "error_message": task.error_message,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }


def agent_step_item(step: AgentStep) -> dict[str, object]:
    return {
        "step_id": step.id,
        "step_index": step.step_index,
        "model_input": step.model_input,
        "raw_model_output": step.raw_model_output,
        "action": step.action,
        "trusted_args": step.trusted_args,
        "observation": step.observation,
        "state_before": step.state_before,
        "state_after": step.state_after,
        "status": step.status,
        "error_message": step.error_message,
        "duration_ms": step.duration_ms,
    }


def sse_event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
