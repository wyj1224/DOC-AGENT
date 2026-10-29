import shutil
from datetime import date
from pathlib import Path

from app.config import BACKEND_ROOT
from app.db.database import SessionLocal
from app.db.models import CheckIssue, WordDocument, WordEditRun, WordReference, WordSection
from app.services.completeness_check import check_body_completeness
from app.services.word_check import check_word_document, issue_sort_key, issue_to_dict
from app.services.word_references import extract_references
from app.services.word_sections import extract_word_sections
from app.word_loader import parse_docx_file


UPLOAD_ROOT = BACKEND_ROOT / "data" / "uploads"


def parse_word_tool(
    file_path: str | None = None,
    document_id: int | None = None,
    owner_user_id: int | None = None,
    edit_run_id: int | None = None,
    edit_cycle: int | None = None,
    file_name: str | None = None,
) -> dict[str, object]:
    """Parse a Word file into references and sections.

    ``file_name`` is the name shown to users; it defaults to the file's own name.
    Parsing is CPU-bound and takes seconds on large documents, so it runs between
    two short transactions instead of holding a pooled connection throughout.
    """
    if document_id:
        return get_document_parse_result(document_id, owner_user_id=owner_user_id)

    if not file_path:
        raise ValueError("缺少 Word 文件路径")
    if (edit_run_id is None) != (edit_cycle is None):
        raise ValueError("edit_run_id 和 edit_cycle 必须同时提供")

    source_path = Path(file_path)
    display_name = file_name or source_path.name
    upload_dir = UPLOAD_ROOT / "word"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 1. Claim the document row.
    with SessionLocal() as session:
        document = None
        if edit_run_id is not None:
            edit_run = session.get(WordEditRun, edit_run_id)
            if not edit_run or edit_run.owner_user_id != owner_user_id:
                raise ValueError("Word 修订任务不存在或不属于当前访客")
            if not any(int(item.get("cycle") or 1) == edit_cycle for item in list(edit_run.changes or [])):
                raise ValueError("Word 修订任务中不存在指定 cycle")
            document = (
                session.query(WordDocument)
                .filter(
                    WordDocument.edit_run_id == edit_run_id,
                    WordDocument.edit_cycle == edit_cycle,
                )
                .with_for_update()
                .first()
            )
            if document and document.owner_user_id != owner_user_id:
                raise ValueError("修订副本不属于当前访客")
            if document and document.parse_status == "parsed":
                return current_parse_result(session, document)

        if document is None:
            document = WordDocument(
                owner_user_id=owner_user_id,
                file_name=display_name,
                parse_status="parsing",
                edit_run_id=edit_run_id,
                edit_cycle=edit_cycle,
            )
            session.add(document)
        else:
            document.file_name = display_name
            document.parse_status = "parsing"
            session.query(WordReference).filter(WordReference.document_id == document.id).delete()
            session.query(WordSection).filter(WordSection.document_id == document.id).delete()
        session.flush()
        new_document_id = document.id
        saved_path = upload_dir / f"{new_document_id}_{display_name}"
        document.file_path = str(saved_path)
        session.commit()

    # 2. Parse without a database connection.
    try:
        if source_path.resolve() != saved_path.resolve():
            shutil.copyfile(source_path, saved_path)
        chunks = parse_docx_file(str(saved_path))
        references = extract_references(chunks)
        sections = extract_word_sections(str(saved_path))
    except Exception:
        with SessionLocal() as session:
            failed = session.get(WordDocument, new_document_id)
            failed.parse_status = "failed"
            session.commit()
        raise

    # 3. Store the results.
    with SessionLocal() as session:
        document = session.get(WordDocument, new_document_id)
        for item in references:
            session.add(
                WordReference(
                    owner_user_id=owner_user_id,
                    document_id=document.id,
                    file_name=document.file_name,
                    section_title=str(item["section_title"]),
                    paragraph_index=int(item["paragraph_index"]),
                    standard_no=str(item["standard_no"]),
                    standard_name=str(item["standard_name"]),
                    clause_no=str(item["clause_no"]),
                    quoted_text=str(item["quoted_text"]),
                    context=str(item["context"]),
                    locator=dict(item.get("locator") or {}),
                )
            )
        for item in sections:
            session.add(
                WordSection(
                    owner_user_id=owner_user_id,
                    document_id=document.id,
                    file_name=document.file_name,
                    section_index=int(item["section_index"]),
                    paragraph_start=int(item["paragraph_start"]),
                    paragraph_end=int(item["paragraph_end"]),
                    level=int(item["level"]),
                    heading_no=str(item["heading_no"]),
                    title=str(item["title"]),
                    full_title=str(item["full_title"]),
                    section_path=str(item["section_path"]),
                    body_text=str(item["body_text"]),
                    body_length=int(item["body_length"]),
                )
            )
        document.parse_status = "parsed"
        session.flush()
        result = parse_result_dict(document, saved_path, len(chunks), len(references), len(sections))
        session.commit()
        return result


