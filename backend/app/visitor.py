import hashlib
import hmac
import re
import secrets

from fastapi import Request
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db.database import SessionLocal
from app.db.models import User


VISITOR_COOKIE_NAME = "doc_agent_visitor"
VISITOR_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def prepare_visitor(request: Request) -> str:
    """Resolve the anonymous visitor and return the signed cookie value."""
    raw_cookie = request.cookies.get(VISITOR_COOKIE_NAME, "")
    visitor_key = verify_cookie(raw_cookie) or secrets.token_hex(16)
    request.state.visitor_key = visitor_key
    return sign_cookie(visitor_key)


def set_visitor_cookie(response, cookie_value: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=VISITOR_COOKIE_NAME,
        value=cookie_value,
        max_age=settings.visitor_cookie_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.visitor_cookie_secure,
        samesite="lax",
        path="/",
    )


def get_current_visitor(request: Request) -> User:
    visitor_key = getattr(request.state, "visitor_key", None)
    if not visitor_key:
        visitor_key = verify_cookie(request.cookies.get(VISITOR_COOKIE_NAME, ""))
    if not visitor_key:
        raise RuntimeError("匿名访客 Cookie 尚未初始化")

    username = f"visitor_{visitor_key}"
    with SessionLocal() as session:
        visitor = session.query(User).filter(User.username == username).first()
        if not visitor:
            visitor = User(username=username, display_name="访客", password_hash="")
            session.add(visitor)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                visitor = session.query(User).filter(User.username == username).one()
            else:
                session.refresh(visitor)
        session.expunge(visitor)
        return visitor


def sign_cookie(visitor_key: str) -> str:
    signature = hmac.new(
        visitor_secret().encode("utf-8"),
        visitor_key.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{visitor_key}.{signature}"


def verify_cookie(cookie_value: str) -> str | None:
    visitor_key, separator, signature = cookie_value.partition(".")
    if not separator or not VISITOR_KEY_PATTERN.fullmatch(visitor_key):
        return None
    expected = sign_cookie(visitor_key).split(".", 1)[1]
    return visitor_key if hmac.compare_digest(signature, expected) else None


def visitor_secret() -> str:
    secret = get_settings().visitor_cookie_secret
    if not secret:
        raise RuntimeError("VISITOR_COOKIE_SECRET 未配置")
    return secret
