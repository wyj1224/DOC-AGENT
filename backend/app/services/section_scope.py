"""Shared section classification helpers for Word reference checks."""

BASIS_SECTION_KEYWORDS = ("设计依据", "编制依据")


def is_basis_section_title(section_title: str) -> bool:
    """Return True when a Word section should be treated as an evidence/basis section."""
    title = section_title or ""
    return any(keyword in title for keyword in BASIS_SECTION_KEYWORDS)


def basis_section_label() -> str:
    return "依据章节（设计依据/编制依据）"
