import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import BACKEND_ROOT
from app.db.database import SessionLocal
from app.db.models import AgentSession, CheckIssue, CheckRun, WordDocument, WordEditRun, WordReference
from app.services.word_check import check_word_document, issue_sort_key, issue_to_dict
from app.services.word_editor import apply_word_changes, resolve_word_document_path


EDITABLE_SCOPES = ("basis_excel", "body_basis")
EDITABLE_SEVERITIES = ("warning", "high")
TERMINAL_STATUSES = ("completed", "manual_review", "failed")


def start_word_edit_run(
    *,
    document_id: int,
    owner_user_id: int,
    session_id: int | None = None,
    task_id: int | None = None,
    episode_id: int | None = None,
) -> dict[str, object]:
    """Create the single durable memory record used by one Word-edit Agent loop."""
    with SessionLocal() as session:
        document = get_owned_document(session, document_id, owner_user_id)
        agent_session = None
        if session_id is not None:
            agent_session = get_owned_agent_session(session, session_id, owner_user_id)
            if not agent_session:
                raise ValueError("Agent 会话不存在或不属于当前访客")
        edit_run = WordEditRun(
            owner_user_id=owner_user_id,
            session_id=session_id,
            task_id=task_id,
            episode_id=episode_id,
            source_document_id=document.id,
            source_check_run_id=latest_check_run_id(session, document.id, session_id, owner_user_id),
            status="planning",
            changes=[],
        )
        session.add(edit_run)
        session.flush()
        if agent_session:
            agent_session.active_edit_run_id = edit_run.id
        session.commit()
        session.refresh(edit_run)
        return word_edit_state_dict(edit_run, document)


def inspect_consistency_issues(*, edit_run_id: int, owner_user_id: int) -> dict[str, object]:
    """Inspect the current working document and return the next Agent observation."""
    with SessionLocal() as session:
        edit_run = get_owned_edit_run(session, edit_run_id, owner_user_id, for_update=True)
        if edit_run.status == "awaiting_plan":
            return inspection_result(session, edit_run)
        require_status(edit_run, "planning")
        document_id = current_document_id(edit_run)
        document = get_owned_document(session, document_id, owner_user_id)
        edit_run.status = "inspecting"
        session.flush()

        with SessionLocal() as check_session:
            inspection = check_word_document(
                check_session,
                document_id=document_id,
                publish_date=document.declared_publish_date,
                replace=True,
                check_scope="all",
                issue_limit=0,
            )
        inspection_run = CheckRun(
            owner_user_id=owner_user_id,
            session_id=edit_run.session_id,
            task_id=edit_run.task_id,
            episode_id=edit_run.episode_id,
            document_id=document_id,
            run_type="word_check",
            user_message="Word Agent Loop 初始一致性检查",
            tool_plan={"steps": [{"tool": "inspect_consistency_issues_tool", "args": {"edit_run_id": edit_run_id}}]},
            tool_results=[{"tool": "word_check_tool", "result": inspection}],
            answer=f"初始检查完成，发现 {inspection.get('issue_count', 0)} 个问题。",
            status="completed",
            finished_at=datetime.now(timezone.utc),
            issue_count=int(inspection.get("issue_count") or 0),
        )
        session.add(inspection_run)
        session.flush()
        require_status(edit_run, "inspecting")
        edit_run.source_check_run_id = inspection_run.id
        edit_run.status = "awaiting_plan"
        session.commit()
        return inspection_result(session, edit_run)


