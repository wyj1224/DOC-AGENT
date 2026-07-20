from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, default="", nullable=False)


class MandatoryClause(Base, TimestampMixin):
    __tablename__ = "mandatory_clauses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    standard_no: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    standard_name: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    applicable_scope: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mandatory_count: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    mandatory_type: Mapped[str] = mapped_column(String(32), default="条文", nullable=False)
    clause_no: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    clause_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_file: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        Index("ix_mandatory_clauses_standard_clause", "standard_no", "clause_no"),
        Index("ix_mandatory_clauses_type", "mandatory_type"),
    )


class StandardValidityRecord(Base, TimestampMixin):
    __tablename__ = "standard_validity_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    old_standard_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    new_standard_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    new_publish_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    new_effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    involved_content: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    verified_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_file: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        Index("ix_standard_validity_effective_date", "new_effective_date"),
    )


class KnowledgeDocument(Base, TimestampMixin):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    parse_status: Mapped[str] = mapped_column(String(32), default="parsing", nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (
        Index("ix_knowledge_documents_status", "parse_status"),
    )


class WordDocument(Base, TimestampMixin):
    __tablename__ = "word_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    declared_publish_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    edit_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    edit_cycle: Mapped[int | None] = mapped_column(Integer, nullable=True)

    references: Mapped[list["WordReference"]] = relationship(back_populates="document")
    sections: Mapped[list["WordSection"]] = relationship(back_populates="document")

    __table_args__ = (
        Index("ux_word_documents_edit_run_cycle", "edit_run_id", "edit_cycle", unique=True),
    )


class WordTemplate(Base, TimestampMixin):
    __tablename__ = "word_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    template_year: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    template_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    parse_status: Mapped[str] = mapped_column(String(32), default="parsed", nullable=False)
    heading_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class WordTemplateHeading(Base, TimestampMixin):
    __tablename__ = "word_template_headings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("word_templates.id"), nullable=True)
    heading_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paragraph_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    heading_no: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    full_title: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (
        Index("ix_word_template_headings_template_index", "template_id", "heading_index"),
    )


class WordTemplateKeySection(Base, TimestampMixin):
    __tablename__ = "word_template_key_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("word_templates.id", ondelete="CASCADE"), nullable=False
    )
    section_key: Mapped[str] = mapped_column(String(64), nullable=False)
    section_title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    paragraph_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    blocks: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    __table_args__ = (
        Index(
            "ux_word_template_key_sections_template_key",
            "template_id",
            "section_key",
            unique=True,
        ),
    )


class WordReference(Base, TimestampMixin):
    __tablename__ = "word_references"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("word_documents.id"), nullable=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    file_name: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    section_title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    paragraph_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    standard_no: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    standard_name: Mapped[str] = mapped_column(Text, default="", nullable=False)
    clause_no: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    quoted_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    context: Mapped[str] = mapped_column(Text, default="", nullable=False)
    locator: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    document: Mapped[WordDocument | None] = relationship(back_populates="references")

    __table_args__ = (
        Index("ix_word_references_standard_clause", "standard_no", "clause_no"),
        Index("ix_word_references_file_paragraph", "file_name", "paragraph_index"),
    )


class WordSection(Base, TimestampMixin):
    __tablename__ = "word_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("word_documents.id"), nullable=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    file_name: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    section_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paragraph_start: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paragraph_end: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    heading_no: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    full_title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    section_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body_length: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    document: Mapped[WordDocument | None] = relationship(back_populates="sections")

    __table_args__ = (
        Index("ix_word_sections_document_index", "document_id", "section_index"),
    )


class CheckIssue(Base, TimestampMixin):
    __tablename__ = "check_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("word_documents.id"), nullable=True)
    word_reference_id: Mapped[int | None] = mapped_column(ForeignKey("word_references.id"), nullable=True)
    matched_clause_id: Mapped[int | None] = mapped_column(ForeignKey("mandatory_clauses.id"), nullable=True)
    matched_standard_record_id: Mapped[int | None] = mapped_column(ForeignKey("standard_validity_records.id"), nullable=True)
    section_title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    paragraph_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    standard_no: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    standard_name: Mapped[str] = mapped_column(Text, default="", nullable=False)
    clause_no: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    check_scope: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    original_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    suggestion: Mapped[str] = mapped_column(Text, default="", nullable=False)
    fix_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_check_issues_type_severity", "issue_type", "severity"),
        Index("ix_check_issues_document_paragraph", "document_id", "paragraph_index"),
        Index("ix_check_issues_document_scope", "document_id", "check_scope"),
    )


class CheckRun(Base, TimestampMixin):
    __tablename__ = "check_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("word_documents.id"), nullable=True)
    user_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tool_plan: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    tool_results: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    issue_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        Index("ix_check_runs_document_status", "document_id", "status"),
    )


class WordEditRun(Base, TimestampMixin):
    __tablename__ = "word_edit_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("agent_sessions.id", ondelete="SET NULL"), nullable=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("word_documents.id"), nullable=False)
    source_check_run_id: Mapped[int | None] = mapped_column(ForeignKey("check_runs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="planning", nullable=False)
    changes: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    decision_trace: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    output_document_id: Mapped[int | None] = mapped_column(ForeignKey("word_documents.id"), nullable=True)
    verification_run_id: Mapped[int | None] = mapped_column(ForeignKey("check_runs.id", ondelete="SET NULL"), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (
        Index("ix_word_edit_runs_owner_status", "owner_user_id", "status"),
        Index("ix_word_edit_runs_session_created", "session_id", "created_at"),
    )


class AgentSession(Base, TimestampMixin):
    __tablename__ = "agent_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(256), default="新对话", nullable=False)
    messages: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    active_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("word_documents.id", ondelete="SET NULL"), nullable=True
    )
    last_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("check_runs.id", ondelete="SET NULL"), nullable=True
    )
    last_check_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("check_runs.id", ondelete="SET NULL"), nullable=True
    )
    active_edit_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_clause_extraction_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    summarized_message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        Index("ix_agent_sessions_owner_updated", "owner_user_id", "updated_at"),
    )


class ClauseExtractionRun(Base, TimestampMixin):
    __tablename__ = "clause_extraction_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="SET NULL"), nullable=True
    )
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parsed_pages_path: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="planning", nullable=False)
    mandatory_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    detection_methods: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clause_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    decision_trace: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), default="1", nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), default="1", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (
        Index("ix_clause_extraction_runs_owner_status", "owner_user_id", "status"),
        Index(
            "ix_clause_extraction_runs_owner_hash_version",
            "owner_user_id",
            "file_hash",
            "parser_version",
            "prompt_version",
        ),
        Index("ix_clause_extraction_runs_session_created", "session_id", "created_at"),
    )
