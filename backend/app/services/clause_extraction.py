import hashlib
import json
import re
from pathlib import Path

import fitz

from app.config import BACKEND_ROOT
from app.db.database import SessionLocal
from app.db.models import AgentSession, ClauseExtractionRun
from app.llm import USER_REPORT_FORMAT_RULES, call_llm
from app.services.knowledge_base import parse_document
from app.services.pdf_vision import (
    analyze_pdf_bold_lines,
    analyze_pdf_visual_evidence,
    pdf_page_count,
)


PARSER_VERSION = "12"
PROMPT_VERSION = "2"
TERMINAL_STATUSES = ("completed", "manual_review", "failed")
CLAUSE_NO_SOURCE = r"\d{1,2}(?:[.．。]\d{1,2}){1,3}"
CLAUSE_NO_PATTERN = re.compile(rf"(?<!\d)({CLAUSE_NO_SOURCE})(?!\d)")
OCR_DIGIT_SOURCE = r"[0-9OIlJ]"
FLEXIBLE_CLAUSE_NO_SOURCE = (
    rf"{OCR_DIGIT_SOURCE}{{1,2}}\s*(?:[.．。]\s*{OCR_DIGIT_SOURCE}{{1,2}}\s*){{1,3}}"
)
CLAUSE_LINE_PATTERN = re.compile(
    rf"^\s*(?:[#>*_\-]+\s*)?({FLEXIBLE_CLAUSE_NO_SOURCE})(.*)$",
    re.MULTILINE,
)
ANNOUNCEMENT_PATTERN = re.compile(
    r"其中[，,]?\s*第(?P<clause_list>.+?)条为强制性条文", re.DOTALL
)
ANNOUNCEMENT_REF_PATTERN = re.compile(
    rf"(?P<clause>{CLAUSE_NO_SOURCE})(?:条)?"
    r"(?:第(?P<items>\d{1,2}(?:[,，、]\d{1,2})*)款)?"
)
ITEM_LINE_PATTERN = re.compile(r"^\s*(?P<item>\d{1,2})\s*[.、]\s*(?P<text>.*)$")
VISION_PREVIEW_PAGE_COUNT = 12
BODY_OCR_PROMPT = (
    "请只做高精度文字 OCR，逐页完整保留规范正文、条号、数字、单位、标点、表格和分页内容。"
    "忽略斜向水印。不要根据必须、严禁、应、不得等语义推断强制性条文，也不要自行添加 "
    "Markdown 粗体标记。数字 0、1、6、8、9 不得识别为字母。"
)


def start_clause_extraction_run(
    *,
    file_path: str,
    owner_user_id: int,
    session_id: int | None = None,
) -> dict[str, object]:
    path = Path(file_path)
    file_name = display_file_name(path.name)
    if path.suffix.lower() != ".pdf":
        raise ValueError("强条抽取只支持 PDF 文件")
    if not path.exists():
        raise ValueError("PDF 文件不存在")
    file_hash = sha256_file(path)

    with SessionLocal() as session:
        agent_session = get_owned_agent_session(session, session_id, owner_user_id) if session_id else None
        cached = (
            session.query(ClauseExtractionRun)
            .filter(
                ClauseExtractionRun.owner_user_id == owner_user_id,
                ClauseExtractionRun.file_hash == file_hash,
                ClauseExtractionRun.parser_version == PARSER_VERSION,
                ClauseExtractionRun.prompt_version == PROMPT_VERSION,
                ClauseExtractionRun.status.in_(["completed", "manual_review"]),
            )
            .order_by(ClauseExtractionRun.id.desc())
            .first()
        )
        if cached:
            if agent_session:
                agent_session.active_clause_extraction_run_id = cached.id
                agent_session.title = shorten(Path(file_name).stem)
                session.commit()
            state = clause_extraction_state_dict(cached)
            state["reused"] = True
            return state

        extraction_run = ClauseExtractionRun(
            owner_user_id=owner_user_id,
            session_id=session_id,
            file_name=file_name,
            file_path=str(path),
            file_hash=file_hash,
            status="planning",
            parser_version=PARSER_VERSION,
            prompt_version=PROMPT_VERSION,
        )
        session.add(extraction_run)
        session.flush()
        if agent_session:
            agent_session.active_clause_extraction_run_id = extraction_run.id
            agent_session.title = shorten(Path(file_name).stem)
        session.commit()
        session.refresh(extraction_run)
        return clause_extraction_state_dict(extraction_run)


