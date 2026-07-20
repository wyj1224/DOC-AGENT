import re

from sqlalchemy.orm import Session

from app.db.models import CheckIssue, WordDocument, WordSection, WordTemplate, WordTemplateHeading
from app.services.key_section_diff import (
    KEY_SECTION_TITLES,
    compare_key_sections,
    extract_key_sections,
    key_for_title,
)
from app.services.template_ingest import (
    ensure_template_key_sections,
    infer_template_type,
    infer_template_year,
    template_type_label,
)
from app.services.word_check import issue_sort_key, issue_to_dict

PLACEHOLDER_RE = re.compile(r"(?i)(x{2,}|ｘ{2,}|×{2,}|待补充|待填写|待定|todo|tbd|某某)")
KEY_SECTION_SIMILARITY_THRESHOLD = 0.95


def check_body_completeness(
    session: Session,
    document_id: int,
    template_id: int | None = None,
    replace: bool = True,
    issue_limit: int = 50,
) -> dict[str, object]:
    document = session.get(WordDocument, document_id)
    template, template_issues = resolve_template(session, document, template_id)
    sections = (
        session.query(WordSection)
        .filter(WordSection.document_id == document_id)
        .order_by(WordSection.section_index, WordSection.id)
        .all()
    )
    headings = []
    if template:
        headings = (
            session.query(WordTemplateHeading)
            .filter(WordTemplateHeading.template_id == template.id)
            .order_by(WordTemplateHeading.heading_index, WordTemplateHeading.id)
            .all()
        )

    if replace:
        session.query(CheckIssue).filter(
            CheckIssue.document_id == document_id,
            CheckIssue.check_scope == "completeness",
        ).delete()

    issues = template_issues
    key_section_results: list[dict[str, object]] = []
    if template:
        issues.extend(missing_heading_issues(document_id, headings, sections))
        key_section_results, key_section_diff_issues = key_section_comparison_issues(
            document_id,
            ensure_template_key_sections(session, template),
            sections,
        )
        issues.extend(key_section_diff_issues)
    issues.extend(empty_section_issues(document_id, sections))
    issues.extend(placeholder_text_issues(document_id, sections))

    for issue in issues:
        session.add(issue)
    session.flush()

    sorted_issues = sorted(issues, key=issue_sort_key)
    returned_issues = sorted_issues if issue_limit <= 0 else sorted_issues[:issue_limit]
    session.commit()

    return {
        "document_id": document_id,
        "template_id": template.id if template else None,
        "template_file_name": template.file_name if template else "",
        "template_year": template.template_year if template else infer_template_year(document.file_name),
        "template_type": template.template_type if template else infer_template_type(document.file_name),
        "template_type_label": template_type_label(template.template_type) if template else template_type_label(infer_template_type(document.file_name)),
        "check_scope": "completeness",
        "template_heading_count": len(headings),
        "document_section_count": len(sections),
        "key_section_results": key_section_results,
        "issue_count": len(issues),
        "returned_issue_count": len(returned_issues),
        "issues": [issue_to_dict(issue) for issue in returned_issues],
    }

def resolve_template(
    session: Session,
    document: WordDocument,
    template_id: int | None,
) -> tuple[WordTemplate | None, list[CheckIssue]]:
    if template_id:
        return session.get(WordTemplate, template_id), []

    template_type = infer_template_type(document.file_name)
    if not template_type:
        return None, [
            make_completeness_issue(
                document.id,
                "template_not_matched",
                "warning",
                "未能从待检文件名识别模板类型。",
                "文件名应能识别为 700M、室内或室外，或手动选择模板后重新检查。",
                original_text=document.file_name,
            )
        ]

    template_year = infer_template_year(document.file_name)
    if not template_year:
        years = [
            item[0]
            for item in session.query(WordTemplate.template_year)
            .filter(WordTemplate.template_type == template_type)
            .distinct()
            .all()
            if item[0]
        ]
        if len(years) == 1:
            template_year = years[0]
        else:
            return None, [
                make_completeness_issue(
                    document.id,
                    "template_year_not_matched",
                    "warning",
                    "未能从待检文件名识别模板年份，且模板库中该类型不能唯一确定年份。",
                    "请在待检文件名中保留年份。",
                    original_text=document.file_name,
                )
            ]

    templates = (
        session.query(WordTemplate)
        .filter(
            WordTemplate.template_year == template_year,
            WordTemplate.template_type == template_type,
        )
        .order_by(WordTemplate.id.desc())
        .all()
    )
    if not templates:
        return None, [
            make_completeness_issue(
                document.id,
                "template_not_matched",
                "warning",
                f"模板库中未找到 {template_year} 年 {template_type_label(template_type)} 模板。",
                "请先上传对应年份和类型的模板。",
                original_text=document.file_name,
            )
        ]
    if len(templates) > 1:
        names = "；".join(template.file_name for template in templates)
        return templates[0], [
            make_completeness_issue(
                document.id,
                "template_multiple_matched",
                "warning",
                f"模板库中匹配到多个 {template_year} 年 {template_type_label(template_type)} 模板，已使用最近上传的模板继续检查。",
                f"请清理重复模板。匹配模板：{names}",
                original_text=document.file_name,
            )
        ]
    return templates[0], []


