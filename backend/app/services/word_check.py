import re
from datetime import date

from sqlalchemy.orm import Session

from app.db.models import CheckIssue, MandatoryClause, StandardValidityRecord, WordDocument, WordReference
from app.services.section_scope import basis_section_label, is_basis_section_title


STANDARD_NO_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:GB/T|GB|YD/T|YD/|YD|JGJ/T|JGJ|CECS|HJ/T|QB-A|QB-J|MH|JJ|B)\s*-?\s*\d+(?:\.\d+)*(?:\s*[-－]\s*\d{3,4})?(?:（\d{4}）)?"
)
DOCUMENT_NO_RE = re.compile(
    r"(?:工信部[\u4e00-\u9fa5]*[\[〔]\d{4}[\]〕]\s*\d+\s*号|工信部令第\d+\s*号|计通[\[〔]\d{4}[\]〕]\s*\d+\s*号|川移计[^\s“”《》；。]*[\[〔]\d{4}[\]〕]\s*\d+\s*号|国地面\s*（\d{4}）\s*\d+)"
)
STANDARD_NAME_RE = re.compile(r"《([^》]{2,120})》")


ISSUE_ORDER = {
    "standard_replaced": 1,
    "standard_name_mismatch": 2,
    "standard_no_mismatch": 3,
    "body_reference_replaced_by_basis": 4,
    "body_standard_no_mismatch": 5,
    "body_standard_name_mismatch": 6,
    "standard_not_found": 7,
    "basis_declared_but_unused": 8,
    "body_reference_not_in_basis": 9,
    "template_year_not_matched": 10,
    "template_not_matched": 11,
    "template_multiple_matched": 12,
    "missing_section": 13,
    "empty_section_body": 14,
    "placeholder_text_found": 15,
    "template_key_section_missing": 16,
    "key_section_missing": 17,
    "key_section_similarity_low": 18,
    "key_section_heading_no_changed": 19,
    "key_section_content_missing": 20,
    "key_section_content_modified": 21,
    "key_section_content_added": 22,
}


def check_word_document(
    session: Session,
    document_id: int,
    publish_date: date | None = None,
    replace: bool = True,
    check_scope: str = "basis_excel",
    issue_limit: int = 50,
) -> dict[str, object]:
    if check_scope not in ("basis_excel", "body_basis", "all"):
        raise ValueError("check_scope 只能是 basis_excel、body_basis 或 all")

    document = session.get(WordDocument, document_id)
    if publish_date:
        document.declared_publish_date = publish_date

    if replace:
        query = session.query(CheckIssue).filter(CheckIssue.document_id == document_id)
        if check_scope == "all":
            query = query.filter(CheckIssue.check_scope.in_(["basis_excel", "body_basis"]))
        else:
            query = query.filter(CheckIssue.issue_type.in_(issue_types_for_scope(check_scope)))
        query.delete()

    references = session.query(WordReference).filter(WordReference.document_id == document_id).order_by(WordReference.paragraph_index).all()
    clauses = session.query(MandatoryClause).all()
    validity_records = session.query(StandardValidityRecord).all()

    basis_references = [reference for reference in references if is_basis_reference(reference)]
    body_references = [reference for reference in references if not is_basis_reference(reference)]

    clauses_by_no: dict[str, list[MandatoryClause]] = {}
    for clause in clauses:
        clauses_by_no.setdefault(normalize_no(clause.standard_no), []).append(clause)

    issues: list[CheckIssue] = []
    if check_scope in ("basis_excel", "all"):
        issues.extend(
            check_basis_against_excel(
                document_id=document_id,
                references=basis_references,
                clauses=clauses,
                clauses_by_no=clauses_by_no,
                validity_records=validity_records,
                publish_date=publish_date,
            )
        )

    if check_scope in ("body_basis", "all"):
        issues.extend(
            check_body_against_basis(
                document_id=document_id,
                basis_references=basis_references,
                body_references=body_references,
                validity_records=validity_records,
            )
        )

    for issue in issues:
        session.add(issue)
    session.flush()

    sorted_issues = sorted(issues, key=issue_sort_key)
    returned_issues = sorted_issues if issue_limit <= 0 else sorted_issues[:issue_limit]
    grouped_issues = group_issues(returned_issues)
    session.commit()

    return {
        "document_id": document_id,
        "check_scope": check_scope,
        "reference_count": len(references),
        "basis_reference_count": len(basis_references),
        "body_reference_count": len(body_references),
        "issue_count": len(issues),
        "returned_issue_count": len(returned_issues),
        "issues": [issue_to_dict(issue) for issue in returned_issues],
        "grouped_issues": grouped_issues,
    }


