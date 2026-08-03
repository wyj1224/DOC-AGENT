from pathlib import Path
import shutil

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import BACKEND_ROOT
from app.db.database import SessionLocal
from app.db.models import WordTemplate, WordTemplateHeading, WordTemplateKeySection
from app.services.template_ingest import ingest_word_template, template_type_label


router = APIRouter(prefix="/templates", tags=["Word 模板"])
UPLOAD_ROOT = BACKEND_ROOT / "data" / "uploads"


@router.post("/upload")
def upload_template(
    files: list[UploadFile] | None = File(None),
    file: UploadFile | None = File(None),
):
    upload_files = files or ([file] if file else [])
    if not upload_files:
        raise HTTPException(status_code=400, detail="请先选择模板 Word")

    upload_dir = UPLOAD_ROOT / "templates"
    upload_dir.mkdir(parents=True, exist_ok=True)

    items = []
    for upload_file in upload_files:
        if Path(upload_file.filename).suffix.lower() != ".docx":
            raise HTTPException(status_code=400, detail="当前模板解析只支持 .docx 文件")
        file_path = upload_dir / Path(upload_file.filename).name
        with file_path.open("wb") as out:
            shutil.copyfileobj(upload_file.file, out)
        items.append(ingest_word_template(str(file_path)))

    result = dict(items[-1])
    result["count"] = len(items)
    result["items"] = items
    return result


@router.get("")
def list_templates(limit: int = 10):
    with SessionLocal() as session:
        templates = session.query(WordTemplate).order_by(WordTemplate.id.desc()).limit(limit).all()
        return {
            "count": len(templates),
            "items": [template_summary(item) for item in templates],
        }


@router.get("/{template_id}")
def get_template(template_id: int):
    with SessionLocal() as session:
        template = session.get(WordTemplate, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="template not found")
        headings = (
            session.query(WordTemplateHeading)
            .filter(WordTemplateHeading.template_id == template_id)
            .order_by(WordTemplateHeading.heading_index)
            .all()
        )
        return {
            **template_summary(template),
            "headings": [template_heading_item(item) for item in headings],
        }


@router.delete("/{template_id}")
def delete_template(template_id: int):
    with SessionLocal() as session:
        template = session.get(WordTemplate, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="模板不存在")
        session.query(WordTemplateHeading).filter(
            WordTemplateHeading.template_id == template_id
        ).delete()
        session.query(WordTemplateKeySection).filter(
            WordTemplateKeySection.template_id == template_id
        ).delete()
        session.delete(template)
        session.commit()
        return {"template_id": template_id, "deleted": True}


def template_summary(template: WordTemplate) -> dict[str, object]:
    return {
        "template_id": template.id,
        "file_name": template.file_name,
        "template_year": template.template_year,
        "template_type": template.template_type,
        "template_type_label": template_type_label(template.template_type),
        "parse_status": template.parse_status,
        "heading_count": template.heading_count,
        "created_at": template.created_at,
    }


def template_heading_item(heading: WordTemplateHeading) -> dict[str, object]:
    return {
        "heading_index": heading.heading_index,
        "paragraph_index": heading.paragraph_index,
        "level": heading.level,
        "heading_no": heading.heading_no,
        "title": heading.title,
        "full_title": heading.full_title,
    }