def prepare_word_edit(
    *,
    edit_run_id: int,
    owner_user_id: int,
    selected_issue_ids: list[int],
    expected_document_id: int,
) -> dict[str, object]:
    """Append a trusted change batch to WordEditRun.changes without creating a new run."""
    selected_issue_ids = list(dict.fromkeys(int(value) for value in selected_issue_ids))
    if not selected_issue_ids:
        raise ValueError("修订计划没有选择任何问题")
    with SessionLocal() as session:
        edit_run = get_owned_edit_run(session, edit_run_id, owner_user_id, for_update=True)
        document_id = current_document_id(edit_run)
        if document_id != expected_document_id:
            raise ValueError("文档状态已经变化，请基于最新复检结果重新规划")
        get_owned_document(session, document_id, owner_user_id)

        changes = [dict(item) for item in list(edit_run.changes or [])]
        pending = [item for item in changes if item.get("status") == "pending"]
        if pending:
            pending_issue_ids = {int(item.get("issue_id") or 0) for item in pending}
            if edit_run.status == "ready" and pending_issue_ids == set(selected_issue_ids):
                return prepared_result(edit_run, document_id, selected_issue_ids, pending)
            raise ValueError("当前修订任务仍有另一批待执行的 changes")
        require_status(edit_run, "awaiting_plan", "awaiting_decision")

        issues = (
            session.query(CheckIssue)
            .filter(
                CheckIssue.document_id == document_id,
                CheckIssue.id.in_(selected_issue_ids),
                CheckIssue.check_scope.in_(EDITABLE_SCOPES),
                CheckIssue.severity.in_(EDITABLE_SEVERITIES),
            )
            .all()
        )
        issues = sorted(issues, key=issue_sort_key)
        accepted_ids = {issue.id for issue in issues}
        rejected_ids = [issue_id for issue_id in selected_issue_ids if issue_id not in accepted_ids]
        if rejected_ids:
            raise ValueError(f"以下问题已失效或不可自动修改：{rejected_ids}")
        cycle = next_cycle(changes)
        planned = build_changes(
            session,
            edit_run_id=edit_run.id,
            issues=issues,
            cycle=cycle,
            input_document_id=document_id,
        )
        attempted = {
            str(item.get("semantic_fingerprint") or "")
            for item in changes
            if item.get("semantic_fingerprint")
        }
        planned = [item for item in planned if item.get("semantic_fingerprint") not in attempted]
        if not planned:
            raise ValueError("所选问题没有新的可定位修改，可能与已尝试 changes 重复")
        edit_run.changes = changes + planned
        edit_run.status = "ready"
        session.commit()
        return prepared_result(edit_run, document_id, selected_issue_ids, planned)


