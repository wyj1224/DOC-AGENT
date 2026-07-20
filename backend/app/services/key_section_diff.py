from difflib import SequenceMatcher
import re
import unicodedata


KEY_SECTION_TITLES = {
    "safety_production": "安全生产要求",
    "project_acceptance": "工程验收",
    "emc_environment": "电磁防护与环境保护",
}

KEY_SECTION_ALIASES = {
    "safety_production": ("安全生产要求",),
    "project_acceptance": ("工程验收",),
    "emc_environment": ("电磁防护与环境保护", "电磁防护和环境保护"),
}


def extract_key_sections(sections: list[object]) -> list[dict[str, object]]:
    """Extract the three configured heading subtrees, including child heading numbers."""
    roots: dict[str, int] = {}
    for index, section in enumerate(sections):
        key = key_for_title(str(value(section, "title") or ""))
        if key and key not in roots:
            roots[key] = index

    results: list[dict[str, object]] = []
    for section_key in KEY_SECTION_TITLES:
        root_index = roots.get(section_key)
        if root_index is None:
            continue
        root = sections[root_index]
        root_level = int(value(root, "level") or 1)
        subtree = [root]
        for section in sections[root_index + 1 :]:
            if int(value(section, "level") or 1) <= root_level:
                break
            subtree.append(section)
        results.append(build_section_record(section_key, subtree))
    return results


def build_section_record(section_key: str, sections: list[object]) -> dict[str, object]:
    root = sections[0]
    root_level = int(value(root, "level") or 1)
    counters: list[int] = []
    blocks: list[dict[str, object]] = []

    for section_offset, section in enumerate(sections):
        level = int(value(section, "level") or root_level)
        relative_no = ""
        if section_offset:
            relative_level = max(1, level - root_level)
            while len(counters) < relative_level:
                counters.append(0)
            counters = counters[:relative_level]
            counters[-1] += 1
            relative_no = ".".join(str(item) for item in counters)

        explicit_no = str(value(section, "heading_no") or "").strip()
        display_no = explicit_no or relative_no
        paragraph_start = int(value(section, "paragraph_start") or 0)
        paragraph_end = int(value(section, "paragraph_end") or paragraph_start)
        title = str(value(section, "title") or "").strip()
        full_title = str(value(section, "full_title") or title).strip()
        blocks.append(
            {
                "kind": "heading",
                "text": title,
                "raw_text": full_title,
                "normalized_text": normalize_text(title),
                "heading_no": display_no,
                "explicit_heading_no": explicit_no,
                "relative_heading_no": relative_no,
                "level": level,
                "section_title": full_title,
                "paragraph_index": paragraph_start,
            }
        )

        body_lines = [line.strip() for line in str(value(section, "body_text") or "").splitlines() if line.strip()]
        for line_index, line in enumerate(body_lines):
            blocks.append(
                {
                    "kind": "body",
                    "text": line,
                    "raw_text": line,
                    "normalized_text": normalize_text(line),
                    "heading_no": display_no,
                    "level": level,
                    "section_title": full_title,
                    "paragraph_index": min(paragraph_end, paragraph_start + line_index + 1),
                }
            )

    raw_text = "\n".join(block_display_text(block) for block in blocks)
    normalized_text = "\n".join(block_comparison_text(block) for block in blocks)
    return {
        "section_key": section_key,
        "section_title": KEY_SECTION_TITLES[section_key],
        "paragraph_index": int(value(root, "paragraph_start") or 0),
        "raw_text": raw_text,
        "normalized_text": normalized_text,
        "blocks": blocks,
    }


def compare_key_sections(
    template_section: object,
    document_section: object,
) -> dict[str, object]:
    template_blocks = list(value(template_section, "blocks") or [])
    document_blocks = list(value(document_section, "blocks") or [])
    template_text = str(value(template_section, "normalized_text") or "")
    document_text = str(value(document_section, "normalized_text") or "")
    similarity = text_similarity(template_text, document_text)

    differences = heading_number_differences(template_blocks, document_blocks)
    differences.extend(content_differences(template_blocks, document_blocks))
    return {
        "section_key": str(value(template_section, "section_key") or ""),
        "section_title": str(value(template_section, "section_title") or ""),
        "similarity": similarity,
        "similarity_percent": round(similarity * 100, 1),
        "differences": differences,
    }