def issue_types_for_scope(check_scope: str) -> list[str]:
    if check_scope == "basis_excel":
        return ["standard_replaced", "standard_name_mismatch", "standard_no_mismatch", "standard_not_found", "clause_not_found"]
    if check_scope == "body_basis":
        return [
            "body_reference_replaced_by_basis",
            "body_standard_no_mismatch",
            "body_standard_name_mismatch",
            "basis_declared_but_unused",
            "body_reference_not_in_basis",
        ]
    if check_scope == "completeness":
        return [
            "template_year_not_matched",
            "template_not_matched",
            "template_multiple_matched",
            "missing_section",
            "empty_section_body",
            "placeholder_text_found",
            "template_key_section_missing",
            "key_section_missing",
            "key_section_similarity_low",
            "key_section_heading_no_changed",
            "key_section_content_missing",
            "key_section_content_modified",
            "key_section_content_added",
        ]
    return list(ISSUE_ORDER)


def check_basis_against_excel(
    *,
    document_id: int,
    references: list[WordReference],
    clauses: list[MandatoryClause],
    clauses_by_no: dict[str, list[MandatoryClause]],
    validity_records: list[StandardValidityRecord],
    publish_date: date | None,
) -> list[CheckIssue]:
    issues: list[CheckIssue] = []
    for reference in references:
        ref_nos = split_values(reference.standard_no)
        ref_names = split_values(reference.standard_name)
        matched_by_no = find_clauses_by_no(ref_nos, clauses_by_no)
        matched_by_name = find_clauses_by_name(ref_names, clauses)
        matched_clauses = matched_by_no or matched_by_name
        replaced_records = find_replaced_records(reference, ref_nos, ref_names, validity_records, allow_name_only=True)

        if replaced_records:
            for record in replaced_records:
                severity = "high" if publish_date and record.new_effective_date and publish_date >= record.new_effective_date else "warning"
                issues.append(
                    make_issue(
                        document_id=document_id,
                        reference=reference,
                        issue_type="standard_replaced",
                        severity=severity,
                        matched_clause_id=matched_clauses[0].id if matched_clauses else None,
                        matched_standard_record_id=record.id,
                        reason=f"Word 引用可能已被新标准替代：{record.old_standard_text}",
                        suggestion=f"建议核对是否应采用：{record.new_standard_text}",
                        fix_data=replacement_record_fix_data(reference, record),
                    )
                )
            continue

        if ref_nos and not matched_by_no and not matched_by_name and not replaced_records:
            issues.append(
                make_issue(
                    document_id=document_id,
                    reference=reference,
                    issue_type="standard_not_found",
                    severity="info",
                    reason=f"Word 引用未在 Excel 标准库中找到：{reference.standard_no or reference.standard_name}",
                    suggestion="请确认 Excel 标准库是否需要补充该依据，或检查 Word 引用是否正确。",
                )
            )
            matched_clauses = []

        if matched_by_no and ref_names and name_mismatch(ref_names, matched_by_no):
            issues.append(
                make_issue(
                    document_id=document_id,
                    reference=reference,
                    issue_type="standard_name_mismatch",
                    severity="warning",
                    matched_clause_id=matched_by_no[0].id,
                    reason=f"标准号能匹配，但 Word 中的标准名称与 Excel 标准库名称不一致：{reference.standard_name}",
                    suggestion=f"请核对标准名称是否应写为：{matched_by_no[0].standard_name}",
                    fix_data=component_fix_data(reference, standard_name=matched_by_no[0].standard_name),
                )
            )
        elif not matched_by_no and matched_by_name and ref_nos:
            issues.append(
                make_issue(
                    document_id=document_id,
                    reference=reference,
                    issue_type="standard_no_mismatch",
                    severity="warning",
                    matched_clause_id=matched_by_name[0].id,
                    reason=f"标准名称能匹配，但 Word 中的标准号与 Excel 标准库不一致：{reference.standard_no}",
                    suggestion=f"请核对标准号是否应写为：{matched_by_name[0].standard_no}",
                    fix_data=component_fix_data(reference, standard_no=matched_by_name[0].standard_no),
                )
            )
    return issues