def apply_word_edit(*, edit_run_id: int, owner_user_id: int) -> dict[str, object]:
    """Apply only the currently pending change batch to the latest Word copy."""
    with SessionLocal() as session:
        edit_run = get_owned_edit_run(session, edit_run_id, owner_user_id, for_update=True)
        changes = [dict(item) for item in list(edit_run.changes or [])]
        pending = [item for item in changes if item.get("status") == "pending"]
        if not pending:
            cycle = latest_cycle(changes)
            cycle_changes = [item for item in changes if int(item.get("cycle") or 1) == cycle]
            if edit_run.output_document_id and any(item.get("output_document_id") for item in cycle_changes):
                document = get_owned_document(session, current_document_id(edit_run), owner_user_id)
                return word_edit_action_result(edit_run, document.file_name, changes, cycle)
            require_status(edit_run, "ready")
            document = get_owned_document(session, current_document_id(edit_run), owner_user_id)
            return word_edit_action_result(edit_run, document.file_name, changes, cycle)

        require_status(edit_run, "ready")

        cycle = max(int(item.get("cycle") or 1) for item in pending)
        batch = [item for item in pending if int(item.get("cycle") or 1) == cycle]
        input_ids = {int(item.get("input_document_id") or 0) for item in batch}
        if len(input_ids) != 1 or 0 in input_ids:
            raise ValueError("当前 changes 缺少唯一的输入文档")
        input_document_id = input_ids.pop()
        if input_document_id != current_document_id(edit_run):
            raise ValueError("当前 changes 已过期，请重新检查并规划")

        document = get_owned_document(session, input_document_id, owner_user_id)
        publish_date = document.declared_publish_date
        source_path = resolve_word_document_path(document)
        output_name = f"{Path(document.file_name).stem}{revision_suffix(cycle)}.docx"
        output_path = BACKEND_ROOT / "data" / "edits" / str(edit_run.id) / f"cycle-{cycle}" / output_name
        edit_run.status = "applying"
        session.flush()

        try:
            applied_batch = apply_word_changes(source_path, output_path, batch)
        except Exception as exc:
            failed_at = utc_now()
            for item in batch:
                item["status"] = "failed"
                item["error"] = str(exc)
                item["applied_at"] = failed_at
            merged = merge_change_batch(changes, batch)
            edit_run.changes = merged
            edit_run.status = "failed"
            edit_run.error_message = str(exc)
            session.commit()
            return word_edit_action_result(edit_run, document.file_name, merged, cycle)

        applied_count = count_change_status(applied_batch, "applied")
        if applied_count == 0:
            applied_at = utc_now()
            for item in applied_batch:
                item["applied_at"] = applied_at
                item.setdefault("error", "")
            changes = merge_change_batch(changes, applied_batch)
            edit_run.changes = changes
            edit_run.status = "failed"
            edit_run.error_message = "本轮没有任何修改成功写入"
            session.commit()
            return word_edit_action_result(edit_run, document.file_name, changes, cycle)

        from app.agent.tools import parse_word_tool

        try:
            parse_result = parse_word_tool(
                file_path=str(output_path),
                owner_user_id=owner_user_id,
                edit_run_id=edit_run.id,
                edit_cycle=cycle,
            )
            output_document_id = int(parse_result["document_id"])
        except Exception as exc:
            failed_at = utc_now()
            for item in applied_batch:
                item["status"] = "failed"
                item["error"] = f"修订副本解析失败：{exc}"
                item["applied_at"] = failed_at
            changes = merge_change_batch(changes, applied_batch)
            edit_run.changes = changes
            edit_run.status = "failed"
            edit_run.error_message = str(exc)
            session.commit()
            return word_edit_action_result(edit_run, output_name, changes, cycle)

        output_document = get_owned_document(session, output_document_id, owner_user_id)
        output_document.declared_publish_date = publish_date
        applied_at = utc_now()
        for item in applied_batch:
            item["applied_at"] = applied_at
            item["output_document_id"] = output_document_id
            item.setdefault("error", "")
        changes = merge_change_batch(changes, applied_batch)
        edit_run.changes = changes
        edit_run.output_document_id = output_document_id
        edit_run.verification_run_id = None
        edit_run.status = "applied"
        edit_run.error_message = ""
        session.commit()
        return word_edit_action_result(edit_run, output_document.file_name, changes, cycle)


def verify_word_edit(*, edit_run_id: int, owner_user_id: int) -> dict[str, object]:
    """Recheck the latest copy and return an observation; the Agent decides what follows."""
    with SessionLocal() as session:
        edit_run = get_owned_edit_run(session, edit_run_id, owner_user_id, for_update=True)
        if not edit_run.output_document_id:
            raise ValueError("修订任务尚未生成 Word 副本")

        output_document = get_owned_document(session, edit_run.output_document_id, owner_user_id)
        cycle = latest_cycle(list(edit_run.changes or []))
        if edit_run.status == "awaiting_decision" and edit_run.verification_run_id:
            return verification_result(session, edit_run, output_document, cycle)
        require_status(edit_run, "applied")
        edit_run.status = "verifying"
        session.flush()
        with SessionLocal() as check_session:
            verification = check_word_document(
                check_session,
                document_id=output_document.id,
                publish_date=output_document.declared_publish_date,
                replace=True,
                check_scope="all",
                issue_limit=0,
            )
        require_status(edit_run, "verifying")
        verification_run = CheckRun(
            owner_user_id=owner_user_id,
            session_id=edit_run.session_id,
            task_id=edit_run.task_id,
            episode_id=edit_run.episode_id,
            document_id=output_document.id,
            run_type="word_check",
            user_message="Word Agent Loop 修订后复检",
            tool_plan={"steps": [{"tool": "verify_word_edit_tool", "args": {"edit_run_id": edit_run.id}}]},
            tool_results=[{"tool": "word_check_tool", "result": verification}],
            answer="Word Agent Loop 修订后复检完成。",
            status="completed",
            finished_at=datetime.now(timezone.utc),
            issue_count=int(verification.get("issue_count") or 0),
        )
        session.add(verification_run)
        session.flush()

        verified_at = utc_now()
        changes = [dict(item) for item in list(edit_run.changes or [])]
        for item in changes:
            if int(item.get("cycle") or 1) == cycle:
                item["verification_run_id"] = verification_run.id
                item["verification_status"] = "checked"
                item["verified_at"] = verified_at
        edit_run.changes = changes
        edit_run.verification_run_id = verification_run.id
        edit_run.status = "awaiting_decision"
        session.commit()
        return verification_result(session, edit_run, output_document, cycle)


