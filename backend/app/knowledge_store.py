from pathlib import Path

from app.config import get_settings, resolve_backend_path
from pymilvus import AnnSearchRequest, DataType, MilvusClient, WeightedRanker

from app.schemas import TextChunk


KEYWORD_WEIGHT = 0.6
DENSE_WEIGHT = 0.4


class KnowledgeMilvusStore:
    def __init__(self) -> None:
        settings = get_settings()
        uri = resolve_backend_path(settings.milvus_uri)
        Path(uri).parent.mkdir(parents=True, exist_ok=True)
        self.client = MilvusClient(uri=uri)
        self.collection_name = settings.knowledge_milvus_collection

    def ensure_collection(self, dim: int) -> None:
        if self.client.has_collection(self.collection_name):
            return

        schema = MilvusClient.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field("document_id", DataType.INT64)
        schema.add_field("chunk_index", DataType.INT64)
        schema.add_field("page_no", DataType.INT64)
        schema.add_field("source_file", DataType.VARCHAR, max_length=512)
        schema.add_field("text", DataType.VARCHAR, max_length=65535)
        schema.add_field("keywords", DataType.VARCHAR, max_length=8192)
        schema.add_field("sparse_vector", DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field("dense_vector", DataType.FLOAT_VECTOR, dim=dim)

        indexes = MilvusClient.prepare_index_params()
        indexes.add_index(
            field_name="sparse_vector",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="IP",
        )
        indexes.add_index(
            field_name="dense_vector",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )
        self.client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=indexes,
        )

    def insert_chunks(
        self,
        document_id: int,
        chunks: list[TextChunk],
        dense_vectors: list[list[float]],
        sparse_vectors: list[dict[int, float]],
        keywords: list[str],
    ) -> None:
        rows = []
        for chunk, dense, sparse, keyword_value in zip(
            chunks, dense_vectors, sparse_vectors, keywords
        ):
            rows.append(
                {
                    "document_id": document_id,
                    "chunk_index": chunk.chunk_index,
                    "page_no": int(chunk.metadata.get("page_no") or 0),
                    "source_file": chunk.source_file,
                    "text": chunk.text,
                    "keywords": keyword_value,
                    "sparse_vector": sparse,
                    "dense_vector": dense,
                }
            )
        self.client.insert(collection_name=self.collection_name, data=rows)

    def hybrid_search(
        self,
        dense_vector: list[float],
        sparse_query: dict[int, float],
        *,
        limit: int = 5,
    ) -> list[dict[str, object]]:
        if not self.client.has_collection(self.collection_name):
            return []

        self.client.load_collection(collection_name=self.collection_name)
        candidate_limit = max(limit * 3, limit)
        sparse_request = AnnSearchRequest(
            data=[sparse_query],
            anns_field="sparse_vector",
            param={"metric_type": "IP", "params": {}},
            limit=candidate_limit,
        )
        dense_request = AnnSearchRequest(
            data=[dense_vector],
            anns_field="dense_vector",
            param={"metric_type": "COSINE", "params": {}},
            limit=candidate_limit,
        )
        results = self.client.hybrid_search(
            collection_name=self.collection_name,
            reqs=[sparse_request, dense_request],
            ranker=WeightedRanker(KEYWORD_WEIGHT, DENSE_WEIGHT),
            limit=limit,
            output_fields=[
                "document_id",
                "chunk_index",
                "page_no",
                "source_file",
                "text",
                "keywords",
            ],
        )
        return list(results[0]) if results else []

    def delete_document(self, document_id: int) -> None:
        if self.client.has_collection(self.collection_name):
            self.client.load_collection(collection_name=self.collection_name)
            self.client.delete(
                collection_name=self.collection_name,
                filter=f"document_id == {document_id}",
            )
