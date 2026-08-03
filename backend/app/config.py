from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")
LEGACY_MILVUS_URI = os.environ.pop("MILVUS_URI", "")


@dataclass(frozen=True)
class Settings:
    qwen_api_key: str
    qwen_base_url: str
    qwen_embedding_model: str
    qwen_vision_api_key: str
    qwen_vision_base_url: str
    qwen_vision_model: str
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    milvus_uri: str
    milvus_collection: str
    knowledge_milvus_collection: str
    database_url: str
    llama_cloud_api_key: str
    visitor_cookie_secret: str
    visitor_cookie_days: int
    visitor_cookie_secure: bool


def get_settings() -> Settings:
    return Settings(
        qwen_api_key=os.getenv("QWEN_API_KEY", ""),
        qwen_base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        qwen_embedding_model=os.getenv("QWEN_EMBEDDING_MODEL", "text-embedding-v4"),
        qwen_vision_api_key=os.getenv(
            "DASHSCOPE_API_KEY", os.getenv("QWEN_API_KEY", "")
        ),
        qwen_vision_base_url=os.getenv(
            "QWEN_VISION_BASE_URL",
            os.getenv(
                "QWEN_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        ),
        qwen_vision_model=os.getenv("QWEN_VISION_MODEL", "qwen3.7-plus"),
        llm_api_key=os.getenv("DEEPSEEK_API_KEY", os.getenv("LLM_API_KEY", "")),
        llm_base_url=os.getenv("DEEPSEEK_BASE_URL", os.getenv("LLM_BASE_URL", "https://api.deepseek.com")),
        llm_model=os.getenv("DEEPSEEK_MODEL", os.getenv("LLM_MODEL", "deepseek-chat")),
        milvus_uri=os.getenv("APP_MILVUS_URI", LEGACY_MILVUS_URI or "./data/milvus.db"),
        milvus_collection=os.getenv("MILVUS_COLLECTION", "mandatory_clause_chunks"),
        knowledge_milvus_collection=os.getenv("KNOWLEDGE_MILVUS_COLLECTION", "knowledge_chunks"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://clause_agent:clause_agent@localhost:5432/clause_agent",
        ),
        llama_cloud_api_key=os.getenv("LLAMA_CLOUD_API_KEY", ""),
        visitor_cookie_secret=os.getenv("VISITOR_COOKIE_SECRET", "change-me-before-running"),
        visitor_cookie_days=int(os.getenv("VISITOR_COOKIE_DAYS", "90")),
        visitor_cookie_secure=os.getenv("VISITOR_COOKIE_SECURE", "false").lower()
        in {"1", "true", "yes"},
    )


def resolve_backend_path(path_text: str) -> str:
    path = Path(path_text)
    if path.is_absolute():
        return str(path)
    return str((BACKEND_ROOT / path).resolve())