def inspect_clause_pdf(*, extraction_run_id: int, owner_user_id: int) -> dict[str, object]:
    with SessionLocal() as session:
        extraction_run = get_owned_run(session, extraction_run_id, owner_user_id, for_update=True)
        if extraction_run.status == "inspected":
            return inspection_result(extraction_run)
        require_status(extraction_run, "planning", "inspecting")
        if extraction_run.status == "planning":
            extraction_run.status = "inspecting"
            session.commit()
        source_path = Path(extraction_run.file_path)
        source_file_hash = extraction_run.file_hash

    total_page_count = pdf_page_count(source_path)
    if total_page_count <= 0:
        raise ValueError("PDF 没有可识别页面")

    try:
        visual = inspect_pdf_visual_evidence(source_path, total_page_count)
    except Exception as exc:
        visual = {
            "vision_attempted": True,
            "vision_completed": False,
            "vision_error": str(exc),
            "vision_pages": [],
            "listed_clause_nos": [],
            "visual_bold_clause_nos": [],
            "detection_methods": [],
        }

    reusable = find_reusable_parsed_pages(
        file_hash=source_file_hash,
        owner_user_id=owner_user_id,
        expected_page_count=total_page_count,
        exclude_run_id=extraction_run_id,
    )
    if reusable:
        reused_run_id, pages = reusable
    else:
        reused_run_id = None
        pages = align_pages(
            parse_document(source_path, preserve_empty_pages=True),
            total_page_count,
        )
    signals = detect_clause_signals(pages, display_file_name(source_path.name))
    signals = merge_visual_signals(signals, visual)

    if reused_run_id:
        signals["body_pages_reused"] = True
        signals["body_pages_reused_from_run_id"] = reused_run_id
        if "body_cache" not in signals["detection_methods"]:
            signals["detection_methods"].append("body_cache")
    elif signals.get("parse_quality") == "low":
        native_pages = extract_native_pdf_pages(source_path, total_page_count)
        native_signals = detect_clause_signals(
            native_pages, display_file_name(source_path.name)
        )
        if native_signals.get("parse_quality") != "low":
            pages = native_pages
            signals = merge_visual_signals(native_signals, visual)
            signals["body_native_text"] = True
            signals["detection_methods"].append("body_native_text")
        else:
            try:
                ocr_pages = parse_document(
                    source_path,
                    target_page_indexes=list(range(total_page_count)),
                    high_accuracy=True,
                    user_prompt=BODY_OCR_PROMPT,
                    preserve_empty_pages=True,
                )
                candidate_pages = align_pages(ocr_pages, total_page_count)
                text_signals = detect_clause_signals(
                    candidate_pages, display_file_name(source_path.name)
                )
                if text_signals.get("parse_quality") == "low":
                    raise ValueError("高精度正文 OCR 返回空内容或有效文本量不足")
                pages = candidate_pages
                signals = merge_visual_signals(text_signals, visual)
                signals["body_high_accuracy_all"] = True
                if "body_high_accuracy" not in signals["detection_methods"]:
                    signals["detection_methods"].append("body_high_accuracy")
            except Exception as exc:
                signals["body_high_accuracy_all"] = False
                signals["body_ocr_error"] = str(exc)
    parsed_path = save_parsed_pages(extraction_run_id, pages)

    with SessionLocal() as session:
        extraction_run = get_owned_run(session, extraction_run_id, owner_user_id, for_update=True)
        require_status(extraction_run, "inspecting")
        extraction_run.parsed_pages_path = str(parsed_path)
        extraction_run.page_count = total_page_count
        extraction_run.detection_methods = list(signals["detection_methods"])
        extraction_run.result_json = {
            "standard_no": signals["standard_no"],
            "standard_name": signals["standard_name"],
            "inspection": signals,
            "clauses": [],
            "missing_clause_nos": [],
            "warnings": [],
        }
        extraction_run.status = "inspected"
        session.commit()
        return inspection_result(extraction_run)


def extract_clause_candidates(*, extraction_run_id: int, owner_user_id: int) -> dict[str, object]:
    with SessionLocal() as session:
        extraction_run = get_owned_run(session, extraction_run_id, owner_user_id, for_update=True)
        if extraction_run.status == "extracted":
            return extraction_result(extraction_run)
        require_status(extraction_run, "inspected", "extracting")
        if extraction_run.status == "inspected":
            extraction_run.status = "extracting"
        parsed_pages_path = extraction_run.parsed_pages_path
        source_path = Path(extraction_run.file_path)
        result = dict(extraction_run.result_json or {})
        session.commit()

    pages = load_parsed_pages(parsed_pages_path)
    inspection = dict(result.get("inspection") or {})
    listed_clause_nos = [normalize_clause_no(value) for value in inspection.get("listed_clause_nos") or []]
    listed_clause_refs = normalize_clause_references(
        list(inspection.get("listed_clause_refs") or []) or listed_clause_nos
    )
    visual_bold_clause_nos = [
        normalize_clause_no(value)
        for value in inspection.get("visual_bold_clause_nos") or []
    ]
    listed_main_nos = {item["clause_no"] for item in listed_clause_refs}
    evidence_refs = normalize_clause_references(
        [
            *listed_clause_refs,
            *(
                {"clause_no": clause_no, "item_no": ""}
                for clause_no in visual_bold_clause_nos
                if clause_no not in listed_main_nos
            ),
        ]
    )
    candidates = extract_candidates_from_pages(
        pages,
        listed_clause_nos=listed_clause_nos,
        listed_clause_refs=listed_clause_refs,
        visual_bold_clause_nos=visual_bold_clause_nos,
    )
    if evidence_refs and (
        inspection.get("body_high_accuracy_all")
        or inspection.get("body_native_text")
        or inspection.get("body_pages_reused")
    ):
        inspection["body_refined"] = True
    elif evidence_refs:
        target_page_nos = {int(item["page_no"]) for item in candidates}
        bold_clause_pages = dict(inspection.get("bold_clause_pages") or {})
        target_page_nos.update(
            int(bold_clause_pages[clause_no])
            for clause_no in visual_bold_clause_nos
            if clause_no in bold_clause_pages
        )
        target_page_nos = sorted(target_page_nos)
        try:
            if not target_page_nos:
                raise ValueError("未能定位强条所在正文页")
            refined_pages = parse_document(
                source_path,
                target_page_indexes=[page_no - 1 for page_no in target_page_nos],
                high_accuracy=True,
                user_prompt=BODY_OCR_PROMPT,
                preserve_empty_pages=True,
            )
            if len(refined_pages) != len(target_page_nos):
                raise ValueError("高精度正文页数量与目标页不一致")
            for page_no, refined_text in zip(target_page_nos, refined_pages):
                pages[page_no - 1] = refined_text
            continuation_page_nos = continuation_pages_to_refine(
                pages, candidates, target_page_nos
            )
            if continuation_page_nos:
                continuation_pages = parse_document(
                    source_path,
                    target_page_indexes=[page_no - 1 for page_no in continuation_page_nos],
                    high_accuracy=True,
                    user_prompt=BODY_OCR_PROMPT,
                    preserve_empty_pages=True,
                )
                if len(continuation_pages) != len(continuation_page_nos):
                    raise ValueError("高精度续页数量与目标页不一致")
                for page_no, refined_text in zip(
                    continuation_page_nos, continuation_pages
                ):
                    pages[page_no - 1] = refined_text
            save_parsed_pages(extraction_run_id, pages)
            refined_candidates = extract_candidates_from_pages(
                pages,
                listed_clause_nos=listed_clause_nos,
                listed_clause_refs=listed_clause_refs,
                visual_bold_clause_nos=visual_bold_clause_nos,
            )
            refined_by_ref = {
                candidate_reference_key(item): item for item in refined_candidates
            }
            existing_by_ref = {
                candidate_reference_key(item): item for item in candidates
            }
            candidates = [
                refined_by_ref.get(reference_key(reference), existing_by_ref.get(reference_key(reference)))
                for reference in evidence_refs
                if refined_by_ref.get(reference_key(reference), existing_by_ref.get(reference_key(reference)))
            ]
            inspection["body_refined"] = True
            inspection["body_refined_page_count"] = len(
                set(target_page_nos + continuation_page_nos)
            )
            if "body_high_accuracy" not in inspection["detection_methods"]:
                inspection["detection_methods"].append("body_high_accuracy")
        except Exception as exc:
            inspection["body_refined"] = False
            inspection["body_refinement_error"] = str(exc)
    found_refs = {candidate_reference_key(item) for item in candidates}
    missing = [
        reference_label(reference)
        for reference in evidence_refs
        if reference_key(reference) not in found_refs
    ]

    result["clauses"] = candidates
    result["missing_clause_nos"] = missing
    result["inspection"] = inspection
    with SessionLocal() as session:
        extraction_run = get_owned_run(session, extraction_run_id, owner_user_id, for_update=True)
        require_status(extraction_run, "extracting")
        extraction_run.result_json = result
        extraction_run.detection_methods = list(inspection.get("detection_methods") or [])
        extraction_run.clause_count = len(candidates)
        extraction_run.status = "extracted"
        session.commit()
        return extraction_result(extraction_run)


