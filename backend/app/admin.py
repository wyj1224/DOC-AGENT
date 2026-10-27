import hmac

from fastapi import Header, HTTPException

from app.config import get_settings


ADMIN_TOKEN_HEADER = "X-Admin-Token"


def require_admin(x_admin_token: str = Header("", alias=ADMIN_TOKEN_HEADER)) -> None:
    """Guard endpoints that change shared data (standards library, templates).

    Without ADMIN_TOKEN configured the guard is open, which keeps local
    development unchanged; any public deployment must set it.
    """
    expected = get_settings().admin_token
    if not expected:
        return
    if not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="管理员口令错误")