def check_body_against_basis(
    *,
    document_id: int,
    basis_references: list[WordReference],
    body_references: list[WordReference],
    validity_records: list[StandardValidityRecord],
) -> list[CheckIssue]:
    issues: list[CheckIssue] = []

    for reference in body_references:
        if not reference.standard_no and not reference.standard_name:
            continue

        ref_nos = split_values(reference.standard_no)
        ref_names = split_values(reference.standard_name)
        replaced_records = [
            record
            for record in find_replaced_records(reference, ref_nos, ref_names, validity_records, allow_name_only=True)
            if basis_has_new_standard(record, basis_references)
        ]
        if replaced_records:
            for record in replaced_records:
                issues.append(
                    make_issue(
                        document_id=document_id,
                        reference=reference,
                        issue_type="body_reference_replaced_by_basis",
                        severity="high",
                        matched_standard_record_id=record.id,
                        reason=f"正文仍引用旧标准，但{basis_section_label()}已列对应新标准：{record.old_standard_text}",
                        suggestion=f"建议正文改用{basis_section_label()}中的新标准：{record.new_standard_text}",
                        fix_data=replacement_record_fix_data(reference, record),
                    )
                )
            continue

        matched_by_no = find_basis_by_no(reference, basis_references)
        matched_by_name = find_basis_by_name(reference, basis_references)

        if matched_by_no:
            if reference.standard_name and reference_name_mismatch(reference, matched_by_no):
                issues.append(
                    make_issue(
                        document_id=document_id,
                        reference=reference,
                        issue_type="body_standard_name_mismatch",
                        severity="warning",
                        reason=f"正文引用的标准号在{basis_section_label()}中存在，但标准名称不一致：{reference.standard_name}",
                        suggestion=f"请核对是否应与{basis_section_label()}一致：{matched_by_no[0].standard_name}",
                        fix_data=component_fix_data(reference, standard_name=matched_by_no[0].standard_name),
                    )
                )
            continue

        if matched_by_name:
            if reference.standard_no and matched_by_name[0].standard_no:
                issues.append(
                    make_issue(
                        document_id=document_id,
                        reference=reference,
                        issue_type="body_standard_no_mismatch",
                        severity="warning",
                        reason=f"正文引用的标准名称在{basis_section_label()}中存在，但标准号不一致：{reference.standard_no}",
                        suggestion=f"请核对是否应与{basis_section_label()}一致：{matched_by_name[0].standard_no}",
                        fix_data=component_fix_data(reference, standard_no=matched_by_name[0].standard_no),
                    )
                )
            continue

        issues.append(
            make_issue(
                document_id=document_id,
                reference=reference,
                issue_type="body_reference_not_in_basis",
                severity="info",
                reason=f"正文引用未在{basis_section_label()}中找到：{reference.standard_no or reference.standard_name}",
                suggestion=f"请确认正文引用是否应补充到{basis_section_label()}，或检查正文引用是否写错。",
            )
        )

    for reference in basis_references:
        if reference.standard_no or reference.standard_name:
            if find_basis_usage(reference, body_references):
                continue
            issues.append(
                make_issue(
                    document_id=document_id,
                    reference=reference,
                    issue_type="basis_declared_but_unused",
                    severity="info",
                    reason=f"{basis_section_label()}中列出该依据，但正文未发现明确引用：{reference.standard_no or reference.standard_name}",
                    suggestion="该项不一定是错误，可人工确认是否属于仅作为总依据列出的标准。",
                )
            )

    return issues