def get_word_edit_state(*, edit_run_id: int, owner_user_id: int) -> dict[str, object]:
    """Reload loop memory from PostgreSQL before every LLM decision."""
    with SessionLocal() as session:
        edit_run = get_owned_edit_run(session, edit_run_id, owner_user_id)
        document = get_owned_document(session, current_document_id(edit_run), owner_user_id)
        return word_edit_state_dict(edit_run, document)


def inspection_result(session, edit_run: WordEditRun) -> dict[str, object]:
    document_id = current_document_id(edit_run)
    issues = consistency_issues(session, document_id)
    items = [editable_issue_dict(session, issue) for issue in issues]
    return {
        "edit_run_id": edit_run.id,
        "document_id": document_id,
        "issue_count": len(items),
        "auto_fixable_issue_count": sum(1 for item in items if item["auto_fixable"]),
        "issues": items,
    }


def prepared_result(
    edit_run: WordEditRun,
    document_id: int,
    selected_issue_ids: list[int],
    batch: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "edit_run_id": edit_run.id,
        "document_id": document_id,
        "cycle": max((int(item.get("cycle") or 1) for item in batch), default=0),
        "selected_issue_ids": selected_issue_ids,
        "planned_count": len(batch),
        "changes": batch,
        "status": edit_run.status,
    }


def verification_result(
    session,
    edit_run: WordEditRun,
    output_document: WordDocument,
    cycle: int,
) -> dict[str, object]:
    changes = [dict(item) for item in list(edit_run.changes or [])]
    remaining = consistency_issues(session, output_document.id)
    remaining_items = [editable_issue_dict(session, issue) for issue in remaining]
    return {
        **word_edit_action_result(edit_run, output_document.file_name, changes, cycle),
        "remaining_issue_count": len(remaining_items),
        "auto_fixable_issue_count": sum(1 for item in remaining_items if item["auto_fixable"]),
        "remaining_issues": remaining_items,
        "verification_run_id": edit_run.verification_run_id,
    }


