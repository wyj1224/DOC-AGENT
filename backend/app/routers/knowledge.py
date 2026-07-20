from pathlib import Path
import shutil
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.agent.tools import knowledge_query_tool
from app.auth import get_current_user
from app.config import BACKEND_ROOT
from app.db.database import SessionLocal
from app.db.models import KnowledgeDocument
from app.knowledge_store import KnowledgeMilvusStore
from app.services.knowledge_base import ingest_knowledge_document, knowledge_document_item


router = APIRouter(
    prefix="/knowledge",
    tags=["知识库"],
    dependencies=[Depends(get_current_user)],
)
UPLOAD_ROOT = BACKEND_ROOT / "data" / "uploads"


@router.post("/documents")
def upload_knowledge_documents(files: list[UploadFile] = File(...)):
    upload_dir = UPLOAD_ROOT / "knowledge"
    upload_dir.mkdir(parents=True, exist_ok=True)

    items = []
    for upload_file in files:
        file_name = Path(upload_file.filename).name
        file_path = upload_dir / f"{uuid4().hex[:8]}_{file_name}"
        with file_path.open("wb") as out:
            shutil.copyfileobj(upload_file.file, out)
        try:
            items.append(ingest_knowledge_document(str(file_path), file_name))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"count": len(items), "items": items}


@router.get("/documents")
def list_knowledge_documents(limit: int = 100):
    with SessionLocal() as session:
        documents = session.query(KnowledgeDocument).order_by(KnowledgeDocument.id.desc()).limit(limit).all()
        return {
            "count": len(documents),
            "items": [knowledge_document_item(document) for document in documents],
        }


@router.delete("/documents/{document_id}")
def delete_knowledge_document(document_id: int):
    with SessionLocal() as session:
        document = session.get(KnowledgeDocument, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="知识库文件不存在")
        file_path = Path(document.file_path)
        KnowledgeMilvusStore().delete_document(document_id)
        session.delete(document)
        session.commit()
    file_path.unlink(missing_ok=True)
    return {"document_id": document_id, "deleted": True}


@router.post("/query")
def query_knowledge(question: str = Form(...), limit: int = Form(5)):
    if not question.strip():
        raise HTTPException(status_code=400, detail="请输入问题")
    try:
        return knowledge_query_tool(question.strip(), limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