def verify_clause_candidates(*, extraction_run_id: int, owner_user_id: int) -> dict[str, object]:
    with SessionLocal() as session:
        extraction_run = get_owned_run(session, extraction_run_id, owner_user_id, for_update=True)
        if extraction_run.status == "verified":
            return verification_result(extraction_run)
        require_status(extraction_run, "extracted", "verifying")
        extraction_run.status = "verifying"
        result = dict(extraction_run.result_json or {})
        inspection = dict(result.get("inspection") or {})
        clauses = list(result.get("clauses") or [])
        missing = list(result.get("missing_clause_nos") or [])
        warnings: list[str] = []

        if clauses:
            mandatory_status = "present"
        elif inspection.get("explicit_none"):
            mandatory_status = "confirmed_none"
        elif not inspection.get("vision_completed") or inspection.get("has_bold_rule"):
            mandatory_status = "needs_review"
        else:
            mandatory_status = "none_detected"

        if missing:
            warnings.append(f"视觉证据确认的 {len(missing)} 个条号未在正文 OCR 中定位")
        if inspection.get("listed_clause_nos") and not inspection.get("body_refined"):
            warnings.append("强条正文页高精度识别未完成，条文内容需要人工复核")
        if inspection.get("vision_attempted") and not inspection.get("vision_completed"):
            warnings.append("视觉模型检查未完成，公告条号和粗体证据需要人工复核")
        if (
            inspection.get("has_bold_rule")
            and not inspection.get("bold_candidate_count")
            and not inspection.get("listed_clause_nos")
        ):
            warnings.append("PDF 声明以黑体标识强条，但视觉扫描未确认到对应粗体条文")
        requires_review = bool(missing or mandatory_status == "needs_review" or warnings)
        result.update(
            {
                "mandatory_status": mandatory_status,
                "requires_review": requires_review,
                "warnings": warnings,
            }
        )
        extraction_run.result_json = result
        extraction_run.mandatory_status = mandatory_status
        extraction_run.status = "verified"
        session.commit()
        return verification_result(extraction_run)


def get_clause_extraction_state(*, extraction_run_id: int, owner_user_id: int) -> dict[str, object]:
    with SessionLocal() as session:
        extraction_run = get_owned_run(session, extraction_run_id, owner_user_id)
        return clause_extraction_state_dict(extraction_run)


def get_clause_extraction_result(*, extraction_run_id: int, owner_user_id: int) -> dict[str, object]:
    with SessionLocal() as session:
        extraction_run = get_owned_run(session, extraction_run_id, owner_user_id)
        if extraction_run.status not in ("completed", "manual_review"):
            raise ValueError("强条抽取任务尚未结束")
        return clause_extraction_result_dict(extraction_run)


def append_clause_extraction_trace(
    *,
    extraction_run_id: int,
    owner_user_id: int,
    phase: str,
    actor: str,
    name: str,
    output: dict[str, object],
    summary: str,
) -> dict[str, object]:
    with SessionLocal() as session:
        extraction_run = get_owned_run(session, extraction_run_id, owner_user_id, for_update=True)
        trace = list(extraction_run.decision_trace or [])
        entry = {
            "step": len(trace) + 1,
            "phase": phase,
            "actor": actor,
            "name": name,
            "output": output,
            "summary": summary,
        }
        extraction_run.decision_trace = trace + [entry]
        session.commit()
        return entry


def finalize_clause_extraction_run(
    *,
    extraction_run_id: int,
    owner_user_id: int,
    action: str,
    reason: str,
) -> dict[str, object]:
    if action not in ("finish", "manual_review"):
        raise ValueError("强条抽取 Agent 终止动作无效")
    with SessionLocal() as session:
        extraction_run = get_owned_run(session, extraction_run_id, owner_user_id, for_update=True)
        if extraction_run.status in ("completed", "manual_review"):
            return clause_extraction_result_dict(extraction_run)
        require_status(extraction_run, "verified")
        result = dict(extraction_run.result_json or {})
        requires_review = bool(result.get("requires_review"))
        completed = action == "finish" and not requires_review
        extraction_run.status = "completed" if completed else "manual_review"

        if extraction_run.session_id:
            agent_session = get_owned_agent_session(
                session, extraction_run.session_id, owner_user_id
            )
            if agent_session:
                agent_session.active_clause_extraction_run_id = extraction_run.id
                agent_session.title = shorten(Path(extraction_run.file_name).stem)
        session.commit()
        output = clause_extraction_result_dict(extraction_run)
        if reason:
            output["message"] = f"{output['message']} 决策原因：{reason}"
        return output


