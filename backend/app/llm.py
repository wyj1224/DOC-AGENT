from openai import OpenAI

from app.config import get_settings


USER_REPORT_FORMAT_RULES = """
面向用户的回答必须使用统一、易读的排版：
1. 只使用简短自然段、Markdown 二级/三级标题、项目符号和编号列表。
2. 禁止使用 Markdown 表格，禁止输出以竖线“|”分隔的内容、表格分隔行或代码块。
3. 内容较多时先给简短结论，再分类说明；没有内容的分类不要输出。
4. 同类内容先用粗体汇总“名称（N处/条）”，再列必要明细，避免重复堆砌。
5. 每条只保留名称、位置和必要说明；不要直接复制内部 JSON、英文状态字段或大段原文。
6. 使用中文业务名称。篇幅较短时可以直接回答，不要为了排版制造空标题。
""".strip()


def call_llm(prompt: str, *, temperature: float = 0) -> str:
    settings = get_settings()
    if not settings.llm_api_key:
        raise ValueError("请先在 backend/.env 中配置 DEEPSEEK_API_KEY")
    client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return response.choices[0].message.content.strip()
