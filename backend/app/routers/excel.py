from pathlib import Path
import shutil

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.auth import get_current_user
from app.config import BACKEND_ROOT
from app.db.database import SessionLocal
from app.db.models import MandatoryClause, StandardValidityRecord
from app.services.excel_ingest import ingest_excel_to_postgres


router = APIRouter(
    prefix="/excel",
    tags=["Excel 标准库"],
    dependencies=[Depends(get_current_user)],
)
UPLOAD_ROOT = BACKEND_ROOT / "data" / "uploads"


@router.post("/ingest")
def ingest_excel(
    file: UploadFile = File(...),
    sheet: str = Form("强条"),
    replace: bool = Form(True),
):
    upload_dir = UPLOAD_ROOT / "excel"
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / Path(file.filename).name
    with file_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    result = ingest_excel_to_postgres(str(file_path), sheet=sheet, replace=replace)
    return {
        "file_name": file.filename,
        "sheet": sheet,
        "replace": replace,
        **result,
    }


@router.get("/clauses")
def list_excel_clauses():
    with SessionLocal() as session:
        clauses = session.query(MandatoryClause).order_by(MandatoryClause.row_index, MandatoryClause.id).all()
        return {
            "count": len(clauses),
            "items": [
                {
                    "id": item.id,
                    "row_index": item.row_index,
                    "standard_no": item.standard_no,
                    "standard_name": item.standard_name,
                    "category": item.category,
                    "applicable_scope": item.applicable_scope,
                    "mandatory_type": item.mandatory_type,
                    "clause_no": item.clause_no,
                    "clause_text": item.clause_text,
                    "chunk_text": item.chunk_text,
                    "source_file": item.source_file,
                    "sheet_name": item.sheet_name,
                }
                for item in clauses
            ],
        }


@router.get("/standard-validity")
def list_standard_validity():
    with SessionLocal() as session:
        records = session.query(StandardValidityRecord).order_by(
            StandardValidityRecord.row_index,
            StandardValidityRecord.id,
        ).all()
        return {
            "count": len(records),
            "items": [
                {
                    "id": item.id,
                    "row_index": item.row_index,
                    "old_standard_text": item.old_standard_text,
                    "new_standard_text": item.new_standard_text,
                    "new_publish_date": item.new_publish_date,
                    "new_effective_date": item.new_effective_date,
                    "involved_content": item.involved_content,
                    "verified_date": item.verified_date,
                    "note": item.note,
                    "source_url": item.source_url,
                    "source_file": item.source_file,
                    "sheet_name": item.sheet_name,
                }
                for item in records
            ],
        }
