from datetime import date

from app.db.database import SessionLocal
from app.db.models import CheckIssue, MandatoryClause, StandardValidityRecord
from app.excel_loader import load_clause_chunks, load_standard_validity_records


def parse_date(value: str):
    if not value:
        return None
    return date.fromisoformat(value)


def ingest_excel_to_postgres(xlsx_path: str, *, sheet: str = "强条", replace: bool = True) -> dict[str, object]:
    chunks = load_clause_chunks(xlsx_path, sheet_name=sheet)
    standard_records = load_standard_validity_records(xlsx_path)

    with SessionLocal() as session:
        if replace:
            session.query(CheckIssue).delete()
            session.query(MandatoryClause).delete()
            session.query(StandardValidityRecord).delete()

        for chunk in chunks:
            metadata = chunk.metadata
            session.add(
                MandatoryClause(
                    standard_no=metadata.get("standard_no", ""),
                    standard_name=metadata.get("standard_name", ""),
                    category=metadata.get("category", ""),
                    applicable_scope=metadata.get("applicable_scope", ""),
                    mandatory_count=metadata.get("mandatory_count", ""),
                    mandatory_type=metadata.get("mandatory_type", "条文"),
                    clause_no=metadata.get("clause_no", ""),
                    clause_text=metadata.get("clause_text", ""),
                    chunk_text=chunk.text,
                    source_file=chunk.source_file,
                    sheet_name=metadata.get("sheet_name", ""),
                    row_index=int(metadata.get("row_index") or 0),
                )
            )

        for record in standard_records:
            data = record.as_dict()
            session.add(
                StandardValidityRecord(
                    old_standard_text=data["old_standard_text"],
                    new_standard_text=data["new_standard_text"],
                    new_publish_date=parse_date(data["new_publish_date"]),
                    new_effective_date=parse_date(data["new_effective_date"]),
                    involved_content=data["involved_content"],
                    verified_date=parse_date(data["verified_date"]),
                    note=data["note"],
                    source_url=data["source_url"],
                    source_file=data["source_file"],
                    sheet_name=data["sheet_name"],
                    row_index=data["row_index"],
                )
            )

        session.commit()

    return {
        "excel_item_count": len(chunks),
        "clause_chunk_count": sum(1 for chunk in chunks if chunk.metadata.get("mandatory_type") != "标准依据"),
        "standard_only_count": sum(1 for chunk in chunks if chunk.metadata.get("mandatory_type") == "标准依据"),
        "standard_validity_count": len(standard_records),
        "row_summary": build_row_summary(chunks),
        "mandatory_clauses": [
            {
                "chunk_index": chunk.chunk_index,
                "row_index": chunk.metadata.get("row_index", 0),
                "standard_no": chunk.metadata.get("standard_no", ""),
                "standard_name": chunk.metadata.get("standard_name", ""),
                "category": chunk.metadata.get("category", ""),
                "applicable_scope": chunk.metadata.get("applicable_scope", ""),
                "mandatory_type": chunk.metadata.get("mandatory_type", ""),
                "clause_no": chunk.metadata.get("clause_no", ""),
                "clause_text": chunk.metadata.get("clause_text", ""),
                "chunk_text": chunk.text,
            }
            for chunk in chunks
        ],
        "standard_validity_records": [
            record.as_dict()
            for record in standard_records
        ],
    }


def build_row_summary(chunks) -> list[dict[str, object]]:
    rows: dict[int, dict[str, object]] = {}
    for chunk in chunks:
        row_index = int(chunk.metadata.get("row_index") or 0)
        if row_index not in rows:
            rows[row_index] = {
                "row_index": row_index,
                "standard_no": chunk.metadata.get("standard_no", ""),
                "standard_name": chunk.metadata.get("standard_name", ""),
                "generated_chunk_count": 0,
                "clause_nos": [],
                "mandatory_types": [],
            }
        rows[row_index]["generated_chunk_count"] += 1
        rows[row_index]["clause_nos"].append(chunk.metadata.get("clause_no", ""))
        rows[row_index]["mandatory_types"].append(chunk.metadata.get("mandatory_type", ""))

    for row in rows.values():
        row["clause_nos"] = list(dict.fromkeys(value for value in row["clause_nos"] if value))
        row["mandatory_types"] = list(dict.fromkeys(value for value in row["mandatory_types"] if value))
    return list(rows.values())
