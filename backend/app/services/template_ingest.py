import re
from pathlib import Path

from docx import Document

from app.config import BACKEND_ROOT
from app.db.database import SessionLocal
from app.db.models import WordTemplate, WordTemplateHeading, WordTemplateKeySection
from app.services.key_section_diff import extract_key_sections
from app.services.word_sections import parse_heading
from app.services.word_sections import extract_word_sections


TEMPLATE_TYPE_LABELS = {
    "700m": "700M",
    "indoor": "室内",
    "outdoor": "室外",
}


def ingest_word_template(file_path: str) -> dict[str, object]:
    path = Path(file_path)
    headings = extract_template_headings(file_path)
    key_sections = extract_key_sections(extract_word_sections(file_path))
    parsed_year = infer_template_year(path.name)
    parsed_type = infer_template_type(path.name)

    with SessionLocal() as session:
        existing_ids = [
            item[0]
            for item in session.query(WordTemplate.id)
            .filter(
                WordTemplate.template_year == parsed_year,
                WordTemplate.template_type == parsed_type,
            )
            .all()
        ]
        if existing_ids:
            session.query(WordTemplateKeySection).filter(
                WordTemplateKeySection.template_id.in_(existing_ids)
            ).delete(synchronize_session=False)
            session.query(WordTemplateHeading).filter(
                WordTemplateHeading.template_id.in_(existing_ids)
            ).delete(synchronize_session=False)
            session.query(WordTemplate).filter(WordTemplate.id.in_(existing_ids)).delete(
                synchronize_session=False
            )

        template = WordTemplate(
            file_name=path.name,
            template_year=parsed_year,
            template_type=parsed_type,
            parse_status="parsed",
            heading_count=len(headings),
        )
        session.add(template)
        session.flush()

        for item in headings:
            session.add(WordTemplateHeading(template_id=template.id, **item))
        for item in key_sections:
            session.add(WordTemplateKeySection(template_id=template.id, **item))

        session.commit()
        template_id = template.id

    return {
        "template_id": template_id,
        "file_name": path.name,
        "template_year": parsed_year,
        "template_type": parsed_type,
        "template_type_label": template_type_label(parsed_type),
        "heading_count": len(headings),
        "key_section_count": len(key_sections),
    }


def ensure_template_key_sections(session, template: WordTemplate) -> list[WordTemplateKeySection]:
    stored = (
        session.query(WordTemplateKeySection)
        .filter(WordTemplateKeySection.template_id == template.id)
        .order_by(WordTemplateKeySection.id)
        .all()
    )
    if stored:
        return stored

    file_path = BACKEND_ROOT / "data" / "uploads" / "templates" / template.file_name
    if not file_path.exists():
        return []
    for item in extract_key_sections(extract_word_sections(str(file_path))):
        session.add(WordTemplateKeySection(template_id=template.id, **item))
    session.flush()
    return (
        session.query(WordTemplateKeySection)
        .filter(WordTemplateKeySection.template_id == template.id)
        .order_by(WordTemplateKeySection.id)
        .all()
    )


def extract_template_headings(file_path: str) -> list[dict[str, object]]:
    document = Document(file_path)
    headings: list[dict[str, object]] = []

    for paragraph_index, paragraph in enumerate(document.paragraphs):
        text = paragraph.text.strip()
        if not text:
            continue

        style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
        if style_name.lower().startswith("toc"):
            continue

        level, heading_no, title = parse_heading(paragraph, text)
        if not level:
            continue

        headings.append(
            {
                "heading_index": len(headings),
                "paragraph_index": paragraph_index,
                "level": level,
                "heading_no": heading_no,
                "title": title,
                "full_title": text,
            }
        )

    return headings


def infer_template_year(file_name: str) -> int:
    match = re.search(r"(20\d{2})", file_name)
    return int(match.group(1)) if match else 0


def infer_template_type(file_name: str) -> str:
    text = re.sub(r"\s+", "", file_name).lower()
    if "700m" in text:
        return "700m"
    if "室内" in text or "室分" in text:
        return "indoor"
    if "室外" in text or "宏站" in text:
        return "outdoor"
    return ""


def template_type_label(value: str) -> str:
    return TEMPLATE_TYPE_LABELS.get(value, value or "-")