def missing_heading_issues(
    document_id: int,
    headings: list[WordTemplateHeading],
    sections: list[WordSection],
) -> list[CheckIssue]:
    section_titles = {normalize_title(section.title) for section in sections if section.title}

    issues: list[CheckIssue] = []
    for heading in headings:
        title = normalize_title(heading.title)
        if title and title in section_titles:
            continue
        if key_for_title(heading.title):
            continue

        issues.append(
            CheckIssue(
                document_id=document_id,
                check_scope="completeness",
                issue_type="missing_section",
                severity="info",
                section_title=heading.full_title,
                paragraph_index=heading.paragraph_index,
                original_text=heading.full_title,
                reason="模板中存在该标题，但待检 Word 正文未找到对应标题，可能是按项目情况删除。",
                suggestion="这是一项完整性提醒，请确认该章节是否确实不适用；需要时再补充。",
            )
        )
    return issues


def key_section_comparison_issues(
    document_id: int,
    template_sections: list[object],
    document_sections: list[WordSection],
) -> tuple[list[dict[str, object]], list[CheckIssue]]:
    template_by_key = {item.section_key: item for item in template_sections}
    document_by_key = {
        str(item["section_key"]): item for item in extract_key_sections(document_sections)
    }
    results: list[dict[str, object]] = []
    issues: list[CheckIssue] = []

    for section_key, section_title in KEY_SECTION_TITLES.items():
        template_section = template_by_key.get(section_key)
        document_section = document_by_key.get(section_key)
        if not template_section:
            results.append({"section_key": section_key, "section_title": section_title, "status": "template_missing"})
            issues.append(
                make_completeness_issue(
                    document_id,
                    "template_key_section_missing",
                    "warning",
                    f"匹配模板中未找到关键章节“{section_title}”，无法执行正文差异检查。",
                    "请检查模板标题样式或补充该章节后重新上传模板。",
                    section_title=section_title,
                )
            )
            continue
        if not document_section:
            results.append({"section_key": section_key, "section_title": section_title, "status": "document_missing", "similarity_percent": 0.0})
            issues.append(
                make_completeness_issue(
                    document_id,
                    "key_section_missing",
                    "warning",
                    f"待检 Word 缺少关键章节“{section_title}”，与模板相似度为 0%。",
                    "请按匹配模板补充完整章节。",
                    section_title=section_title,
                    original_text=template_section.raw_text,
                    fix_data={"section_key": section_key, "similarity_percent": 0.0},
                )
            )
            continue

        comparison = compare_key_sections(template_section, document_section)
        results.append(
            {
                key: value
                for key, value in comparison.items()
                if key != "differences"
            }
            | {"status": "matched", "difference_count": len(comparison["differences"])}
        )
        similarity_percent = float(comparison["similarity_percent"])
        if similarity_percent < KEY_SECTION_SIMILARITY_THRESHOLD * 100:
            issues.append(
                make_completeness_issue(
                    document_id,
                    "key_section_similarity_low",
                    "warning",
                    f"关键章节“{section_title}”与模板的文字相似度为 {similarity_percent:.1f}%，低于 95%。",
                    "请根据下方逐项差异核对缺失或修改的内容。",
                    section_title=section_title,
                    paragraph_index=int(document_section["paragraph_index"]),
                    fix_data={"section_key": section_key, "similarity_percent": similarity_percent},
                )
            )

        for difference in list(comparison["differences"]):
            issues.append(
                difference_issue(
                    document_id,
                    section_title,
                    similarity_percent,
                    difference,
                )
            )
    return results, issues