def fail_clause_extraction_run(
    *, extraction_run_id: int, owner_user_id: int, error_message: str
) -> None:
    with SessionLocal() as session:
        extraction_run = get_owned_run(session, extraction_run_id, owner_user_id, for_update=True)
        if extraction_run.status not in TERMINAL_STATUSES:
            extraction_run.status = "failed"
            extraction_run.error_message = error_message
            session.commit()


def answer_clause_extraction_question(
    *, message: str, result: dict[str, object], conversation_context: str
) -> str:
    clauses = list(result.get("clauses") or [])
    selected = select_clauses_for_question(clauses, message)
    prompt = f"""
你是强制性条文抽取 Agent 的结果总结器。只能依据下面的抽取任务结果回答，不得把未识别到的内容补写成强条。

要求：
1. 首次汇总时说明识别方法、强条数量、待复核项，并按条号列出关键结果。
2. 用户询问某条或某章时，只回答筛选出的条文。
3. mandatory_status 为 none_detected 时，只能说“未识别到”，不能断言规范确定没有强条。
4. 每条结论尽量标注 PDF 页码；有 warning 时明确提示人工复核。
5. 只能描述当前任务结果，不得沿用会话中旧任务的条数、缺失项或错误结论。
6. vision_bold_rule 只表示 PDF 声明“黑体为强条”；只有 vision_bold_body 才表示视觉模型在正文页确认了粗体条文。
7. 条文含 reference 时必须按 reference 逐项列出，不得把同一主条号下的多款合并。

{USER_REPORT_FORMAT_RULES}

会话上下文：
{conversation_context}

用户问题：{message}

任务摘要：
{json.dumps({key: result.get(key) for key in ('file_name', 'mandatory_status', 'detection_methods', 'page_count', 'clause_count', 'missing_clause_nos', 'warnings')}, ensure_ascii=False)}

相关条文：
{json.dumps(selected, ensure_ascii=False)}
"""
    return call_llm(prompt)


def inspect_pdf_visual_evidence(path: Path, total_page_count: int) -> dict[str, object]:
    preview_indexes = list(range(min(total_page_count, VISION_PREVIEW_PAGE_COUNT)))
    preview = analyze_pdf_visual_evidence(path, page_indexes=preview_indexes)
    visual_pages = list(preview.get("pages") or [])
    preview_summary = aggregate_visual_evidence(visual_pages)

    may_stop_at_front_matter = bool(
        preview_summary["listed_clause_nos"]
        or preview_summary["explicit_none_pages"]
    )
    remaining_indexes = list(range(len(preview_indexes), total_page_count))
    bold_line_metrics: list[dict[str, object]] = []
    if may_stop_at_front_matter:
        pass
    elif preview_summary["bold_rule_pages"]:
        for page in visual_pages:
            page["bold_clause_nos"] = []
        bold_scan = analyze_pdf_bold_lines(
            path,
            page_indexes=list(range(total_page_count)),
        )
        visual_pages.extend(list(bold_scan.get("pages") or []))
        bold_line_metrics = [
            item
            for item in list(bold_scan.get("candidate_metrics") or [])
            if item.get("is_bold_candidate")
        ]
    elif remaining_indexes:
        remaining = analyze_pdf_visual_evidence(path, page_indexes=remaining_indexes)
        visual_pages.extend(list(remaining.get("pages") or []))

    summary = aggregate_visual_evidence(visual_pages)
    scanned_page_nos = {
        int(page.get("page_no") or 0) for page in visual_pages
    }
    summary.update(
        {
            "vision_attempted": True,
            "vision_completed": True,
            "vision_model": preview.get("model"),
            "vision_full_scan": len(scanned_page_nos) == total_page_count,
            "vision_scanned_page_count": len(scanned_page_nos),
            "vision_pages": visual_pages,
            "bold_line_metrics": bold_line_metrics,
        }
    )
    return summary


def aggregate_visual_evidence(
    visual_pages: list[dict[str, object]],
) -> dict[str, object]:
    listed_clause_nos: list[str] = []
    listed_clause_refs: list[dict[str, str]] = []
    bold_clause_nos: list[str] = []
    announcement_pages: list[int] = []
    bold_rule_pages: list[int] = []
    explicit_none_pages: list[int] = []
    bold_clause_pages: dict[str, int] = {}

    for page in visual_pages:
        page_no = int(page.get("page_no") or 0)
        page_listed = [
            normalize_clause_no(str(value))
            for value in list(page.get("announcement_clause_nos") or [])
        ]
        page_refs = normalize_clause_references(
            list(page.get("announcement_clause_refs") or [])
        )
        for reference in page_refs:
            clause_no = reference["clause_no"]
            if clause_no not in page_listed:
                page_listed.append(clause_no)
        page_bold = [
            normalize_clause_no(str(value))
            for value in list(page.get("bold_clause_nos") or [])
        ]
        if page_listed:
            announcement_pages.append(page_no)
        if page.get("has_bold_rule"):
            bold_rule_pages.append(page_no)
        if page.get("has_explicit_no_mandatory"):
            explicit_none_pages.append(page_no)
        for clause_no in page_listed:
            if clause_no not in listed_clause_nos:
                listed_clause_nos.append(clause_no)
        for reference in page_refs:
            if reference_key(reference) not in {
                reference_key(item) for item in listed_clause_refs
            }:
                listed_clause_refs.append(reference)
        for clause_no in page_bold:
            if clause_no not in bold_clause_nos:
                bold_clause_nos.append(clause_no)
                bold_clause_pages[clause_no] = page_no

    methods: list[str] = []
    if listed_clause_nos:
        methods.append("vision_announcement")
    if bold_rule_pages:
        methods.append("vision_bold_rule")
    if bold_clause_nos:
        methods.append("vision_bold_body")
    if explicit_none_pages:
        methods.append("vision_explicit_none")
    return {
        "listed_clause_nos": sorted(listed_clause_nos, key=clause_sort_key),
        "listed_clause_refs": sorted(listed_clause_refs, key=reference_sort_key),
        "visual_bold_clause_nos": sorted(bold_clause_nos, key=clause_sort_key),
        "announcement_pages": sorted(set(announcement_pages)),
        "bold_rule_pages": sorted(set(bold_rule_pages)),
        "explicit_none_pages": sorted(set(explicit_none_pages)),
        "bold_clause_pages": bold_clause_pages,
        "detection_methods": methods,
    }


