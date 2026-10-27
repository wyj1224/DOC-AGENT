from functools import lru_cache
import os
import threading

from openai import OpenAI

from app.config import get_settings


LLM_TIMEOUT_SECONDS = 60.0
# Upper bound on in-flight LLM requests per process, shared by every worker slot,
# so a burst of tasks queues here instead of tripping the provider's rate limit.
LLM_MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY", "4"))
# How long a call may wait for a free slot before failing loudly.
LLM_SLOT_TIMEOUT_SECONDS = 120.0
_llm_slots = threading.BoundedSemaphore(LLM_MAX_CONCURRENCY)
LLM_MAX_TOKENS = 4096
LLM_REPORT_MAX_TOKENS = 8192


USER_REPORT_FORMAT_RULES = """
面向用户的回答必须使用统一、易读的排版：
1. 只使用简短自然段、Markdown 二级/三级标题、项目符号和编号列表。
2. 禁止使用 Markdown 表格，禁止输出以竖线“|”分隔的内容、表格分隔行或代码块。
3. 内容较多时先给简短结论，再分类说明；没有内容的分类不要输出。
4. 同类内容先用粗体汇总“名称（N处/条）”，再列必要明细，避免重复堆砌。
5. 每条只保留名称、位置和必要说明；不要直接复制内部 JSON、英文状态字段或大段原文。
6. 使用中文业务名称。篇幅较短时可以直接回答，不要为了排版制造空标题。
""".strip()


def call_llm_messages(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0,
    max_tokens: int = LLM_MAX_TOKENS,
) -> str:
    settings = get_settings()
    if not settings.llm_api_key:
        raise ValueError("请先在 backend/.env 中配置 DEEPSEEK_API_KEY")
    client = llm_client(settings.llm_api_key, settings.llm_base_url)
    if not _llm_slots.acquire(timeout=LLM_SLOT_TIMEOUT_SECONDS):
        raise TimeoutError(
            f"等待 LLM 并发槽位超过 {LLM_SLOT_TIMEOUT_SECONDS:.0f} 秒"
        )
    try:
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    finally:
        _llm_slots.release()
    content = response.choices[0].message.content or ""
    if not content.strip():
        raise ValueError("LLM 未返回可用文本")
    return content.strip()


@lru_cache(maxsize=4)
def llm_client(api_key: str, base_url: str) -> OpenAI:
    """Reuse one client (and its HTTP connection pool) per credential set."""
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=0,
    )


def call_llm(prompt: str, *, temperature: float = 0) -> str:
    """Compatibility wrapper for existing business summarizers."""
    return call_llm_messages(
        [{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=LLM_REPORT_MAX_TOKENS,
    )