def difference_issue(
    document_id: int,
    root_title: str,
    similarity_percent: float,
    difference: dict[str, object],
) -> CheckIssue:
    difference_type = str(difference["type"])
    issue_type = {
        "heading_no_changed": "key_section_heading_no_changed",
        "deleted": "key_section_content_missing",
        "added": "key_section_content_added",
        "modified": "key_section_content_modified",
    }[difference_type]
    template_text = str(difference.get("template_text") or "")
    document_text = str(difference.get("document_text") or "")
    location_title = str(difference.get("section_title") or root_title)
    if difference_type == "heading_no_changed":
        detail = f"子章节“{location_title}”编号与模板不同：模板为 {template_text}，待检 Word 为 {document_text}。"
        suggestion = "请确认子章节编号和层级是否应与模板保持一致。"
    elif difference_type == "deleted":
        detail = "待检 Word 缺少一处模板内容。"
        suggestion = "请确认该内容是否可以删除；如仍适用，请按模板补充。"
    elif difference_type == "added":
        detail = "待检 Word 比模板新增一处内容。"
        suggestion = "请确认新增内容是否符合当前项目要求。"
    else:
        detail = "待检 Word 有一处内容与模板不同。"
        suggestion = "请核对该修改是否为当前项目的必要调整。"
    original_text = f"模板：{template_text or '（无）'}\n待检 Word：{document_text or '（无）'}"
    return make_completeness_issue(
        document_id,
        issue_type,
        "info",
        f"{detail} 本章文字相似度为 {similarity_percent:.1f}%。",
        suggestion,
        section_title=f"{root_title} / {location_title}" if location_title != root_title else root_title,
        paragraph_index=int(difference.get("paragraph_index") or 0),
        original_text=original_text,
        fix_data={
            "similarity_percent": similarity_percent,
            "difference_type": difference_type,
            "template_text": template_text,
            "document_text": document_text,
        },
    )


def empty_section_issues(document_id: int, sections: list[WordSection]) -> list[CheckIssue]:
    issues: list[CheckIssue] = []
    for index, section in enumerate(sections):
        if has_child_section(index, sections):
            continue
        if is_optional_empty_section(section):
            continue
        if has_meaningful_body(section.body_text):
            continue
        issues.append(
            make_completeness_issue(
                document_id,
                "empty_section_body",
                "warning",
                "正文存在该标题，但该标题下未发现有效正文内容。",
                "请补充该标题下的正文内容，或确认该标题是否可以为空。",
                section_title=section.section_path or section.full_title,
                paragraph_index=section.paragraph_start,
                original_text=section.full_title,
            )
        )
    return issues


def placeholder_text_issues(document_id: int, sections: list[WordSection]) -> list[CheckIssue]:
    issues: list[CheckIssue] = []
    for section in sections:
        body_text = section.body_text or ""
        placeholder_matches = list(PLACEHOLDER_RE.finditer(body_text))
        if not placeholder_matches:
            continue
        matches = list(dict.fromkeys(match.group(0) for match in placeholder_matches))
        issues.append(
            make_completeness_issue(
                document_id,
                "placeholder_text_found",
                "warning",
                f"正文存在占位符：{'、'.join(matches[:5])}",
                "请将占位符替换为正式内容。",
                section_title=section.section_path or section.full_title,
                paragraph_index=section.paragraph_start,
                original_text=placeholder_context(body_text, placeholder_matches[0]),
            )
        )
    return issues


def placeholder_context(text: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - 120)
    end = min(len(text), match.end() + 180)
    prefix = "..." if start else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def has_child_section(index: int, sections: list[WordSection]) -> bool:
    current = sections[index]
    for later in sections[index + 1 :]:
        if later.level <= current.level:
            return False
        if later.level > current.level:
            return True
    return False


def has_meaningful_body(value: str) -> bool:
    text = re.sub(r"[\s　,，。；;：:、.．…·\-—_（）()【】\[\]<>《》“”\"'‘’/\\|]+", "", value or "")
    return bool(text)


def is_optional_empty_section(section: WordSection) -> bool:
    text = f"{section.full_title} {section.title}"
    return "若无" in text or "无则删除" in text or "删除本节" in text


def make_completeness_issue(
    document_id: int,
    issue_type: str,
    severity: str,
    reason: str,
    suggestion: str,
    section_title: str = "",
    paragraph_index: int = 0,
    original_text: str = "",
    fix_data: dict[str, object] | None = None,
) -> CheckIssue:
    return CheckIssue(
        document_id=document_id,
        check_scope="completeness",
        issue_type=issue_type,
        severity=severity,
        section_title=section_title,
        paragraph_index=paragraph_index,
        original_text=original_text,
        reason=reason,
        suggestion=suggestion,
        fix_data=fix_data or {},
    )


def normalize_no(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def normalize_title(value: str) -> str:
    text = value or ""
    text = re.sub(r"^[一二三四五六七八九十]+[、.．]\s*", "", text)
    text = re.sub(r"^\d+(?:\.\d+)*\s*", "", text)
    text = re.sub(r"[，,。；;：《》“”（）()【】\[\]\s　]", "", text)
    return text.lower()