def merge_visual_signals(
    text_signals: dict[str, object], visual: dict[str, object]
) -> dict[str, object]:
    signals = dict(text_signals)
    visual_listed = list(visual.get("listed_clause_nos") or [])
    if visual_listed:
        signals["listed_clause_nos"] = visual_listed
        signals["announcement_pages"] = list(visual.get("announcement_pages") or [])
    listed_refs = normalize_clause_references(
        list(signals.get("listed_clause_refs") or [])
        + list(visual.get("listed_clause_refs") or [])
    )
    referenced_clause_nos = {item["clause_no"] for item in listed_refs}
    listed_refs.extend(
        {"clause_no": normalize_clause_no(value), "item_no": ""}
        for value in signals.get("listed_clause_nos") or []
        if normalize_clause_no(value) not in referenced_clause_nos
    )
    signals["listed_clause_refs"] = sorted(listed_refs, key=reference_sort_key)
    visual_bold_nos = list(visual.get("visual_bold_clause_nos") or [])
    signals["visual_bold_clause_nos"] = visual_bold_nos
    signals["bold_clause_pages"] = dict(visual.get("bold_clause_pages") or {})
    signals["bold_candidate_count"] = len(visual_bold_nos)
    signals["bold_rule_pages"] = sorted(
        set(signals.get("bold_rule_pages") or [])
        | set(visual.get("bold_rule_pages") or [])
    )
    signals["explicit_none_pages"] = sorted(
        set(signals.get("explicit_none_pages") or [])
        | set(visual.get("explicit_none_pages") or [])
    )
    signals["has_bold_rule"] = bool(signals["bold_rule_pages"])
    signals["explicit_none"] = bool(signals["explicit_none_pages"])

    methods = [
        value
        for value in list(signals.get("detection_methods") or [])
        if value not in {"no_evidence", "bold_body"}
    ]
    for method in list(visual.get("detection_methods") or []):
        if method not in methods:
            methods.append(method)
    if not methods:
        methods = [
            "vision_no_evidence"
            if visual.get("vision_completed")
            else "no_evidence"
        ]
    signals["detection_methods"] = methods
    for key in (
        "vision_attempted",
        "vision_completed",
        "vision_error",
        "vision_model",
        "vision_full_scan",
        "vision_scanned_page_count",
        "vision_pages",
    ):
        if key in visual:
            signals[key] = visual[key]
    return signals


def align_pages(pages: list[str], expected_count: int) -> list[str]:
    aligned = list(pages[:expected_count])
    if len(aligned) < expected_count:
        aligned.extend([""] * (expected_count - len(aligned)))
    return aligned


def extract_native_pdf_pages(path: Path, expected_count: int) -> list[str]:
    with fitz.open(path) as document:
        pages = [page.get_text("text").strip() for page in document]
    return align_pages(pages, expected_count)


def detect_clause_signals(pages: list[str], file_name: str) -> dict[str, object]:
    announcement_pages: list[int] = []
    bold_rule_pages: list[int] = []
    explicit_none_pages: list[int] = []
    listed_clause_nos: list[str] = []
    listed_clause_refs: list[dict[str, str]] = []
    for page_no, text in enumerate(pages, start=1):
        compact = " ".join(text.split())
        page_refs = extract_announcement_references(text)
        if page_refs:
            announcement_pages.append(page_no)
            listed_clause_refs = normalize_clause_references(
                [*listed_clause_refs, *page_refs]
            )
            for reference in page_refs:
                if reference["clause_no"] not in listed_clause_nos:
                    listed_clause_nos.append(reference["clause_no"])
        announcement = ANNOUNCEMENT_PATTERN.search(text)
        if announcement:
            if page_no not in announcement_pages:
                announcement_pages.append(page_no)
            for clause_no in extract_clause_numbers(announcement.group("clause_list")):
                normalized = normalize_clause_no(clause_no)
                if normalized not in listed_clause_nos:
                    listed_clause_nos.append(normalized)
        if "强制性条文" in compact and ("黑体字" in compact or "粗体" in compact):
            bold_rule_pages.append(page_no)
        if "无强制性条文" in compact or "不设强制性条文" in compact:
            explicit_none_pages.append(page_no)

    methods = []
    if listed_clause_nos:
        methods.append("announcement_list")
    if bold_rule_pages:
        methods.append("bold_rule")
    if explicit_none_pages:
        methods.append("explicit_none")
    if not methods:
        methods.append("no_evidence")

    sample = "\n".join(pages[:5])
    standard_no_match = re.search(
        r"\b(?:GB(?:/T)?|YD/T|YD|JGJ|CECS)\s*\d{3,6}(?:\s*[-—]\s*\d{4})?\b",
        f"{file_name}\n{sample}",
        re.IGNORECASE,
    )
    standard_name_match = re.search(r"《([^》]{2,80})》", sample)
    total_chars = sum(len(page.strip()) for page in pages)
    parse_quality = "low" if total_chars < max(500, len(pages) * 80) else "normal"
    return {
        "standard_no": normalize_standard_no(standard_no_match.group(0)) if standard_no_match else "",
        "standard_name": standard_name_match.group(1).strip() if standard_name_match else "",
        "detection_methods": methods,
        "listed_clause_nos": listed_clause_nos,
        "listed_clause_refs": listed_clause_refs,
        "announcement_pages": announcement_pages,
        "bold_rule_pages": bold_rule_pages,
        "explicit_none_pages": explicit_none_pages,
        "explicit_none": bool(explicit_none_pages),
        "has_bold_rule": bool(bold_rule_pages),
        "bold_candidate_count": 0,
        "parse_quality": parse_quality,
        "total_text_chars": total_chars,
    }


