from openai import OpenAI

from .config import get_settings

MAX_EMBEDDING_BATCH_SIZE = 10


class QwenEmbedder:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.qwen_api_key:
            raise RuntimeError("请先在 backend/.env 中填写 QWEN_API_KEY")
        self.model = settings.qwen_embedding_model
        self.client = OpenAI(api_key=settings.qwen_api_key, base_url=settings.qwen_base_url)

    def embed_texts(self, texts: list[str], batch_size: int = MAX_EMBEDDING_BATCH_SIZE) -> list[list[float]]:
        batch_size = min(batch_size, MAX_EMBEDDING_BATCH_SIZE)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            response = self.client.embeddings.create(model=self.model, input=batch)
            vectors.extend([item.embedding for item in response.data])
        return vectors

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]
