from datetime import date
from pathlib import Path
import shutil
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.agent.tools import completeness_check_tool, get_issues_tool, parse_word_tool, word_check_tool
from app.agent.workflow import DEFAULT_MAX_EDIT_CYCLES, run_word_edit_loop
from app.config import BACKEND_ROOT
from app.db.database import SessionLocal
from app.db.models import User, WordDocument, WordSection
from app.services.word_editor import resolve_word_document_path
from app.visitor import get_current_visitor


router = APIRouter(
    prefix="/word",
    tags=["Word 校核"],
    dependencies=[Depends(get_current_visitor)],
)
UPLOAD_ROOT = BACKEND_ROOT / "data" / "uploads"


@router.post("/upload")
def upload_word(
    file: UploadFile = File(...),
    user: User = Depends(get_current_visitor),
):
    if Path(file.filename).suffix.lower() != ".docx":
        raise HTTPException(status_code=400, detail="当前本地解析只支持 .docx 文件")

    upload_dir = UPLOAD_ROOT / "word"
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / f"{uuid4().hex}_{Path(file.filename).name}"
    with file_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return parse_word_tool(
        file_path=str(file_path),
        owner_user_id=user.id,
        file_name=Path(file.filename).name,
    )


@router.post("/check")
def check_word(
    document_id: int | None = Form(None),
    publish_date: str = Form(""),
    replace: bool = Form(True),
    issue_limit: int = Form(50),
    user: User = Depends(get_current_visitor),
):
    parsed_publish_date = date.fromisoformat(publish_date) if publish_date else None
    document_id = document_id or latest_word_document_id(user.id)
    return word_check_tool(
        document_id=document_id,
        publish_date=parsed_publish_date,
        replace=replace,
        issue_limit=issue_limit,
        owner_user_id=user.id,
    )


@router.post("/completeness-check")
def check_word_completeness(
    document_id: int | None = Form(None),
    template_id: int | None = Form(None),
    replace: bool = Form(True),
    issue_limit: int = Form(50),
    user: User = Depends(get_current_visitor),
):
    document_id = document_id or latest_word_document_id(user.id)
    return completeness_check_tool(
        document_id=document_id,
        template_id=template_id,
        replace=replace,
        issue_limit=issue_limit,
        owner_user_id=user.id,
    )


@router.get("/issues")
def get_word_issues(
    document_id: int,
    check_scope: str = "",
    issue_type: str = "",
    severity: str = "",
    issue_limit: int = 50,
    user: User = Depends(get_current_visitor),
):
    return get_issues_tool(
        document_id=document_id,
        check_scope=check_scope,
        issue_type=issue_type,
        severity=severity,
        issue_limit=issue_limit,
        owner_user_id=user.id,
    )


@router.post("/fix-consistency")
def fix_word_consistency(
    document_id: int = Form(...),
    max_attempts: int = Form(DEFAULT_MAX_EDIT_CYCLES),
    user: User = Depends(get_current_visitor),
):
    return run_word_edit_loop(
        message="请修复当前 Word 文档中的一致性问题并生成修订副本",
        document_id=document_id,
        owner_user_id=user.id,
        max_edit_cycles=max_attempts,
    )


@router.get("/documents/{document_id}/download")
def download_word_document(
    document_id: int,
    user: User = Depends(get_current_visitor),
):
    with SessionLocal() as session:
        document = session.get(WordDocument, document_id)
        if not document or document.owner_user_id != user.id:
            raise HTTPException(status_code=404, detail="文档不存在")
        path = resolve_word_document_path(document)
        return FileResponse(
            path=path,
            filename=document.file_name,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


@router.get("/sections")
def get_word_sections(
    document_id: int,
    limit: int = 0,
    user: User = Depends(get_current_visitor),
):
    with SessionLocal() as session:
        document = session.get(WordDocument, document_id)
        if not document or document.owner_user_id != user.id:
            raise HTTPException(status_code=404, detail="document not found")
        sections = (
            session.query(WordSection)
            .filter(WordSection.document_id == document_id)
            .order_by(WordSection.section_index, WordSection.id)
            .all()
        )
        returned_sections = sections if limit <= 0 else sections[:limit]
        return {
            "document_id": document.id,
            "file_name": document.file_name,
            "section_count": len(sections),
            "returned_section_count": len(returned_sections),
            "sections": [word_section_item(item) for item in returned_sections],
        }


def latest_word_document_id(owner_user_id: int) -> int:
    with SessionLocal() as session:
        document = (
            session.query(WordDocument)
            .filter(WordDocument.owner_user_id == owner_user_id)
            .order_by(WordDocument.id.desc())
            .first()
        )
        if not document:
            raise HTTPException(status_code=400, detail="请先上传 Word 文件")
        return document.id


def word_section_item(section: WordSection) -> dict[str, object]:
    return {
        "section_id": section.id,
        "section_index": section.section_index,
        "paragraph_start": section.paragraph_start,
        "paragraph_end": section.paragraph_end,
        "level": section.level,
        "heading_no": section.heading_no,
        "title": section.title,
        "full_title": section.full_title,
        "section_path": section.section_path,
        "body_text": section.body_text,
        "body_length": section.body_length,
    }