def extract_candidates_from_pages(
    pages: list[str],
    *,
    listed_clause_nos: list[str],
    listed_clause_refs: list[dict[str, str]] | None = None,
    visual_bold_clause_nos: list[str] | None = None,
) -> list[dict[str, object]]:
    candidates: dict[str, dict[str, object]] = {}
    blocks = extract_clause_blocks(pages)
    visual_bold = set(visual_bold_clause_nos or [])
    references = normalize_clause_references(
        list(listed_clause_refs or []) or listed_clause_nos
    )
    for reference in references:
        clause_no = reference["clause_no"]
        item_no = reference.get("item_no") or ""
        block = blocks.get(clause_no)
        recovered = False
        if not block:
            shortened_no = ".".join(clause_no.split(".")[:-1])
            fallback = blocks.get(shortened_no)
            if fallback and looks_like_normative_clause(str(fallback.get("clause_text") or "")):
                block = fallback
                recovered = True
        if block and item_no:
            block = dict(block.get("_items", {}).get(item_no) or {})
        if block:
            from_vision = clause_no in visual_bold
            candidate = {
                **{key: value for key, value in block.items() if key != "_items"},
                "clause_no": clause_no,
                "item_no": item_no,
                "reference": reference_label(reference),
                "evidence_type": (
                    "announcement_and_body_ocr_recovered"
                    if recovered
                    else (
                        "announcement_and_bold_body"
                        if from_vision
                        else "announcement_and_body"
                    )
                ),
                "confidence": 0.9 if recovered else 0.98,
            }
            candidates[reference_key(reference)] = candidate

    for clause_no in visual_bold:
        block = blocks.get(clause_no)
        if not block:
            continue
        matching = [
            item for item in candidates.values() if item["clause_no"] == clause_no
        ]
        if matching:
            for item in matching:
                item["evidence_type"] = "announcement_and_bold_body"
                item["confidence"] = 0.99
        else:
            reference = {"clause_no": clause_no, "item_no": ""}
            candidates[reference_key(reference)] = {
                **{key: value for key, value in block.items() if key != "_items"},
                "item_no": "",
                "reference": clause_no,
                "evidence_type": "vision_bold_body_and_ocr",
                "confidence": 0.96,
            }
    return sorted(candidates.values(), key=candidate_sort_key)


def extract_clause_blocks(pages: list[str]) -> dict[str, dict[str, object]]:
    blocks: dict[str, dict[str, object]] = {}
    start_index, end_index = normative_body_range(pages)
    current_no = ""
    current_lines: list[tuple[int, str]] = []
    current_page_no = 0
    for page_no, page in enumerate(pages[start_index:end_index], start=start_index + 1):
        page = normalize_split_clause_numbers(page)
        for raw_line in page.splitlines():
            line = raw_line.strip()
            match = CLAUSE_LINE_PATTERN.match(line)
            if match:
                if current_no:
                    save_clause_block(blocks, current_no, current_lines, current_page_no)
                current_no = normalize_clause_no(match.group(1))
                current_lines = [(page_no, match.group(2).strip(" *_#"))]
                current_page_no = page_no
            elif current_no:
                if line.startswith("#"):
                    save_clause_block(blocks, current_no, current_lines, current_page_no)
                    current_no = ""
                    current_lines = []
                    current_page_no = 0
                elif line:
                    current_lines.append((page_no, line.strip(" *_")))
    if current_no:
        save_clause_block(blocks, current_no, current_lines, current_page_no)
    return blocks


def normalize_split_clause_numbers(value: str) -> str:
    pattern = re.compile(
        rf"(?m)^(\s*{OCR_DIGIT_SOURCE}{{1,2}}(?:\s*[.．。]\s*{OCR_DIGIT_SOURCE}{{1,2}})*\s*[.．。])"
        rf"\s*\n\s*({OCR_DIGIT_SOURCE}{{1,2}})(?=\s*(?:[.．。]|\s))"
    )
    while True:
        normalized = pattern.sub(r"\1\2", value)
        if normalized == value:
            return value
        value = normalized


def save_clause_block(
    blocks: dict[str, dict[str, object]],
    clause_no: str,
    lines: list[tuple[int, str]],
    page_no: int,
) -> None:
    useful_lines = [
        (line_page, value)
        for line_page, value in lines
        if value
        and not re.fullmatch(
            r"(?:[•·]\s*)?\d{1,3}(?:\s*[•·])?", value.strip()
        )
        and "移动通信集团设计院有限公司" not in value
        and not re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", value.strip())
    ]
    text = " ".join(value for _, value in useful_lines).replace("**", "").strip()
    if len(text) < 4:
        return
    if clause_no in blocks:
        previous = blocks[clause_no]
        previous_text = str(previous.get("clause_text") or "")
        if text not in previous_text:
            previous["clause_text"] = f"{previous_text} {text}".strip()[:6000]
        return
    blocks[clause_no] = {
        "clause_no": clause_no,
        "clause_text": text[:6000],
        "page_no": page_no,
        "_items": extract_numbered_items(useful_lines),
    }


def extract_numbered_items(
    lines: list[tuple[int, str]],
) -> dict[str, dict[str, object]]:
    items: dict[str, dict[str, object]] = {}
    current_no = ""
    current_page = 0
    parts: list[str] = []
    for page_no, line in lines:
        match = ITEM_LINE_PATTERN.match(line)
        if match:
            if current_no and parts:
                items[current_no] = {
                    "page_no": current_page,
                    "clause_text": " ".join(parts).strip()[:6000],
                }
            current_no = match.group("item")
            current_page = page_no
            parts = [match.group("text").strip()]
        elif current_no:
            parts.append(line)
    if current_no and parts:
        items[current_no] = {
            "page_no": current_page,
            "clause_text": " ".join(parts).strip()[:6000],
        }
    return items


def looks_like_normative_clause(value: str) -> bool:
    if len(value.strip()) < 16:
        return False
    return bool(re.search(r"必须|应当|应|不得|严禁|不应|宜|可按|应符合|应采用|应进行", value))


def continuation_pages_to_refine(
    pages: list[str],
    candidates: list[dict[str, object]],
    already_refined: list[int],
) -> list[int]:
    page_nos: set[int] = set()
    footer_pattern = r"\n\s*(?:[•·]\s*)?\d{1,3}(?:\s*[•·])?\s*$"
    for candidate in candidates:
        page_no = int(candidate.get("page_no") or 0)
        if page_no <= 0 or page_no >= len(pages):
            continue
        page_text = pages[page_no - 1].rstrip()
        without_footer = re.sub(footer_pattern, "", page_text).rstrip()
        content_ending = without_footer.rstrip("*_># ")
        if re.search(footer_pattern, page_text) and content_ending:
            last_char = content_ending[-1]
            if last_char not in "。；：.!?！？）)|":
                page_nos.add(page_no + 1)
    return sorted(page_no for page_no in page_nos if page_no not in already_refined)