def finalize_word_edit_run(
    *,
    edit_run_id: int,
    owner_user_id: int,
    remaining_issues: list[dict[str, object]],
    action: str,
    reason: str,
) -> dict[str, object]:
    """Close the loop explicitly after the Agent chooses finish or manual review."""
    del remaining_issues
    if action not in ("finish", "manual_review"):
        raise ValueError("Word Agent Loop 终止动作无效")
    with SessionLocal() as session:
        edit_run = get_owned_edit_run(session, edit_run_id, owner_user_id, for_update=True)
        changes = [dict(item) for item in list(edit_run.changes or [])]
        if any(item.get("status") == "pending" for item in changes) or edit_run.status in ("applying", "verifying"):
            raise ValueError("仍有修改或复检任务正在执行，不能结束 Agent Loop")
        if edit_run.status == "completed" and action != "finish":
            raise ValueError("已完成的 Word 修订任务不能改为人工处理")
        if edit_run.status == "manual_review" and action != "manual_review":
            raise ValueError("已转人工的 Word 修订任务不能重新标记完成")
        final_document_id = current_document_id(edit_run)
        document = get_owned_document(session, final_document_id, owner_user_id)
        remaining_issues = [editable_issue_dict(session, issue) for issue in consistency_issues(session, final_document_id)]
        if action == "finish":
            require_status(edit_run, "awaiting_plan", "awaiting_decision", "completed")
            if remaining_issues:
                raise ValueError("当前文档仍有一致性问题，不能标记为完成")
            if edit_run.output_document_id and not edit_run.verification_run_id:
                raise ValueError("修订副本尚未复检，不能标记为完成")
        if action == "manual_review" and edit_run.status == "applied":
            raise ValueError("修订副本尚未复检，不能结束 Agent Loop")
        completed = (
            action == "finish"
            and not remaining_issues
            and count_change_status(changes, "failed") == 0
        )
        if action == "finish" and not completed:
            raise ValueError("仍有失败的 changes，不能标记为完成")
        edit_run.status = "completed" if completed else "manual_review"

        if edit_run.session_id:
            agent_session = get_owned_agent_session(session, edit_run.session_id, owner_user_id)
            if agent_session:
                agent_session.active_document_id = final_document_id
                agent_session.active_edit_run_id = edit_run.id
                if edit_run.verification_run_id:
                    agent_session.last_word_check_run_id = edit_run.verification_run_id

        session.commit()
        generated_copy = bool(edit_run.output_document_id and edit_run.output_document_id != edit_run.source_document_id)
        if completed and generated_copy:
            message = "Word Agent Loop 已完成修改并复检通过，已生成修订副本。"
        elif completed:
            message = "当前文档没有需要自动修改的一致性警告或高风险问题。"
        elif generated_copy and remaining_issues:
            message = f"Word Agent Loop 已生成修订副本，仍有 {len(remaining_issues)} 个问题需要人工处理。"
        elif generated_copy:
            message = "Word Agent Loop 已生成并复检修订副本，但仍需人工确认修改结果。"
        else:
            message = f"发现 {len(remaining_issues)} 个问题，但没有可安全写入的修改，已转人工处理。"
        if reason:
            message = f"{message} 决策原因：{reason}"

        return {
            "status": "completed" if completed else "partial",
            "source_document_id": edit_run.source_document_id,
            "document_id": final_document_id,
            "output_document_id": edit_run.output_document_id if generated_copy else None,
            "output_file_name": document.file_name if generated_copy else "",
            "download_url": f"/word/documents/{final_document_id}/download" if generated_copy else "",
            "edit_run_id": edit_run.id,
            "edit_run_ids": [edit_run.id],
            "attempt_count": applied_cycle_count(changes),
            "planned_count": len(changes),
            "applied_count": count_change_status(changes, "applied"),
            "failed_count": count_change_status(changes, "failed"),
            "remaining_issue_count": len(remaining_issues),
            "remaining_issues": remaining_issues[:50],
            "changes": changes,
            "passes": summarize_cycles(changes),
            "message": message,
            "final_action": action,
        }


def fail_word_edit_run(*, edit_run_id: int, owner_user_id: int, error_message: str) -> None:
    with SessionLocal() as session:
        edit_run = get_owned_edit_run(session, edit_run_id, owner_user_id, for_update=True)
        if edit_run.status not in TERMINAL_STATUSES:
            edit_run.status = "failed"
            edit_run.error_message = error_message
            session.commit()


