from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import create_access_token, get_current_user, hash_password, verify_password
from app.db.database import SessionLocal
from app.db.models import User


router = APIRouter(prefix="/auth", tags=["认证"])


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/register")
def register(payload: RegisterRequest):
    username = payload.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="用户名至少需要 3 个字符")

    with SessionLocal() as session:
        if session.query(User).filter(User.username == username).first():
            raise HTTPException(status_code=409, detail="用户名已存在")
        user = User(
            username=username,
            display_name=payload.display_name.strip(),
            password_hash=hash_password(payload.password),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return auth_result(user)


@router.post("/login")
def login(payload: LoginRequest):
    with SessionLocal() as session:
        user = session.query(User).filter(User.username == payload.username.strip()).first()
        if not user or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        return auth_result(user)


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_item(user)


def auth_result(user: User) -> dict[str, object]:
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": user_item(user),
    }


def user_item(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
    }
