import asyncio
from datetime import date
import json
from pathlib import Path
import shutil
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.agent.workflow import agent_check
from app.auth import get_current_user
from app.config import BACKEND_ROOT
from app.db.database import SessionLocal
from app.db.models import AgentSession, CheckRun, ClauseExtractionRun, User, WordDocument


router = APIRouter(
    prefix="/agent",
    tags=["Agent"],
    dependencies=[Depends(get_current_user)],
)
UPLOAD_ROOT = BACKEND_ROOT / "data" / "uploads"


@router.post("/check")
def check_with_agent(
    message: str = Form("请全面检查这个文档有没有问题"),
    document_id: int | None = Form(None),
    session_id: int | None = Form(None),
    publish_date: str = Form(""),
    mode: str = Form(""),
    file: UploadFile | None = File(None),
    user: User = Depends(get_current_user),
):
    file_path = save_agent_upload(file, mode) if file else ""
    parsed_publish_date = date.fromisoformat(publish_date) if publish_date else None
    return agent_check(
        message=message,
        document_id=document_id,
        file_path=file_path,
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
    file: UploadFile | None = File(None),
    user: User = Depends(get_current_user),
):
    parsed_publish_date = date.fromisoformat(publish_date) if publish_date else None
    file_path = save_agent_upload(file, mode) if file else ""

    async def event_stream():
        yield sse_event("status", {"content": "正在理解问题并执行所需工具…"})
        try:
            result = await asyncio.to_thread(
                agent_check,
                message=message,
                document_id=document_id,
                file_path=file_path,
                publish_date=parsed_publish_date,
                owner_user_id=user.id,
                session_id=session_id,
                requested_mode=mode,
            )
            yield sse_event(
                "result",
                {
                    "session_id": result.get("session_id"),
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
def list_agent_sessions(limit: int = 30, user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        items = (
            session.query(AgentSession)
            .filter(AgentSession.owner_user_id == user.id)
            .order_by(AgentSession.updated_at.desc(), AgentSession.id.desc())
            .limit(limit)
            .all()
        )
        document_ids = [item.active_document_id for item in items if item.active_document_id]
        extraction_ids = [
            item.active_clause_extraction_run_id
            for item in items
            if item.active_clause_extraction_run_id
        ]
        documents = (
            session.query(WordDocument).filter(WordDocument.id.in_(document_ids)).all()
            if document_ids
            else []
        )
        file_names = {item.id: item.file_name for item in documents}
        extractions = (
            session.query(ClauseExtractionRun).filter(ClauseExtractionRun.id.in_(extraction_ids)).all()
            if extraction_ids
            else []
        )
        extraction_file_names = {item.id: item.file_name for item in extractions}
        return {
            "count": len(items),
            "items": [
                agent_session_summary(
                    item,
                    file_names.get(item.active_document_id, ""),
                    extraction_file_names.get(item.active_clause_extraction_run_id, ""),
                )
                for item in items
            ],
        }


@router.get("/sessions/{session_id}")
def get_agent_session(session_id: int, user: User = Depends(get_current_user)):
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
        extraction = (
            session.get(ClauseExtractionRun, agent_session.active_clause_extraction_run_id)
            if agent_session.active_clause_extraction_run_id
            else None
        )
        return agent_session_detail(
            agent_session,
            document.file_name if document else "",
            extraction.file_name if extraction else "",
        )


@router.delete("/sessions/{session_id}")
def delete_agent_session(session_id: int, user: User = Depends(get_current_user)):
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
    limit: int = 20,
    user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        query = session.query(CheckRun).filter(CheckRun.owner_user_id == user.id)
        if document_id:
            query = query.filter(CheckRun.document_id == document_id)
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
def get_agent_run(run_id: int, user: User = Depends(get_current_user)):
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
def delete_agent_run(run_id: int, user: User = Depends(get_current_user)):
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


def agent_session_summary(
    agent_session: AgentSession,
    document_file_name: str = "",
    clause_extraction_file_name: str = "",
) -> dict[str, object]:
    return {
        "session_id": agent_session.id,
        "title": agent_session.title,
        "active_document_id": agent_session.active_document_id,
        "document_file_name": document_file_name,
        "active_clause_extraction_run_id": agent_session.active_clause_extraction_run_id,
        "clause_extraction_file_name": clause_extraction_file_name,
        "last_run_id": agent_session.last_run_id,
        "message_count": len(agent_session.messages or []),
        "created_at": agent_session.created_at,
        "updated_at": agent_session.updated_at,
    }


def agent_session_detail(
    agent_session: AgentSession,
    document_file_name: str = "",
    clause_extraction_file_name: str = "",
) -> dict[str, object]:
    return {
        **agent_session_summary(
            agent_session,
            document_file_name,
            clause_extraction_file_name,
        ),
        "messages": agent_session.messages or [],
        "summary": agent_session.summary,
        "summarized_message_count": agent_session.summarized_message_count,
        "last_check_run_id": agent_session.last_check_run_id,
    }


def check_run_summary(check_run: CheckRun, document_file_name: str = "") -> dict[str, object]:
    return {
        "run_id": check_run.id,
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


def sse_event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def save_agent_upload(file: UploadFile, mode: str) -> str:
    original_name = Path(file.filename or "upload").name
    suffix = Path(original_name).suffix.lower()
    if mode == "clause_extract" and suffix != ".pdf":
        raise HTTPException(status_code=400, detail="强条抽取只支持 PDF 文件")
    folder = "clause_extraction" if mode == "clause_extract" or suffix == ".pdf" else "word"
    upload_dir = UPLOAD_ROOT / folder
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_path = upload_dir / f"{uuid4().hex}_{original_name}"
    with saved_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return str(saved_path)
