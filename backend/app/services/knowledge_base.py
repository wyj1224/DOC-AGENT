from pathlib import Path

from llama_cloud_services import LlamaParse

from app.chunking import chunk_markdown
from app.config import get_settings
from app.db.database import SessionLocal
from app.db.models import KnowledgeDocument
from app.embedding_qwen import QwenEmbedder
from app.keyword_embedding import keyword_text, sparse_vector
from app.knowledge_store import DENSE_WEIGHT, KEYWORD_WEIGHT, KnowledgeMilvusStore
from app.llm import USER_REPORT_FORMAT_RULES, call_llm
from app.schemas import TextChunk


def ingest_knowledge_document(file_path: str, original_name: str) -> dict[str, object]:
    path = Path(file_path)
    with SessionLocal() as session:
        document = KnowledgeDocument(
            file_name=original_name,
            file_path=str(path),
            file_type=path.suffix.lower(),
            parse_status="parsing",
        )
        session.add(document)
        session.commit()
        session.refresh(document)
        document_id = document.id

    try:
        pages = parse_document(path)
        chunks = build_chunks(pages, original_name)
        if not chunks:
            raise ValueError("LlamaParse 未解析出可入库正文")

        dense_vectors = QwenEmbedder().embed_texts([chunk.text for chunk in chunks])
        sparse_vectors = [sparse_vector(chunk.text) for chunk in chunks]
        keywords = [keyword_text(chunk.text) for chunk in chunks]

        store = KnowledgeMilvusStore()
        store.ensure_collection(len(dense_vectors[0]))
        store.insert_chunks(document_id, chunks, dense_vectors, sparse_vectors, keywords)

        with SessionLocal() as session:
            document = session.get(KnowledgeDocument, document_id)
            document.parse_status = "parsed"
            document.page_count = len(pages)
            document.chunk_count = len(chunks)
            session.commit()
            session.refresh(document)
            return knowledge_document_item(document)
    except Exception as exc:
        with SessionLocal() as session:
            document = session.get(KnowledgeDocument, document_id)
            document.parse_status = "failed"
            document.error_message = str(exc)
            session.commit()
        raise


def parse_document(
    path: Path,
    *,
    target_page_indexes: list[int] | None = None,
    high_accuracy: bool = False,
    user_prompt: str = "",
    preserve_empty_pages: bool = False,
) -> list[str]:
    settings = get_settings()
    if not settings.llama_cloud_api_key:
        raise ValueError("请先在 backend/.env 中配置 LLAMA_CLOUD_API_KEY")
    parser_args: dict[str, object] = {
        "api_key": settings.llama_cloud_api_key,
        "result_type": "markdown",
        "language": "ch_sim",
        "num_workers": 1,
        "show_progress": False,
        "verbose": False,
        "split_by_page": True,
    }
    if target_page_indexes:
        parser_args["target_pages"] = ",".join(str(value) for value in target_page_indexes)
    if high_accuracy:
        parser_args.update(
            {
                "premium_mode": True,
                "high_res_ocr": True,
                "user_prompt": user_prompt,
            }
        )
    parser = LlamaParse(
        **parser_args,
    )
    documents = parser.load_data(str(path))
    if preserve_empty_pages:
        return [document.text.strip() for document in documents]
    return [document.text.strip() for document in documents if document.text.strip()]


def build_chunks(pages: list[str], source_file: str) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for page_no, page_text in enumerate(pages, start=1):
        page_chunks = chunk_markdown(page_text, source_file=source_file, max_chars=700)
        for chunk in page_chunks:
            chunk.chunk_index = len(chunks)
            chunk.source_type = "knowledge_document"
            chunk.metadata["page_no"] = page_no
            chunks.append(chunk)
    return chunks


def search_knowledge(question: str, limit: int = 5) -> list[dict[str, object]]:
    dense_query = QwenEmbedder().embed_query(question)
    sparse_query = sparse_vector(question)
    hits = KnowledgeMilvusStore().hybrid_search(dense_query, sparse_query, limit=limit)
    return [knowledge_hit_item(hit, index) for index, hit in enumerate(hits, start=1)]


def answer_knowledge_question(question: str, limit: int = 5) -> dict[str, object]:
    sources = search_knowledge(question, limit=limit)
    if not sources:
        return {
            "question": question,
            "answer": "知识库中没有检索到可用于回答该问题的内容。",
            "sources": [],
            "weights": {"keyword": KEYWORD_WEIGHT, "dense": DENSE_WEIGHT},
        }

    references = "\n\n".join(
        f"[{item['rank']}] 来源：{item['source_file']}，第 {item['page_no']} 页\n{item['text']}"
        for item in sources
    )
    prompt = f"""
你是通信工程知识库问答助手。请只根据参考资料回答用户问题。

要求：
1. 每个关键结论后标注引用编号，例如 [1]。
2. 资料不足时明确说明，不要补充资料之外的事实。
3. 使用简洁、准确的中文。

{USER_REPORT_FORMAT_RULES}

参考资料：
{references}

用户问题：{question}
"""
    return {
        "question": question,
        "answer": call_llm(prompt),
        "sources": sources,
        "weights": {"keyword": KEYWORD_WEIGHT, "dense": DENSE_WEIGHT},
    }


def knowledge_hit_item(hit: dict, rank: int) -> dict[str, object]:
    entity = hit.get("entity", hit)
    return {
        "rank": rank,
        "score": float(hit.get("distance", 0.0)),
        "document_id": int(entity.get("document_id") or 0),
        "source_file": str(entity.get("source_file") or ""),
        "page_no": int(entity.get("page_no") or 0),
        "chunk_index": int(entity.get("chunk_index") or 0),
        "text": str(entity.get("text") or ""),
    }


def knowledge_document_item(document: KnowledgeDocument) -> dict[str, object]:
    return {
        "document_id": document.id,
        "file_name": document.file_name,
        "file_type": document.file_type,
        "parse_status": document.parse_status,
        "page_count": document.page_count,
        "chunk_count": document.chunk_count,
        "error_message": document.error_message,
        "created_at": document.created_at,
    }