def select_clauses_for_question(
    clauses: list[dict[str, object]], question: str
) -> list[dict[str, object]]:
    requested = {normalize_clause_no(value) for value in CLAUSE_NO_PATTERN.findall(question)}
    requested_item = re.search(r"第\s*(\d{1,2})\s*款", question)
    if requested:
        selected = [item for item in clauses if str(item.get("clause_no")) in requested]
        if requested_item:
            selected = [
                item
                for item in selected
                if str(item.get("item_no") or "") == requested_item.group(1)
            ]
    else:
        chapter_match = re.search(r"第\s*(\d{1,2})\s*章", question)
        if chapter_match:
            prefix = f"{chapter_match.group(1)}."
            selected = [item for item in clauses if str(item.get("clause_no", "")).startswith(prefix)]
        else:
            selected = clauses
    return [
        {
            **item,
            "clause_text": str(item.get("clause_text") or "")[:900],
        }
        for item in selected[:80]
    ]


def inspection_result(extraction_run: ClauseExtractionRun) -> dict[str, object]:
    inspection = dict((extraction_run.result_json or {}).get("inspection") or {})
    return {
        "extraction_run_id": extraction_run.id,
        "file_name": extraction_run.file_name,
        "page_count": extraction_run.page_count,
        "detection_methods": list(extraction_run.detection_methods or []),
        "listed_clause_count": len(
            inspection.get("listed_clause_refs")
            or inspection.get("listed_clause_nos")
            or []
        ),
        "bold_candidate_count": int(inspection.get("bold_candidate_count") or 0),
        "parse_quality": inspection.get("parse_quality"),
        "status": extraction_run.status,
    }


def extraction_result(extraction_run: ClauseExtractionRun) -> dict[str, object]:
    result = dict(extraction_run.result_json or {})
    return {
        "extraction_run_id": extraction_run.id,
        "file_name": extraction_run.file_name,
        "clause_count": extraction_run.clause_count,
        "missing_clause_nos": list(result.get("missing_clause_nos") or []),
        "status": extraction_run.status,
    }


def verification_result(extraction_run: ClauseExtractionRun) -> dict[str, object]:
    result = dict(extraction_run.result_json or {})
    return {
        **extraction_result(extraction_run),
        "mandatory_status": extraction_run.mandatory_status,
        "requires_review": bool(result.get("requires_review")),
        "warnings": list(result.get("warnings") or []),
    }


def clause_extraction_state_dict(extraction_run: ClauseExtractionRun) -> dict[str, object]:
    result = dict(extraction_run.result_json or {})
    inspection = dict(result.get("inspection") or {})
    return {
        "extraction_run_id": extraction_run.id,
        "status": extraction_run.status,
        "file_name": extraction_run.file_name,
        "mandatory_status": extraction_run.mandatory_status,
        "detection_methods": list(extraction_run.detection_methods or []),
        "page_count": extraction_run.page_count,
        "clause_count": extraction_run.clause_count,
        "listed_clause_count": len(
            inspection.get("listed_clause_refs")
            or inspection.get("listed_clause_nos")
            or []
        ),
        "missing_clause_count": len(result.get("missing_clause_nos") or []),
        "requires_review": bool(result.get("requires_review")),
        "error_message": extraction_run.error_message,
    }


def clause_extraction_result_dict(extraction_run: ClauseExtractionRun) -> dict[str, object]:
    result = dict(extraction_run.result_json or {})
    clauses = list(result.get("clauses") or [])
    trace = list(extraction_run.decision_trace or [])
    if extraction_run.status == "completed":
        if extraction_run.mandatory_status == "present":
            message = f"已自动识别并验证 {len(clauses)} 条强制性条文。"
        elif extraction_run.mandatory_status == "confirmed_none":
            message = "PDF 中存在明确无强制性条文的依据。"
        else:
            message = "PDF 中未识别到强制性条文，结论仍应结合原文复核。"
    else:
        message = "已完成自动抽取，但部分条号或粗体证据需要人工复核。"
    return {
        "status": "completed" if extraction_run.status == "completed" else "partial",
        "extraction_run_id": extraction_run.id,
        "file_name": extraction_run.file_name,
        "mandatory_status": extraction_run.mandatory_status,
        "detection_methods": list(extraction_run.detection_methods or []),
        "page_count": extraction_run.page_count,
        "clause_count": len(clauses),
        "clauses": clauses,
        "missing_clause_nos": list(result.get("missing_clause_nos") or []),
        "warnings": list(result.get("warnings") or []),
        "llm_decision_count": sum(1 for item in trace if item.get("actor") == "llm"),
        "tool_call_count": sum(1 for item in trace if item.get("actor") == "tool"),
        "agent_trace": trace,
        "message": message,
    }