def build_changes(
    session,
    *,
    edit_run_id: int,
    issues: list[CheckIssue],
    cycle: int,
    input_document_id: int,
) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    seen: set[tuple[int, str]] = set()
    planned_at = utc_now()
    for issue in issues:
        reference = session.get(WordReference, issue.word_reference_id)
        if not reference:
            continue
        locator = dict(reference.locator or {})
        fix_data = dict(issue.fix_data or {})
        for replacement in fix_data.get("replacements") or []:
            target = str(replacement.get("target") or "")
            span = locator.get(target)
            after = str(replacement.get("after") or "")
            key = (reference.id, target)
            if key in seen or not isinstance(span, dict) or not after:
                continue
            seen.add(key)
            before = str(span.get("text") or replacement.get("before") or "")
            base_locator = {key: value for key, value in locator.items() if key not in ("standard_no", "standard_name")}
            fingerprint = change_fingerprint(
                input_document_id=input_document_id,
                locator=base_locator,
                target=target,
                before=before,
                after=after,
            )
            changes.append(
                {
                    "schema_version": 2,
                    "change_id": f"{edit_run_id}:{cycle}:{fingerprint[:16]}",
                    "issue_fingerprint": fingerprint,
                    "semantic_fingerprint": change_fingerprint(
                        input_document_id=0,
                        locator=base_locator,
                        target=target,
                        before=before,
                        after=after,
                    ),
                    "cycle": cycle,
                    "input_document_id": input_document_id,
                    "output_document_id": None,
                    "verification_run_id": None,
                    "verification_status": "pending",
                    "issue_id": issue.id,
                    "word_reference_id": reference.id,
                    "issue_type": issue.issue_type,
                    "severity": issue.severity,
                    "target": target,
                    "before": before,
                    "after": after,
                    "locator": base_locator,
                    "span": dict(span),
                    "status": "pending",
                    "error": "",
                    "planned_at": planned_at,
                }
            )
    return changes


def editable_issue_dict(session, issue: CheckIssue) -> dict[str, object]:
    reference = session.get(WordReference, issue.word_reference_id)
    locator = dict(reference.locator or {}) if reference else {}
    fix_data = dict(issue.fix_data or {})
    replacements = list(fix_data.get("replacements") or [])
    located_replacements = [
        replacement
        for replacement in replacements
        if isinstance(locator.get(str(replacement.get("target") or "")), dict)
    ]
    return {
        **issue_to_dict(issue),
        "auto_fixable": bool(located_replacements),
        "proposed_replacements": located_replacements,
    }


def consistency_issues(session, document_id: int) -> list[CheckIssue]:
    issues = (
        session.query(CheckIssue)
        .filter(
            CheckIssue.document_id == document_id,
            CheckIssue.check_scope.in_(EDITABLE_SCOPES),
            CheckIssue.severity.in_(EDITABLE_SEVERITIES),
        )
        .all()
    )
    return sorted(issues, key=issue_sort_key)


def latest_check_run_id(
    session,
    document_id: int,
    session_id: int | None,
    owner_user_id: int,
) -> int | None:
    if session_id:
        agent_session = get_owned_agent_session(session, session_id, owner_user_id)
        if agent_session and agent_session.last_word_check_run_id:
            check_run = session.get(CheckRun, agent_session.last_word_check_run_id)
            if (
                check_run
                and check_run.owner_user_id == owner_user_id
                and check_run.document_id == document_id
                and check_run.run_type == "word_check"
            ):
                return check_run.id
    run = (
        session.query(CheckRun)
        .filter(
            CheckRun.document_id == document_id,
            CheckRun.owner_user_id == owner_user_id,
            CheckRun.run_type == "word_check",
            CheckRun.status.in_(["success", "completed"]),
        )
        .order_by(CheckRun.id.desc())
        .first()
    )
    return run.id if run else None


def get_owned_document(session, document_id: int, owner_user_id: int) -> WordDocument:
    document = session.get(WordDocument, document_id)
    if not document or document.owner_user_id != owner_user_id:
        raise ValueError("文档不存在或不属于当前访客")
    return document


def get_owned_edit_run(
    session,
    edit_run_id: int,
    owner_user_id: int,
    *,
    for_update: bool = False,
) -> WordEditRun:
    query = session.query(WordEditRun).filter(
        WordEditRun.id == edit_run_id,
        WordEditRun.owner_user_id == owner_user_id,
    )
    if for_update:
        query = query.with_for_update()
    edit_run = query.first()
    if not edit_run:
        raise ValueError("Word 修订任务不存在或不属于当前访客")
    return edit_run


def get_owned_agent_session(session, session_id: int, owner_user_id: int) -> AgentSession | None:
    return (
        session.query(AgentSession)
        .filter(AgentSession.id == session_id, AgentSession.owner_user_id == owner_user_id)
        .first()
    )


def current_document_id(edit_run: WordEditRun) -> int:
    return int(edit_run.output_document_id or edit_run.source_document_id)


