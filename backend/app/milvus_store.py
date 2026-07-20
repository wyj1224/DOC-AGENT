from pathlib import Path

from .config import get_settings, resolve_backend_path
from pymilvus import DataType, MilvusClient

from .schemas import TextChunk


class MilvusStore:
    def __init__(self) -> None:
        settings = get_settings()
        uri = resolve_backend_path(settings.milvus_uri)
        Path(uri).parent.mkdir(parents=True, exist_ok=True)
        self.client = MilvusClient(uri=uri)
        self.collection_name = settings.milvus_collection

    def recreate_collection(self, dim: int) -> None:
        if self.client.has_collection(self.collection_name):
            self.client.drop_collection(self.collection_name)

        schema = MilvusClient.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field("dense_vector", DataType.FLOAT_VECTOR, dim=dim)
        schema.add_field("text", DataType.VARCHAR, max_length=8192)
        schema.add_field("source_type", DataType.VARCHAR, max_length=64)
        schema.add_field("source_file", DataType.VARCHAR, max_length=512)
        schema.add_field("chunk_index", DataType.INT64)
        schema.add_field("standard_no", DataType.VARCHAR, max_length=128)
        schema.add_field("standard_name", DataType.VARCHAR, max_length=512)
        schema.add_field("clause_no", DataType.VARCHAR, max_length=64)
        schema.add_field("applicable_scope", DataType.VARCHAR, max_length=512)
        schema.add_field("sheet_name", DataType.VARCHAR, max_length=128)
        schema.add_field("row_index", DataType.INT64)

        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            field_name="dense_vector",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )
        self.client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
        )

    def insert_chunks(self, chunks: list[TextChunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks 和 vectors 数量不一致")
        rows = [chunk.as_milvus_row(vector) for chunk, vector in zip(chunks, vectors)]
        self.client.insert(collection_name=self.collection_name, data=rows)

    def search(self, query_vector: list[float], *, limit: int = 5, filter_expr: str = "") -> list[dict]:
        results = self.client.search(
            collection_name=self.collection_name,
            data=[query_vector],
            anns_field="dense_vector",
            limit=limit,
            filter=filter_expr or "",
            output_fields=[
                "text",
                "source_file",
                "chunk_index",
                "standard_no",
                "standard_name",
                "clause_no",
                "applicable_scope",
                "sheet_name",
                "row_index",
            ],
        )
        return list(results[0]) if results else []
