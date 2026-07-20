import re
import math
from pathlib import Path

from .schemas import TextChunk


CLAUSE_START_RE = re.compile(r"(?P<clause_no>\d+(?:\.\d+){2,4})(?=\s|[\u4e00-\u9fff]|$)")


def split_clause_text(clause_text: str) -> list[tuple[str, str]]:
    """Split a cell containing many mandatory clauses into clause-level chunks."""
    text = normalize_text(clause_text)
    if not text:
        return []

    matches = list(CLAUSE_START_RE.finditer(text))
    if not matches:
        return [("", text)]

    parts: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        clause_no = match.group("clause_no")
        clause_body = text[start:end].strip()
        parts.append((clause_no, clause_body))
    return parts


def excel_row_to_clause_chunks(
    row: dict[str, object],
    *,
    source_file: str,
    sheet_name: str,
    row_index: int,
    start_chunk_index: int,
) -> list[TextChunk]:
    standard_no = value_to_text(row.get("标准号"))
    standard_name = value_to_text(row.get("标准名"))
    category = value_to_text(row.get("分类"))
    applicable_scope = value_to_text(row.get("适用范围"))
    mandatory_count = value_to_text(row.get("强制性条文数量"))
    clause_text = value_to_text(row.get("强制性条文内容"))
    mandatory_type = "全文" if mandatory_count == "全文" else "条文"

    if mandatory_type == "全文" and not clause_text:
        clause_text = "全文为强制性内容。"

    chunks: list[TextChunk] = []
    if mandatory_type == "全文":
        clause_parts = [("全文", clause_text)]
    elif clause_text:
        clause_parts = split_clause_text(clause_text)
    elif standard_no or standard_name:
        mandatory_type = "标准依据"
        clause_parts = [("", "")]
    else:
        clause_parts = []

    for offset, (clause_no, text) in enumerate(clause_parts):
        chunk_text = "\n".join(
            part
            for part in [
                f"标准号：{standard_no}" if standard_no else "",
                f"标准名：{standard_name}" if standard_name else "",
                f"分类：{category}" if category else "",
                f"适用范围：{applicable_scope}" if applicable_scope else "",
                f"强制类型：{mandatory_type}" if mandatory_type else "",
                f"条号：{clause_no}" if clause_no else "",
                f"条文：{text}" if text else "",
            ]
            if part
        )
        chunks.append(
            TextChunk(
                text=chunk_text,
                source_type="excel_clause",
                source_file=Path(source_file).name,
                chunk_index=start_chunk_index + offset,
                metadata={
                    "standard_no": standard_no,
                    "standard_name": standard_name,
                    "category": category,
                    "applicable_scope": applicable_scope,
                    "mandatory_count": mandatory_count,
                    "mandatory_type": mandatory_type,
                    "clause_no": clause_no,
                    "clause_text": text,
                    "sheet_name": sheet_name,
                    "row_index": row_index,
                },
            )
        )
    return chunks


def chunk_markdown(text: str, *, source_file: str, max_chars: int = 700) -> list[TextChunk]:
    """Chunk markdown/text while keeping markdown tables together."""
    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    table: list[str] = []

    def flush_current() -> None:
        nonlocal current, current_len
        if current:
            chunks.append("\n".join(current).strip())
            current = []
            current_len = 0

    def flush_table() -> None:
        nonlocal table
        if table:
            flush_current()
            chunks.append("\n".join(table).strip())
            table = []

    for line in lines:
        is_table_line = "|" in line and line.strip().startswith("|")
        if is_table_line:
            table.append(line)
            continue
        if table:
            flush_table()

        line_len = len(line)
        if current and current_len + line_len > max_chars:
            flush_current()
        current.append(line)
        current_len += line_len + 1

    flush_table()
    flush_current()

    return [
        TextChunk(
            text=chunk,
            source_type="markdown_text",
            source_file=Path(source_file).name,
            chunk_index=i,
            metadata={},
        )
        for i, chunk in enumerate(chunks)
        if chunk
    ]


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", value_to_text(value)).strip()


def value_to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "nat"}:
        return ""
    return text
