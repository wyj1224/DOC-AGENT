from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings


def get_engine():
    return create_engine(get_settings().database_url, pool_pre_ping=True)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def init_db() -> None:
    from app.db.models import Base

    engine = get_engine()
    with engine.begin() as connection:
        # Several API processes start at once; let one run the schema DDL at a time.
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtext('init_db'))"))
        Base.metadata.create_all(bind=connection)
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
        connection.execute(text("ALTER TABLE check_runs ADD COLUMN IF NOT EXISTS session_id INTEGER REFERENCES agent_sessions(id) ON DELETE SET NULL"))
        connection.execute(text("ALTER TABLE check_runs ADD COLUMN IF NOT EXISTS task_id INTEGER REFERENCES agent_tasks(id) ON DELETE SET NULL"))
        connection.execute(text("ALTER TABLE check_runs ADD COLUMN IF NOT EXISTS episode_id INTEGER REFERENCES agent_episodes(id) ON DELETE SET NULL"))
        connection.execute(text("ALTER TABLE check_runs ADD COLUMN IF NOT EXISTS run_type VARCHAR(32) NOT NULL DEFAULT 'unknown'"))
        connection.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'agent_sessions' AND column_name = 'last_check_run_id'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'agent_sessions' AND column_name = 'last_word_check_run_id'
                ) THEN
                    ALTER TABLE agent_sessions RENAME COLUMN last_check_run_id TO last_word_check_run_id;
                END IF;
            END $$;
        """))
        connection.execute(text("""
            UPDATE check_runs
            SET run_type = CASE
                WHEN tool_plan ->> 'mode' = 'word_edit' OR tool_results::text LIKE '%word_edit_result%' THEN 'word_edit'
                WHEN tool_results::text LIKE '%word_check_tool%'
                  OR tool_results::text LIKE '%completeness_check_tool%'
                  OR tool_results::text LIKE '%get_issues_tool%' THEN 'word_check'
                ELSE 'general'
            END
            WHERE run_type = 'unknown';
        """))
        connection.execute(text("""
            UPDATE check_runs AS run
            SET session_id = agent_session.id
            FROM agent_sessions AS agent_session
            WHERE run.session_id IS NULL
              AND EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(agent_session.messages) AS message
                  WHERE message ->> 'run_id' ~ '^[0-9]+$'
                    AND (message ->> 'run_id')::integer = run.id
              );
        """))
        connection.execute(text("""
            UPDATE agent_sessions AS agent_session
            SET last_word_check_run_id = (
                SELECT run.id
                FROM check_runs AS run
                WHERE run.session_id = agent_session.id
                  AND run.run_type = 'word_check'
                ORDER BY run.id DESC
                LIMIT 1
            );
        """))
        connection.execute(text("ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS active_edit_run_id INTEGER"))
        connection.execute(text("ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS last_task_id INTEGER"))
        connection.execute(text("ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS last_episode_id INTEGER"))
        connection.execute(text("ALTER TABLE word_edit_runs ADD COLUMN IF NOT EXISTS task_id INTEGER REFERENCES agent_tasks(id) ON DELETE SET NULL"))
        connection.execute(text("ALTER TABLE word_edit_runs ADD COLUMN IF NOT EXISTS episode_id INTEGER REFERENCES agent_episodes(id) ON DELETE SET NULL"))
        connection.execute(text("ALTER TABLE word_edit_runs DROP COLUMN IF EXISTS decision_trace"))
        connection.execute(text("ALTER TABLE agent_experiences ADD COLUMN IF NOT EXISTS success_summary TEXT NOT NULL DEFAULT ''"))
        connection.execute(text("ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS worker_id VARCHAR(128) NOT NULL DEFAULT ''"))
        connection.execute(text("ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ"))
        connection.execute(text("ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ"))
        connection.execute(text("ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS response_payload JSONB NOT NULL DEFAULT '{}'::jsonb"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_tasks_status_id ON agent_tasks (status, id)"))
        connection.execute(text("ALTER TABLE word_templates ADD COLUMN IF NOT EXISTS template_year INTEGER NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE word_templates ADD COLUMN IF NOT EXISTS template_type VARCHAR(32) NOT NULL DEFAULT ''"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_check_issues_document_paragraph ON check_issues (document_id, paragraph_index)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_check_issues_document_scope ON check_issues (document_id, check_scope)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_check_runs_document_status ON check_runs (document_id, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_check_runs_session_type ON check_runs (session_id, run_type)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_word_documents_edit_run_cycle ON word_documents (edit_run_id, edit_cycle)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_word_templates_year_type ON word_templates (template_year, template_type)"))
        connection.execute(text("ALTER TABLE agent_sessions DROP COLUMN IF EXISTS active_clause_extraction_run_id"))
        connection.execute(text("DROP TABLE IF EXISTS clause_extraction_runs"))
        connection.execute(text("DROP TABLE IF EXISTS knowledge_documents"))
