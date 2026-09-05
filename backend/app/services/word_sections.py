import re

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.word_loader import heading_level, table_to_text


NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,5})[\s　]+(.{1,120})$")
LIST_ITEM_RE = re.compile(r"^\d+[\.．、)]\s*")
STANDARD_NO_RE = re.compile(r"\b(?:GB/T|GB|YD/T|YD|JGJ/T|JGJ)\s*-?\s*\d+", re.IGNORECASE)
CLAUSE_SENTENCE_RE = re.compile(r"第\s*\d+(?:\.\d+)*\s*条")


def extract_word_sections(file_path: str) -> list[dict[str, object]]:
    document = Document(file_path)
    sections: list[dict[str, object]] = []
    stack: list[str] = []
    current: dict[str, object] | None = None
    body: list[str] = []

    def close_section(paragraph_end: int) -> None:
        nonlocal current, body
        if not current:
            return
        body_text = "\n".join(body).strip()
        current["paragraph_end"] = paragraph_end
        current["body_text"] = body_text
        current["body_length"] = len(body_text)
        sections.append(current)
        current = None
        body = []

    paragraph_index = -1
    for block in iter_blocks(document):
        if isinstance(block, Paragraph):
            paragraph_index += 1
            text = block.text.strip()
            if not text:
                continue

            style_name = getattr(getattr(block, "style", None), "name", "") or ""
            if style_name.lower().startswith("toc"):
                continue

            level, heading_no, title = parse_heading(block, text)
            if level:
                close_section(paragraph_index - 1)
                stack = stack[: level - 1]
                stack.append(title)
                current = {
                    "section_index": len(sections),
                    "paragraph_start": paragraph_index,
                    "paragraph_end": paragraph_index,
                    "level": level,
                    "heading_no": heading_no,
                    "title": title,
                    "full_title": text,
                    "section_path": " / ".join(stack),
                    "body_text": "",
                    "body_length": 0,
                }
                continue

            if current:
                body.append(text)
            continue

        if current:
            text = table_to_text(block)
            if not text:
                continue
            body.append(text)

    close_section(len(document.paragraphs) - 1)
    return sections


def iter_blocks(document: Document):
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def parse_heading(paragraph, text: str) -> tuple[int, str, str]:
    style_level = heading_level(paragraph)
    level = style_level
    heading_no = ""
    title = text

    match = NUMBERED_HEADING_RE.match(text)
    if match:
        heading_no = match.group(1)
        title = match.group(2).strip()
        level = level or heading_no.count(".") + 1

    if not level or not is_real_heading_text(text, title, bool(match), bool(style_level)):
        return 0, "", text
    return level, heading_no, title


def is_real_heading_text(
    text: str, title: str, is_numbered_heading: bool, has_heading_style: bool
) -> bool:
    if LIST_ITEM_RE.match(text) and not is_numbered_heading:
        return False
    if looks_like_body_sentence(text):
        return False
    if is_numbered_heading:
        return not looks_like_body_sentence(title)
    return has_heading_style


def looks_like_body_sentence(text: str) -> bool:
    value = text.strip()
    if value.endswith(("。", "；", ";")):
        return True
    if CLAUSE_SENTENCE_RE.search(value):
        return True
    if STANDARD_NO_RE.search(value) and len(value) > 25:
        return True
    return value.startswith(("根据", "依据", "按照")) and len(value) > 20