def heading_number_differences(
    template_blocks: list[dict[str, object]],
    document_blocks: list[dict[str, object]],
) -> list[dict[str, object]]:
    template_headings = indexed_headings(template_blocks)
    document_headings = indexed_headings(document_blocks)
    differences: list[dict[str, object]] = []
    for heading_key in template_headings.keys() & document_headings.keys():
        template = template_headings[heading_key]
        document = document_headings[heading_key]
        before = str(template.get("heading_no") or "")
        after = str(document.get("heading_no") or "")
        if before == after or not (before or after):
            continue
        differences.append(
            make_difference(
                "heading_no_changed",
                template,
                document,
                template_text=before or "（无编号）",
                document_text=after or "（无编号）",
            )
        )
    return differences


def indexed_headings(blocks: list[dict[str, object]]) -> dict[tuple[str, int], dict[str, object]]:
    counts: dict[str, int] = {}
    indexed: dict[tuple[str, int], dict[str, object]] = {}
    for block in blocks[1:]:  # 大章节本身不参与“小章节编号”比较
        if block.get("kind") != "heading":
            continue
        title = normalize_title(str(block.get("text") or ""))
        counts[title] = counts.get(title, 0) + 1
        indexed[(title, counts[title])] = block
    return indexed


def content_differences(
    template_blocks: list[dict[str, object]],
    document_blocks: list[dict[str, object]],
) -> list[dict[str, object]]:
    left = [content_key(block) for block in template_blocks]
    right = [content_key(block) for block in document_blocks]
    matcher = SequenceMatcher(None, left, right, autojunk=False)
    differences: list[dict[str, object]] = []
    for operation, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        left_slice = template_blocks[left_start:left_end]
        right_slice = document_blocks[right_start:right_end]
        if operation == "delete":
            differences.extend(make_difference("deleted", block, None) for block in left_slice)
            continue
        if operation == "insert":
            differences.extend(make_difference("added", None, block) for block in right_slice)
            continue

        paired_count = min(len(left_slice), len(right_slice))
        for index in range(paired_count):
            differences.append(make_difference("modified", left_slice[index], right_slice[index]))
        differences.extend(make_difference("deleted", block, None) for block in left_slice[paired_count:])
        differences.extend(make_difference("added", None, block) for block in right_slice[paired_count:])
    return differences


def make_difference(
    difference_type: str,
    template_block: dict[str, object] | None,
    document_block: dict[str, object] | None,
    *,
    template_text: str | None = None,
    document_text: str | None = None,
) -> dict[str, object]:
    location = document_block or template_block or {}
    return {
        "type": difference_type,
        "kind": str(location.get("kind") or "body"),
        "section_title": str(location.get("section_title") or ""),
        "paragraph_index": int(location.get("paragraph_index") or 0),
        "template_text": template_text if template_text is not None else str((template_block or {}).get("raw_text") or ""),
        "document_text": document_text if document_text is not None else str((document_block or {}).get("raw_text") or ""),
    }


def text_similarity(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def content_key(block: dict[str, object]) -> str:
    if block.get("kind") == "heading":
        return f"heading:{normalize_title(str(block.get('text') or ''))}"
    return f"body:{str(block.get('normalized_text') or '')}"


def block_display_text(block: dict[str, object]) -> str:
    text = str(block.get("raw_text") or "")
    heading_no = str(block.get("heading_no") or "")
    if block.get("kind") == "heading" and heading_no and not text.startswith(heading_no):
        return f"{heading_no} {text}"
    return text


def block_comparison_text(block: dict[str, object]) -> str:
    text = str(block.get("normalized_text") or "")
    heading_no = str(block.get("heading_no") or "")
    return f"{heading_no} {text}".strip() if block.get("kind") == "heading" else text


def key_for_title(title: str) -> str:
    normalized = normalize_title(title)
    for key, aliases in KEY_SECTION_ALIASES.items():
        if normalized in {normalize_title(alias) for alias in aliases}:
            return key
    return ""


def normalize_title(value_: str) -> str:
    text = normalize_text(value_)
    text = re.sub(r"^\d+(?:\.\d+)*\s*", "", text)
    text = re.sub(r"[，,。；;：《》“”（）()【】\[\]\s　]", "", text)
    return text.lower()


def normalize_text(value_: str) -> str:
    text = unicodedata.normalize("NFKC", value_ or "")
    return re.sub(r"\s+", " ", text).strip()


def value(item: object, name: str):
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)
