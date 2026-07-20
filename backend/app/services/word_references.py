import re

from app.schemas import TextChunk
from app.services.section_scope import is_basis_section_title


STANDARD_NO_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:GB/T|GB|YD/T|YD/|YD|JGJ/T|JGJ|CECS|HJ/T|QB-A|QB-J|MH|JJ|B)\s*-?\s*\d+(?:\.\d+)*(?:\s*[-－]\s*\d{3,4})?(?:（\d{4}）)?"
)
STANDARD_NAME_RE = re.compile(r"《([^》]{2,80})》")
CLAUSE_NO_RE = re.compile(r"(?:第\s*)?(\d+(?:\.\d+){1,4}(?:[-－]\d+)?)(?:\s*条)?")
DOCUMENT_NO_RE = re.compile(
    r"(?:工信部[\u4e00-\u9fa5]*[\[〔]\d{4}[\]〕]\s*\d+\s*号|工信部令第\d+\s*号|计通[\[〔]\d{4}[\]〕]\s*\d+\s*号|川移计[^\s“”《》；。]*[\[〔]\d{4}[\]〕]\s*\d+\s*号|国地面\s*（\d{4}）\s*\d+)"
)


def extract_references(chunks: list[TextChunk]) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    for chunk in chunks:
        text = chunk.text
        section_title = str(chunk.metadata.get("section_title", "")) or extract_section_title(text)
        is_design_basis = is_basis_section_title(section_title)
        items = extract_reference_items(text, is_design_basis=is_design_basis)
        if not items and is_design_basis and text.strip():
            items = [{"standard_no": "", "standard_name": text.strip(), "standard_no_span": None, "standard_name_span": None}]

        for item in items:
            if not is_design_basis and not item["standard_name"] and not item["standard_no"]:
                continue
            locator = dict(chunk.metadata.get("locator") or {})
            locator["chunk_index"] = chunk.chunk_index
            if item.get("standard_no_span"):
                locator["standard_no"] = item["standard_no_span"]
            if item.get("standard_name_span"):
                locator["standard_name"] = item["standard_name_span"]
            paragraph_index = (
                int(locator["paragraph_index"])
                if locator.get("container") == "body_paragraph"
                else chunk.chunk_index
            )
            references.append(
                {
                    "section_title": section_title,
                    "paragraph_index": paragraph_index,
                    "standard_no": item["standard_no"],
                    "standard_name": item["standard_name"],
                    "clause_no": extract_clause_no(text, item["standard_no"]),
                    "quoted_text": text[:500],
                    "context": text,
                    "locator": locator,
                }
            )
    return references


def extract_reference_items(text: str, *, is_design_basis: bool) -> list[dict[str, object]]:
    code_matches = extract_code_matches(text)
    name_matches = extract_name_matches(text, is_design_basis=is_design_basis)
    paired_name_codes, used_code_indexes = pair_codes_with_names(text, code_matches, name_matches)

    items: list[dict[str, object]] = []
    for name_index, name in enumerate(name_matches):
        code_index = paired_name_codes.get(name_index)
        code = code_matches[code_index] if code_index is not None else None
        items.append(
            {
                "standard_no": str(code["value"]) if code else "",
                "standard_name": str(name["value"]),
                "standard_no_span": span_from_match(code) if code else None,
                "standard_name_span": span_from_match(name),
            }
        )
    for index, code in enumerate(code_matches):
        if index not in used_code_indexes:
            items.append(
                {
                    "standard_no": str(code["value"]),
                    "standard_name": "",
                    "standard_no_span": span_from_match(code),
                    "standard_name_span": None,
                }
            )

    return dedupe_reference_items(items)


def pair_codes_with_names(
    text: str,
    code_matches: list[dict[str, object]],
    name_matches: list[dict[str, object]],
) -> tuple[dict[int, int], set[int]]:
    paired_name_codes: dict[int, int] = {}
    used_code_indexes: set[int] = set()

    for code_index, code in enumerate(code_matches):
        name_index = previous_name_index(int(code["start"]), name_matches)
        if name_index is None or name_index in paired_name_codes:
            continue
        name = name_matches[name_index]
        separator = text[int(name.get("outer_end", name["end"])):int(code["start"])]
        if is_parenthesized_code_separator(separator):
            paired_name_codes[name_index] = code_index
            used_code_indexes.add(code_index)

    for code_index, code in enumerate(code_matches):
        if code_index in used_code_indexes:
            continue
        name_index = next_name_index(int(code["end"]), name_matches)
        if name_index is None or name_index in paired_name_codes:
            continue
        name = name_matches[name_index]
        separator = text[int(code["end"]):int(name.get("outer_start", name["start"]))]
        if is_code_before_name_separator(separator):
            paired_name_codes[name_index] = code_index
            used_code_indexes.add(code_index)

    for code_index, code in enumerate(code_matches):
        if code_index in used_code_indexes:
            continue
        name_index = previous_name_index(int(code["start"]), name_matches)
        if name_index is None or name_index in paired_name_codes:
            continue
        name = name_matches[name_index]
        separator = text[int(name.get("outer_end", name["end"])):int(code["start"])]
        if is_loose_name_before_code_separator(separator):
            paired_name_codes[name_index] = code_index
            used_code_indexes.add(code_index)

    return paired_name_codes, used_code_indexes