def save_parsed_pages(extraction_run_id: int, pages: list[str]) -> Path:
    directory = BACKEND_ROOT / "data" / "clause_extractions" / str(extraction_run_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "pages.json"
    path.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    return path


def load_parsed_pages(path_text: str) -> list[str]:
    if not path_text:
        raise ValueError("强条抽取任务缺少解析页缓存")
    value = json.loads(Path(path_text).read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("强条抽取页缓存格式无效")
    return [str(item) for item in value]


def find_reusable_parsed_pages(
    *,
    file_hash: str,
    owner_user_id: int,
    expected_page_count: int,
    exclude_run_id: int,
) -> tuple[int, list[str]] | None:
    with SessionLocal() as session:
        previous_runs = (
            session.query(ClauseExtractionRun)
            .filter(
                ClauseExtractionRun.owner_user_id == owner_user_id,
                ClauseExtractionRun.file_hash == file_hash,
                ClauseExtractionRun.id != exclude_run_id,
                ClauseExtractionRun.page_count == expected_page_count,
                ClauseExtractionRun.parsed_pages_path.isnot(None),
            )
            .order_by(ClauseExtractionRun.id.desc())
            .all()
        )
        cached_paths = [
            (int(item.id), str(item.parsed_pages_path or ""))
            for item in previous_runs
        ]

    for run_id, path_text in cached_paths:
        try:
            pages = load_parsed_pages(path_text)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if parsed_pages_are_usable(pages, expected_page_count):
            return run_id, pages
    return None


def parsed_pages_are_usable(pages: list[str], expected_page_count: int) -> bool:
    if len(pages) != expected_page_count:
        return False
    nonempty_count = sum(bool(page.strip()) for page in pages)
    total_chars = sum(len(page.strip()) for page in pages)
    return (
        nonempty_count >= max(1, expected_page_count // 2)
        and total_chars >= max(500, expected_page_count * 80)
    )


def get_owned_run(
    session,
    extraction_run_id: int,
    owner_user_id: int,
    *,
    for_update: bool = False,
) -> ClauseExtractionRun:
    query = session.query(ClauseExtractionRun).filter(
        ClauseExtractionRun.id == extraction_run_id,
        ClauseExtractionRun.owner_user_id == owner_user_id,
    )
    if for_update:
        query = query.with_for_update()
    extraction_run = query.first()
    if not extraction_run:
        raise ValueError("强条抽取任务不存在或不属于当前访客")
    return extraction_run


def get_owned_agent_session(
    session, session_id: int | None, owner_user_id: int
) -> AgentSession | None:
    if not session_id:
        return None
    agent_session = (
        session.query(AgentSession)
        .filter(AgentSession.id == session_id, AgentSession.owner_user_id == owner_user_id)
        .first()
    )
    if not agent_session:
        raise ValueError("Agent 会话不存在或不属于当前访客")
    return agent_session


def require_status(extraction_run: ClauseExtractionRun, *allowed: str) -> None:
    if extraction_run.status not in allowed:
        raise ValueError(
            f"强条抽取任务当前状态为 {extraction_run.status}，此操作仅允许状态：{', '.join(allowed)}"
        )


def normalize_clause_no(value: str) -> str:
    clean = re.sub(r"\s+", "", value).replace("．", ".").replace("。", ".")
    return clean.translate(str.maketrans({"O": "0", "I": "1", "l": "1", "J": "1"}))


def normalize_clause_references(values: list[object]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            clause_no = normalize_clause_no(str(value.get("clause_no") or ""))
            item_no = str(value.get("item_no") or "").strip()
        else:
            clause_no, _, item_no = str(value).partition("#")
            clause_no = normalize_clause_no(clause_no)
        reference = {"clause_no": clause_no, "item_no": item_no}
        key = reference_key(reference)
        if clause_no and key not in seen:
            output.append(reference)
            seen.add(key)
    return output


def extract_announcement_references(value: str) -> list[dict[str, str]]:
    compact = re.sub(r"\s+", "", value)
    output: list[dict[str, str]] = []
    for end in re.finditer(r"为强制性条文", compact):
        prefix = compact[: end.start()]
        start = max(
            prefix.rfind("其中"),
            prefix.rfind("黑体字标注的"),
            prefix.rfind("粗体字标注的"),
        )
        segment = prefix[start if start >= 0 else max(0, len(prefix) - 600) :]
        for match in ANNOUNCEMENT_REF_PATTERN.finditer(segment):
            clause_no = normalize_clause_no(match.group("clause"))
            items = re.split(r"[,，、]", match.group("items") or "")
            output.extend(
                {"clause_no": clause_no, "item_no": item_no}
                for item_no in (items or [""])
                if item_no or not match.group("items")
            )
    return normalize_clause_references(output)


def reference_key(reference: dict[str, str]) -> str:
    return f"{reference['clause_no']}#{reference.get('item_no') or ''}"


def reference_label(reference: dict[str, str]) -> str:
    item_no = reference.get("item_no") or ""
    return f"{reference['clause_no']} 第{item_no}款" if item_no else reference["clause_no"]


def reference_sort_key(reference: dict[str, str]) -> tuple[tuple[int, ...], int]:
    item_no = reference.get("item_no") or "0"
    return clause_sort_key(reference["clause_no"]), int(item_no)


def candidate_reference_key(candidate: dict[str, object]) -> str:
    return reference_key(
        {
            "clause_no": str(candidate.get("clause_no") or ""),
            "item_no": str(candidate.get("item_no") or ""),
        }
    )


def candidate_sort_key(candidate: dict[str, object]) -> tuple[tuple[int, ...], int]:
    return reference_sort_key(
        {
            "clause_no": str(candidate.get("clause_no") or ""),
            "item_no": str(candidate.get("item_no") or ""),
        }
    )


def extract_clause_numbers(value: str) -> list[str]:
    flexible = re.compile(rf"(?<![0-9OIlJ])({FLEXIBLE_CLAUSE_NO_SOURCE})(?![0-9OIlJ])")
    return [normalize_clause_no(item) for item in flexible.findall(value)]


def normative_body_range(pages: list[str]) -> tuple[int, int]:
    start_index = 0
    for index, page in enumerate(pages):
        heading = re.search(r"(?m)^\s*#*\s*(?:1\s+)?总\s*则\s*$", page)
        if heading and CLAUSE_LINE_PATTERN.search(page):
            start_index = index
            break

    end_index = len(pages)
    for index in range(start_index + 1, len(pages)):
        page_start = pages[index][:600]
        if "条文说明" in page_start and ("中华人民共和国" in page_start or "# 条文说明" in page_start):
            end_index = index
            break
    return start_index, end_index


def display_file_name(value: str) -> str:
    return re.sub(r"^[0-9a-f]{32}_", "", value, flags=re.IGNORECASE)


def normalize_standard_no(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("—", "-")).strip().upper()


def clause_sort_key(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(item) for item in value.split("."))
    except ValueError:
        return (9999,)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def shorten(value: str) -> str:
    clean = " ".join(value.split()).strip() or "强条抽取"
    return clean if len(clean) <= 30 else f"{clean[:30]}…"
