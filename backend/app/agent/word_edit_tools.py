from app.services.word_edit_workflow import (
    apply_word_edit,
    inspect_consistency_issues,
    prepare_word_edit,
    verify_word_edit,
)


def inspect_consistency_issues_tool(edit_run_id: int, owner_user_id: int) -> dict[str, object]:
    return inspect_consistency_issues(edit_run_id=edit_run_id, owner_user_id=owner_user_id)


def prepare_word_edit_tool(
    edit_run_id: int,
    owner_user_id: int,
    selected_issue_ids: list[int],
    expected_document_id: int,
) -> dict[str, object]:
    return prepare_word_edit(
        edit_run_id=edit_run_id,
        owner_user_id=owner_user_id,
        selected_issue_ids=selected_issue_ids,
        expected_document_id=expected_document_id,
    )


def apply_word_edit_tool(edit_run_id: int, owner_user_id: int) -> dict[str, object]:
    return apply_word_edit(edit_run_id=edit_run_id, owner_user_id=owner_user_id)


def verify_word_edit_tool(edit_run_id: int, owner_user_id: int) -> dict[str, object]:
    return verify_word_edit(edit_run_id=edit_run_id, owner_user_id=owner_user_id)