def word_check_tool(
    document_id: int,
    replace: bool = True,
    issue_limit: int = 50,
    publish_date: date | None = None,
    owner_user_id: int | None = None,
) -> dict[str, object]:
    with SessionLocal() as session:
        require_owned_document(session, document_id, owner_user_id)
        return check_word_document(
            session,
            document_id=document_id,
            publish_date=publish_date,
            replace=replace,
            check_scope="all",
            issue_limit=issue_limit,
        )


def completeness_check_tool(
    document_id: int,
    template_id: int | None = None,
    replace: bool = True,
    issue_limit: int = 50,
    owner_user_id: int | None = None,
) -> dict[str, object]:
    with SessionLocal() as session:
        require_owned_document(session, document_id, owner_user_id)
        return check_body_completeness(
            session,
            document_id=document_id,
            template_id=template_id,
            replace=replace,
            issue_limit=issue_limit,
        )


def get_issues_tool(
    document_id: int,
    check_scope: str = "",
    issue_type: str = "",
    severity: str = "",
    issue_limit: int = 50,
    owner_user_id: int | None = None,
) -> dict[str, object]:
    with SessionLocal() as session:
        require_owned_document(session, document_id, owner_user_id)
        query = session.query(CheckIssue).filter(CheckIssue.document_id == document_id)
        if check_scope:
            query = query.filter(CheckIssue.check_scope == check_scope)
        if issue_type:
            query = query.filter(CheckIssue.issue_type == issue_type)
        if severity:
            query = query.filter(CheckIssue.severity == severity)

        issues = sorted(query.all(), key=issue_sort_key)
        returned_issues = issues if issue_limit <= 0 else issues[:issue_limit]
        return {
            "document_id": document_id,
            "check_scope": check_scope,
            "issue_type": issue_type,
            "severity": severity,
            "issue_count": len(issues),
            "returned_issue_count": len(returned_issues),
            "issues": [issue_to_dict(issue) for issue in returned_issues],
        }


def get_document_parse_result(
    document_id: int,
    *,
    owner_user_id: int | None = None,
) -> dict[str, object]:
    with SessionLocal() as session:
        document = session.get(WordDocument, document_id)
        if not document:
            raise ValueError("Word 文档不存在")
        if owner_user_id is not None and document.owner_user_id != owner_user_id:
            raise ValueError("Word 文档不存在或不属于当前访客")
        return current_parse_result(session, document)


def require_owned_document(session, document_id: int, owner_user_id: int | None) -> WordDocument:
    document = session.get(WordDocument, document_id)
    if not document or (owner_user_id is not None and document.owner_user_id != owner_user_id):
        raise ValueError("Word 文档不存在或不属于当前访客")
    return document


def current_parse_result(session, document: WordDocument) -> dict[str, object]:
    reference_count = session.query(WordReference).filter(
        WordReference.document_id == document.id
    ).count()
    section_count = session.query(WordSection).filter(
        WordSection.document_id == document.id
    ).count()
    return parse_result_dict(
        document,
        saved_path=None,
        chunk_count=0,
        reference_count=reference_count,
        section_count=section_count,
    )


def parse_result_dict(
    document: WordDocument,
    saved_path: Path | None,
    chunk_count: int,
    reference_count: int,
    section_count: int,
) -> dict[str, object]:
    result = {
        "document_id": document.id,
        "file_name": document.file_name,
        "parse_status": document.parse_status,
        "chunk_count": chunk_count,
        "section_count": section_count,
        "reference_count": reference_count,
    }
    if saved_path:
        result["saved_path"] = str(saved_path.relative_to(BACKEND_ROOT))
    return result