def find_clauses_by_no(ref_nos: list[str], clauses_by_no: dict[str, list[MandatoryClause]]) -> list[MandatoryClause]:
    matched: list[MandatoryClause] = []
    for no in ref_nos:
        matched.extend(clauses_by_no.get(normalize_no(no), []))
    return list(dict.fromkeys(matched))


def find_clauses_by_name(ref_names: list[str], clauses: list[MandatoryClause]) -> list[MandatoryClause]:
    matched: list[MandatoryClause] = []
    for name in ref_names:
        normalized_name = normalize_name(name)
        if not normalized_name:
            continue
        for clause in clauses:
            clause_name = normalize_name(clause.standard_name)
            if normalized_name in clause_name or clause_name in normalized_name:
                matched.append(clause)
    return list(dict.fromkeys(matched))


def is_basis_reference(reference: WordReference) -> bool:
    return is_basis_section_title(reference.section_title)


def find_basis_by_no(reference: WordReference, basis_references: list[WordReference]) -> list[WordReference]:
    ref_nos = [normalize_no(no) for no in split_values(reference.standard_no) if normalize_no(no)]
    if not ref_nos:
        return []
    return [
        basis
        for basis in basis_references
        if any(no == basis_no for no in ref_nos for basis_no in split_normalized_nos(basis.standard_no))
    ]


def find_basis_by_name(reference: WordReference, basis_references: list[WordReference]) -> list[WordReference]:
    ref_names = [normalize_name(name) for name in split_values(reference.standard_name) if normalize_name(name)]
    if not ref_names:
        return []
    matched: list[WordReference] = []
    for basis in basis_references:
        basis_names = [normalize_name(name) for name in split_values(basis.standard_name) if normalize_name(name)]
        for ref_name in ref_names:
            if any(ref_name in basis_name or basis_name in ref_name for basis_name in basis_names):
                matched.append(basis)
                break
    return matched


def find_basis_usage(reference: WordReference, body_references: list[WordReference]) -> list[WordReference]:
    return find_basis_by_no(reference, body_references) or find_basis_by_name(reference, body_references)


def basis_has_new_standard(record: StandardValidityRecord, basis_references: list[WordReference]) -> bool:
    new_codes = extract_reference_codes(record.new_standard_text)
    new_names = extract_reference_names(record.new_standard_text)
    for basis in basis_references:
        basis_codes = reference_codes(basis)
        if new_codes and has_common_code(basis_codes, new_codes):
            return True
        basis_names = reference_names(basis)
        if replacement_names_match(basis_names, new_names):
            return True
    return False


def reference_name_mismatch(reference: WordReference, basis_references: list[WordReference]) -> bool:
    ref_names = [normalize_name(name) for name in split_values(reference.standard_name) if normalize_name(name)]
    basis_names = [
        normalize_name(name)
        for basis in basis_references
        for name in split_values(basis.standard_name)
        if normalize_name(name)
    ]
    return bool(ref_names and basis_names and not names_equivalent(ref_names, basis_names))


def split_normalized_nos(value: str) -> list[str]:
    return [normalize_no(no) for no in split_values(value) if normalize_no(no)]


def name_mismatch(ref_names: list[str], matched_clauses: list[MandatoryClause]) -> bool:
    normalized_refs = [normalize_name(name) for name in ref_names if normalize_name(name)]
    normalized_clauses = [normalize_name(clause.standard_name) for clause in matched_clauses if normalize_name(clause.standard_name)]
    return bool(normalized_refs and normalized_clauses and not names_equivalent(normalized_refs, normalized_clauses))