def next_cycle(changes: list[dict[str, object]]) -> int:
    return latest_cycle(changes) + 1


def latest_cycle(changes: list[dict[str, object]]) -> int:
    return max((int(item.get("cycle") or 1) for item in changes), default=0)


def count_change_status(changes: list[dict[str, object]], status: str) -> int:
    return sum(1 for change in changes if change.get("status") == status)


def applied_cycle_count(changes: list[dict[str, object]]) -> int:
    return len(
        {
            int(item.get("cycle") or 1)
            for item in changes
            if item.get("applied_at") or item.get("status") in ("applied", "failed")
        }
    )


def require_status(edit_run: WordEditRun, *allowed: str) -> None:
    if edit_run.status not in allowed:
        raise ValueError(
            f"Word 修订任务当前状态为 {edit_run.status}，此操作仅允许状态：{', '.join(allowed)}"
        )


def merge_change_batch(
    changes: list[dict[str, object]],
    batch: list[dict[str, object]],
) -> list[dict[str, object]]:
    updates = {str(item.get("change_id")): dict(item) for item in batch}
    return [updates.get(str(item.get("change_id")), dict(item)) for item in changes]


def change_fingerprint(
    *,
    input_document_id: int,
    locator: dict[str, object],
    target: str,
    before: str,
    after: str,
) -> str:
    value = json.dumps(
        {
            "input_document_id": input_document_id,
            "locator": locator,
            "target": target,
            "before": before,
            "after": after,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def revision_suffix(cycle: int) -> str:
    if cycle == 1:
        return "-已修订"
    if cycle == 2:
        return "-二次修订"
    return f"-第{cycle}次修订"


def word_edit_action_result(
    edit_run: WordEditRun,
    output_file_name: str,
    changes: list[dict[str, object]],
    cycle: int,
) -> dict[str, object]:
    batch = [item for item in changes if int(item.get("cycle") or 1) == cycle]
    return {
        "edit_run_id": edit_run.id,
        "status": edit_run.status,
        "source_document_id": edit_run.source_document_id,
        "document_id": current_document_id(edit_run),
        "output_document_id": edit_run.output_document_id,
        "output_file_name": output_file_name if edit_run.output_document_id else "",
        "cycle": cycle,
        "planned_count": len(batch),
        "applied_count": count_change_status(batch, "applied"),
        "failed_count": count_change_status(batch, "failed"),
        "error_message": edit_run.error_message,
    }


def word_edit_state_dict(edit_run: WordEditRun, document: WordDocument) -> dict[str, object]:
    changes = [dict(item) for item in list(edit_run.changes or [])]
    cycle = latest_cycle(changes)
    return {
        "edit_run_id": edit_run.id,
        "status": edit_run.status,
        "source_document_id": edit_run.source_document_id,
        "document_id": current_document_id(edit_run),
        "output_document_id": edit_run.output_document_id,
        "output_file_name": document.file_name if edit_run.output_document_id else "",
        "verification_run_id": edit_run.verification_run_id,
        "cycle": cycle,
        "attempt_count": cycle,
        "planned_count": len(changes),
        "pending_count": count_change_status(changes, "pending"),
        "applied_count": count_change_status(changes, "applied"),
        "failed_count": count_change_status(changes, "failed"),
        "changes": changes,
        "error_message": edit_run.error_message,
    }


def summarize_cycles(changes: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "cycle": cycle,
            "planned_count": len(batch),
            "applied_count": count_change_status(batch, "applied"),
            "failed_count": count_change_status(batch, "failed"),
            "input_document_id": batch[0].get("input_document_id") if batch else None,
            "output_document_id": next((item.get("output_document_id") for item in batch if item.get("output_document_id")), None),
            "verification_run_id": next((item.get("verification_run_id") for item in batch if item.get("verification_run_id")), None),
        }
        for cycle in range(1, latest_cycle(changes) + 1)
        for batch in [[item for item in changes if int(item.get("cycle") or 1) == cycle]]
    ]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
