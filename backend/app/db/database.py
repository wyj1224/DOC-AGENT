from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings


def get_engine():
    return create_engine(get_settings().database_url, pool_pre_ping=True)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def init_db() -> None:
    from app.db.models import Base

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT NOT NULL DEFAULT ''"))
        connection.execute(text("ALTER TABLE word_documents ADD COLUMN IF NOT EXISTS file_path VARCHAR(1024) NOT NULL DEFAULT ''"))
        connection.execute(text("ALTER TABLE word_documents ADD COLUMN IF NOT EXISTS edit_run_id INTEGER"))
        connection.execute(text("ALTER TABLE word_documents ADD COLUMN IF NOT EXISTS edit_cycle INTEGER"))
        connection.execute(text("ALTER TABLE word_references ADD COLUMN IF NOT EXISTS locator JSONB NOT NULL DEFAULT '{}'::jsonb"))
        connection.execute(text("ALTER TABLE check_issues ADD COLUMN IF NOT EXISTS section_title TEXT NOT NULL DEFAULT ''"))
        connection.execute(text("ALTER TABLE check_issues ADD COLUMN IF NOT EXISTS paragraph_index INTEGER NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE check_issues ADD COLUMN IF NOT EXISTS standard_no VARCHAR(128) NOT NULL DEFAULT ''"))
        connection.execute(text("ALTER TABLE check_issues ADD COLUMN IF NOT EXISTS standard_name TEXT NOT NULL DEFAULT ''"))
        connection.execute(text("ALTER TABLE check_issues ADD COLUMN IF NOT EXISTS clause_no VARCHAR(64) NOT NULL DEFAULT ''"))
        connection.execute(text("ALTER TABLE check_issues ADD COLUMN IF NOT EXISTS check_scope VARCHAR(32) NOT NULL DEFAULT ''"))
        connection.execute(text("ALTER TABLE check_issues ADD COLUMN IF NOT EXISTS fix_data JSONB NOT NULL DEFAULT '{}'::jsonb"))
        connection.execute(text("ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS active_edit_run_id INTEGER"))
        connection.execute(text("ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS active_clause_extraction_run_id INTEGER"))
        connection.execute(text("ALTER TABLE word_edit_runs ADD COLUMN IF NOT EXISTS decision_trace JSONB NOT NULL DEFAULT '[]'::jsonb"))
        connection.execute(text("ALTER TABLE word_templates ADD COLUMN IF NOT EXISTS template_year INTEGER NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE word_templates ADD COLUMN IF NOT EXISTS template_type VARCHAR(32) NOT NULL DEFAULT ''"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_check_issues_document_paragraph ON check_issues (document_id, paragraph_index)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_check_issues_document_scope ON check_issues (document_id, check_scope)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_check_runs_document_status ON check_runs (document_id, status)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_word_documents_edit_run_cycle ON word_documents (edit_run_id, edit_cycle)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_word_templates_year_type ON word_templates (template_year, template_type)"))