def find_replaced_records(
    reference: WordReference,
    ref_nos: list[str],
    ref_names: list[str],
    records: list[StandardValidityRecord],
    allow_name_only: bool = True,
) -> list[StandardValidityRecord]:
    matched: list[StandardValidityRecord] = []
    ref_codes = reference_codes(reference)
    ref_codes.update(normalize_no(no) for no in ref_nos if normalize_no(no))
    normalized_ref_names = [normalize_name(name) for name in ref_names if normalize_name(name)]

    for record in records:
        old_codes = extract_reference_codes(record.old_standard_text)
        new_codes = extract_reference_codes(record.new_standard_text)

        if ref_codes:
            if has_common_code(ref_codes, new_codes):
                continue
            if has_common_code(ref_codes, old_codes):
                matched.append(record)
            continue

        if not allow_name_only:
            continue

        old_names = extract_reference_names(record.old_standard_text)
        new_names = extract_reference_names(record.new_standard_text)
        if replacement_names_match(normalized_ref_names, old_names) and not replacement_names_match(normalized_ref_names, new_names):
            matched.append(record)
    return matched


def reference_codes(reference: WordReference) -> set[str]:
    codes: set[str] = set()
    for value in (getattr(reference, "standard_no", ""), getattr(reference, "standard_name", "")):
        codes.update(extract_reference_codes(value))
    return codes


def reference_names(reference: WordReference) -> list[str]:
    names: list[str] = []
    for value in (getattr(reference, "standard_name", ""),):
        names.extend(extract_reference_names(value))
    return list(dict.fromkeys(name for name in names if name))


def extract_reference_codes(value: str) -> set[str]:
    text = value or ""
    codes = {
        normalize_no(match.group(0))
        for pattern in (STANDARD_NO_RE, DOCUMENT_NO_RE)
        for match in pattern.finditer(text)
        if normalize_no(match.group(0))
    }
    for item in split_values(text):
        normalized = normalize_no(item)
        if normalized and (STANDARD_NO_RE.fullmatch(item.strip()) or DOCUMENT_NO_RE.fullmatch(item.strip())):
            codes.add(normalized)
    return codes


def extract_reference_names(value: str) -> list[str]:
    text = value or ""
    names = [normalize_name(name) for name in STANDARD_NAME_RE.findall(text) if normalize_name(name)]
    if names:
        return list(dict.fromkeys(names))
    normalized = normalize_name(text)
    return [normalized] if normalized else []


def has_common_code(left: set[str], right: set[str]) -> bool:
    return bool(left and right and left.intersection(right))


def names_equivalent(left: list[str], right: list[str]) -> bool:
    left_keys = {normalize_name(name) for name in left if normalize_name(name)}
    right_keys = {normalize_name(name) for name in right if normalize_name(name)}
    return bool(left_keys and right_keys and left_keys.intersection(right_keys))


def replacement_names_match(ref_names: list[str], candidate_names: list[str]) -> bool:
    ref_keys = {replacement_name_key(name) for name in ref_names if replacement_name_key(name)}
    candidate_keys = {replacement_name_key(name) for name in candidate_names if replacement_name_key(name)}
    return bool(ref_keys and candidate_keys and ref_keys.intersection(candidate_keys))


def replacement_name_key(value: str) -> str:
    text = normalize_name(value)
    text = re.sub(r"(?:19|20)\d{2}年版", "", text)
    return re.sub(r"(?:19|20)\d{2}版", "", text)


def replacement_record_fix_data(
    reference: WordReference,
    record: StandardValidityRecord,
) -> dict[str, object]:
    return component_fix_data(
        reference,
        standard_no=display_standard_no(record.new_standard_text),
        standard_name=display_standard_name(record.new_standard_text),
    )


def component_fix_data(
    reference: WordReference,
    *,
    standard_no: str = "",
    standard_name: str = "",
) -> dict[str, object]:
    replacements: list[dict[str, str]] = []
    target_no = display_standard_no(standard_no)
    target_name = display_standard_name(standard_name)

    if reference.standard_no and target_no and normalize_no(reference.standard_no) != normalize_no(target_no):
        replacements.append(
            {
                "target": "standard_no",
                "before": reference.standard_no,
                "after": target_no,
            }
        )
    if reference.standard_name and target_name and normalize_name(reference.standard_name) != normalize_name(target_name):
        replacements.append(
            {
                "target": "standard_name",
                "before": reference.standard_name,
                "after": target_name,
            }
        )

    return {"auto_fixable": bool(replacements), "replacements": replacements}


