from pathlib import Path
from weakref import WeakKeyDictionary

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from .schemas import TextChunk


def parse_docx_file(file_path: str) -> list[TextChunk]:
    path = Path(file_path)
    document = Document(str(path))
    chunks: list[TextChunk] = []
    section_stack: list[str] = []
    body_paragraph_index = 0
    table_index = 0

    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            paragraph = Paragraph(child, document)
            text = paragraph.text
            locator = {"container": "body_paragraph", "paragraph_index": body_paragraph_index}
            body_paragraph_index += 1

            if not text.strip():
                continue
            level = heading_level(paragraph)
            if level:
                section_stack = section_stack[: level - 1]
                section_stack.append(text.strip())
                continue
            chunks.append(make_chunk(path.name, chunks, text, "word_docx", section_stack, locator))
            continue

        if isinstance(child, CT_Tbl):
            table = Table(child, document)
            append_table_chunks(path.name, chunks, table, table_index, section_stack)
            table_index += 1

    return chunks


# python-docx resolves paragraph.style by scanning every style in the document,
# which made parsing O(paragraphs x styles). Build the id -> name map once per document.
_style_names: "WeakKeyDictionary[object, dict[str | None, str]]" = WeakKeyDictionary()


def paragraph_style_name(paragraph) -> str:
    """Same result as ``paragraph.style.name``, without the per-call style scan."""
    part = paragraph.part
    names = _style_names.get(part)
    if names is None:
        styles = part.styles
        names = {
            style.style_id: style.name or ""
            for style in styles
            if style.type == WD_STYLE_TYPE.PARAGRAPH
        }
        default = styles.default(WD_STYLE_TYPE.PARAGRAPH)
        names[None] = default.name or "" if default is not None else ""
        _style_names[part] = names
    # Unknown ids fall back to the default style, like python-docx does.
    return names.get(paragraph._p.style, names[None])


def heading_level(paragraph) -> int:
    style_name = paragraph_style_name(paragraph)
    for prefix in ("Heading ", "标题 "):
        if style_name.startswith(prefix):
            tail = style_name.removeprefix(prefix).strip()
            return int(tail) if tail.isdigit() else 0
    return 0


def append_table_chunks(
    source_file: str,
    chunks: list[TextChunk],
    table: Table,
    table_index: int,
    section_stack: list[str],
) -> None:
    # Merged cells repeat the same <w:tc>. Keep the elements themselves: id() of a
    # freed lxml proxy can be reused by another cell, which randomly dropped cells.
    seen_cells: set = set()
    for row_index, row in enumerate(table.rows):
        for cell_index, cell in enumerate(row.cells):
            if cell._tc in seen_cells:
                continue
            seen_cells.add(cell._tc)
            for paragraph_index, paragraph in enumerate(cell.paragraphs):
                text = paragraph.text
                if not text.strip():
                    continue
                locator = {
                    "container": "table_cell_paragraph",
                    "table_index": table_index,
                    "row_index": row_index,
                    "cell_index": cell_index,
                    "paragraph_index": paragraph_index,
                }
                chunks.append(make_chunk(source_file, chunks, text, "word_docx_table", section_stack, locator))


def table_to_text(table) -> str:
    rows: list[str] = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows).strip()


def make_chunk(
    source_file: str,
    chunks: list[TextChunk],
    text: str,
    source_type: str,
    section_stack: list[str],
    locator: dict[str, object] | None = None,
) -> TextChunk:
    return TextChunk(
        text=text,
        source_type=source_type,
        source_file=source_file,
        chunk_index=len(chunks),
        metadata={"section_title": " / ".join(section_stack), "locator": locator or {}},
    )