def previous_name_index(position: int, name_matches: list[dict[str, object]]) -> int | None:
    previous_indexes = [
        index
        for index, name in enumerate(name_matches)
        if int(name.get("outer_end", name["end"])) <= position
    ]
    return previous_indexes[-1] if previous_indexes else None


def next_name_index(position: int, name_matches: list[dict[str, object]]) -> int | None:
    for index, name in enumerate(name_matches):
        if int(name.get("outer_start", name["start"])) >= position:
            return index
    return None


def is_parenthesized_code_separator(separator: str) -> bool:
    return bool(re.fullmatch(r"[\s（(【\[]*", separator or ""))


def is_code_before_name_separator(separator: str) -> bool:
    return len(separator) <= 8 and bool(re.fullmatch(r"[\s,，、;；:：\"“”'‘’（()）【】\[\]]*", separator or ""))


def is_loose_name_before_code_separator(separator: str) -> bool:
    return 0 < len(separator) <= 6 and bool(re.fullmatch(r"[\s()（）【】\[\]]+", separator))


def extract_code_matches(text: str) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    for pattern in (STANDARD_NO_RE, DOCUMENT_NO_RE):
        for match in pattern.finditer(text):
            value = normalize_standard_no(match.group(0))
            if value and not overlaps_existing(match.start(), match.end(), matches):
                matches.append(
                    {
                        "value": value,
                        "text": match.group(0),
                        "start": match.start(),
                        "end": match.end(),
                    }
                )
    return sorted(matches, key=lambda item: int(item["start"]))


def extract_name_matches(text: str, *, is_design_basis: bool) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    for match in STANDARD_NAME_RE.finditer(text):
        raw_value = match.group(1)
        value = raw_value.strip()
        if is_design_basis or looks_like_standard_name(value):
            leading_space = len(raw_value) - len(raw_value.lstrip())
            trailing_space = len(raw_value) - len(raw_value.rstrip())
            matches.append(
                {
                    "value": value,
                    "text": value,
                    "start": match.start(1) + leading_space,
                    "end": match.end(1) - trailing_space,
                    "outer_start": match.start(),
                    "outer_end": match.end(),
                }
            )
    return matches


def nearest_code_index(
    start: int,
    end: int,
    code_matches: list[dict[str, object]],
    used_indexes: set[int],
    max_distance: int = 80,
) -> int | None:
    best_index: int | None = None
    best_distance = max_distance + 1
    for index, code in enumerate(code_matches):
        if index in used_indexes:
            continue
        code_start = int(code["start"])
        code_end = int(code["end"])
        if code_end <= start:
            distance = start - code_end
        elif code_start >= end:
            distance = code_start - end
        else:
            distance = 0
        if distance <= max_distance and distance < best_distance:
            best_index = index
            best_distance = distance
    return best_index


def dedupe_reference_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for item in items:
        number_span = item.get("standard_no_span") or {}
        name_span = item.get("standard_name_span") or {}
        key = (
            item["standard_no"],
            item["standard_name"],
            number_span.get("start"),
            name_span.get("start"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def span_from_match(match: dict[str, object]) -> dict[str, object]:
    return {
        "start": int(match["start"]),
        "end": int(match["end"]),
        "text": str(match.get("text") or ""),
    }


def overlaps_existing(start: int, end: int, matches: list[dict[str, object]]) -> bool:
    return any(start < int(item["end"]) and end > int(item["start"]) for item in matches)


def extract_clause_no(text: str, standard_no: str) -> str:
    text_without_refs = text
    if standard_no:
        text_without_refs = text_without_refs.replace(standard_no, "")
    clause_nos = [match.group(1) for match in CLAUSE_NO_RE.finditer(text_without_refs)]
    return "；".join(dict.fromkeys(clause_nos))


def normalize_standard_no(value: str) -> str:
    text = re.sub(r"\s+", " ", value.replace("－", "-")).strip()
    return re.sub(r"\s*-\s*", "-", text)


def looks_like_standard_name(value: str) -> bool:
    return any(keyword in value for keyword in ("标准", "规范", "规程", "规定", "要求", "导则", "图集", "办法", "限值", "批复", "通知", "意见"))


def extract_section_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""