def display_standard_no(value: str) -> str:
    text = value or ""
    for pattern in (STANDARD_NO_RE, DOCUMENT_NO_RE):
        match = pattern.search(text)
        if match:
            result = re.sub(r"\s+", " ", match.group(0).replace("－", "-")).strip()
            return re.sub(r"\s*-\s*", "-", result)
    return text.strip() if STANDARD_NO_RE.fullmatch(text.strip()) or DOCUMENT_NO_RE.fullmatch(text.strip()) else ""


def display_standard_name(value: str) -> str:
    text = value or ""
    match = STANDARD_NAME_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip().strip("《》")


def make_issue(
    *,
    document_id: int,
    reference: WordReference,
    issue_type: str,
    severity: str,
    reason: str,
    suggestion: str,
    matched_clause_id: int | None = None,
    matched_standard_record_id: int | None = None,
    fix_data: dict[str, object] | None = None,
) -> CheckIssue:
    return CheckIssue(
        owner_user_id=reference.owner_user_id,
        document_id=document_id,
        word_reference_id=reference.id,
        matched_clause_id=matched_clause_id,
        matched_standard_record_id=matched_standard_record_id,
        section_title=reference.section_title,
        paragraph_index=reference.paragraph_index,
        standard_no=reference.standard_no,
        standard_name=reference.standard_name,
        clause_no=reference.clause_no,
        check_scope=scope_for_issue(issue_type),
        issue_type=issue_type,
        severity=severity,
        original_text=reference.quoted_text,
        reason=reason,
        suggestion=suggestion,
        fix_data=fix_data or {},
    )


def scope_for_issue(issue_type: str) -> str:
    if issue_type.startswith("body_") or issue_type == "basis_declared_but_unused":
        return "body_basis"
    return "basis_excel"


def issue_to_dict(issue: CheckIssue) -> dict[str, object]:
    return {
        "issue_id": issue.id,
        "check_scope": issue.check_scope,
        "issue_type": issue.issue_type,
        "severity": issue.severity,
        "word_reference_id": issue.word_reference_id,
        "matched_clause_id": issue.matched_clause_id,
        "matched_standard_record_id": issue.matched_standard_record_id,
        "section_title": issue.section_title,
        "paragraph_index": issue.paragraph_index,
        "standard_no": issue.standard_no,
        "standard_name": issue.standard_name,
        "clause_no": issue.clause_no,
        "original_text": issue.original_text,
        "reason": issue.reason,
        "suggestion": issue.suggestion,
        "fix_data": issue.fix_data or {},
    }


def issue_sort_key(issue: CheckIssue) -> tuple[int, int, int]:
    return (ISSUE_ORDER.get(issue.issue_type, 99), issue.paragraph_index, issue.word_reference_id or 0)


def group_issues(issues: list[CheckIssue]) -> dict[str, list[dict[str, object]]]:
    grouped = {issue_type: [] for issue_type in ISSUE_ORDER}
    for issue in issues:
        grouped.setdefault(issue.issue_type, []).append(issue_to_dict(issue))
    return grouped


def split_values(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[；;]", value or "") if item.strip()]


def normalize_no(value: str) -> str:
    text = (value or "").upper()
    for old, new in {"－": "-", "〔": "[", "〕": "]", "（": "(", "）": ")"}.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", "", text)


def normalize_name(value: str) -> str:
    text = value or ""
    names = re.findall(r"《([^》]+)》", text)
    if names:
        text = "；".join(names)
    text = STANDARD_NO_RE.sub("", text)
    text = re.sub(r"(?<=\d)\s*(?:~|～|-|－|–|—|至)\s*(?=\d)", "~", text)
    text = re.sub(r"[，,。；;：《》“”（）()【】\[\]]", "", text)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"^(?:中华人民共和国)?(?:国家|通信行业|行业|中国移动企业|企业)?标准", "", text)
    return text.lower()
