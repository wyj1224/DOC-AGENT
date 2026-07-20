from app.services.clause_extraction import (
    extract_clause_candidates,
    inspect_clause_pdf,
    verify_clause_candidates,
)


def inspect_clause_pdf_tool(
    extraction_run_id: int, owner_user_id: int
) -> dict[str, object]:
    return inspect_clause_pdf(
        extraction_run_id=extraction_run_id,
        owner_user_id=owner_user_id,
    )


def extract_clause_candidates_tool(
    extraction_run_id: int, owner_user_id: int
) -> dict[str, object]:
    return extract_clause_candidates(
        extraction_run_id=extraction_run_id,
        owner_user_id=owner_user_id,
    )


def verify_clause_candidates_tool(
    extraction_run_id: int, owner_user_id: int
) -> dict[str, object]:
    return verify_clause_candidates(
        extraction_run_id=extraction_run_id,
        owner_user_id=owner_user_id,
    )
