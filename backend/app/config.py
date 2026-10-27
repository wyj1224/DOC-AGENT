from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    database_url: str
    visitor_cookie_secret: str
    visitor_cookie_days: int
    visitor_cookie_secure: bool
    admin_token: str


def get_settings() -> Settings:
    return Settings(
        llm_api_key=os.getenv("DEEPSEEK_API_KEY", os.getenv("LLM_API_KEY", "")),
        llm_base_url=os.getenv("DEEPSEEK_BASE_URL", os.getenv("LLM_BASE_URL", "https://api.deepseek.com")),
        llm_model=os.getenv("DEEPSEEK_MODEL", os.getenv("LLM_MODEL", "deepseek-chat")),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://clause_agent:clause_agent@localhost:5432/clause_agent",
        ),
        visitor_cookie_secret=os.getenv("VISITOR_COOKIE_SECRET", "change-me-before-running"),
        visitor_cookie_days=int(os.getenv("VISITOR_COOKIE_DAYS", "90")),
        visitor_cookie_secure=os.getenv("VISITOR_COOKIE_SECURE", "false").lower()
        in {"1", "true", "yes"},
        admin_token=os.getenv("ADMIN_TOKEN", ""),
    )
