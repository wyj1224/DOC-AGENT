from dataclasses import dataclass
from datetime import datetime, timezone

from app.db.database import SessionLocal
from app.db.models import AgentSession, WordDocument
from app.llm import call_llm


SUMMARY_TRIGGER = 12
RECENT_MESSAGE_COUNT = 6


@dataclass(frozen=True)
class SessionContext:
    session_id: int
    document_id: int | None
    conversation: str


def prepare_session(
    owner_user_id: int,
    session_id: int | None,
    message: str,
    document_id: int | None,
) -> SessionContext:
    with SessionLocal() as database:
        if session_id:
            agent_session = (
                database.query(AgentSession)
                .filter(
                    AgentSession.id == session_id,
                    AgentSession.owner_user_id == owner_user_id,
                )
                .first()
            )
            if not agent_session:
                raise ValueError("会话不存在")
        else:
            agent_session = AgentSession(
                owner_user_id=owner_user_id,
                title=session_title(database, message, document_id),
                active_document_id=document_id,
            )
            database.add(agent_session)

        if document_id:
            agent_session.active_document_id = document_id
        database.commit()
        database.refresh(agent_session)
        return SessionContext(
            session_id=agent_session.id,
            document_id=document_id or agent_session.active_document_id,
            conversation=conversation_text(agent_session),
        )


def load_session_context(owner_user_id: int, session_id: int) -> SessionContext:
    """Read the conversation as it is when a queued task actually starts."""
    with SessionLocal() as database:
        agent_session = (
            database.query(AgentSession)
            .filter(
                AgentSession.id == session_id,
                AgentSession.owner_user_id == owner_user_id,
            )
            .first()
        )
        if not agent_session:
            raise ValueError("会话不存在")
        return SessionContext(
            session_id=agent_session.id,
            document_id=agent_session.active_document_id,
            conversation=conversation_text(agent_session),
        )


def append_turn(
    owner_user_id: int,
    session_id: int,
    user_message: str,
    assistant_message: str,
    run_id: int | None,
    run_type: str,
    document_id: int | None,
    task_id: int | None = None,
    episode_id: int | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as database:
        agent_session = (
            database.query(AgentSession)
            .filter(
                AgentSession.id == session_id,
                AgentSession.owner_user_id == owner_user_id,
            )
            .first()
        )
        messages = list(agent_session.messages or [])
        messages.extend(
            [
                {"role": "user", "content": user_message, "created_at": now},
                {
                    "role": "assistant",
                    "content": assistant_message,
                    "created_at": now,
                    **({"run_id": run_id} if run_id else {}),
                    **({"task_id": task_id} if task_id else {}),
                    **({"episode_id": episode_id} if episode_id else {}),
                },
            ]
        )
        agent_session.messages = messages
        agent_session.active_document_id = document_id or agent_session.active_document_id
        if run_id:
            agent_session.last_run_id = run_id
        if run_type == "word_check" and run_id:
            agent_session.last_word_check_run_id = run_id
        if task_id:
            agent_session.last_task_id = task_id
        if episode_id:
            agent_session.last_episode_id = episode_id
        database.commit()

    summarize_if_needed(owner_user_id, session_id)


def conversation_text(agent_session: AgentSession) -> str:
    messages = list(agent_session.messages or [])
    start = min(agent_session.summarized_message_count, len(messages))
    recent = messages[start:][-SUMMARY_TRIGGER:]
    parts = []
    if agent_session.summary.strip():
        parts.append(f"较早会话摘要：\n{agent_session.summary.strip()}")
    if recent:
        lines = [
            f"{'用户' if item.get('role') == 'user' else '助手'}：{item.get('content', '')}"
            for item in recent
        ]
        parts.append("最近会话：\n" + "\n".join(lines))
    return "\n\n".join(parts) or "无"


def summarize_if_needed(owner_user_id: int, session_id: int) -> None:
    with SessionLocal() as database:
        agent_session = (
            database.query(AgentSession)
            .filter(
                AgentSession.id == session_id,
                AgentSession.owner_user_id == owner_user_id,
            )
            .first()
        )
        messages = list(agent_session.messages or [])
        summarized_count = agent_session.summarized_message_count
        if len(messages) - summarized_count < SUMMARY_TRIGGER:
            return
        target_count = len(messages) - RECENT_MESSAGE_COUNT
        pending = messages[summarized_count:target_count]
        old_summary = agent_session.summary

    pending_text = "\n".join(
        f"{'用户' if item.get('role') == 'user' else '助手'}：{item.get('content', '')}"
        for item in pending
    )
    prompt = f"""
请把以下文档智能体会话压缩为简洁中文摘要，保留：用户目标、当前 Word/PDF、已完成操作、关键结论和待办事项。
不要加入原对话没有的信息。

已有摘要：
{old_summary or '无'}

新增对话：
{pending_text}
"""
    try:
        new_summary = call_llm(prompt)
    except Exception:
        return

    with SessionLocal() as database:
        agent_session = (
            database.query(AgentSession)
            .filter(
                AgentSession.id == session_id,
                AgentSession.owner_user_id == owner_user_id,
            )
            .first()
        )
        agent_session.summary = new_summary
        agent_session.summarized_message_count = target_count
        database.commit()


def session_title(database, message: str, document_id: int | None) -> str:
    if document_id:
        document = database.get(WordDocument, document_id)
        if document:
            return shorten(document.file_name.removesuffix(".docx"))
    return shorten(message)


def shorten(value: str) -> str:
    clean = " ".join(value.split()).strip() or "新对话"
    return clean if len(clean) <= 30 else f"{clean[:30]}…"
