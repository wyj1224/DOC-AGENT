from dataclasses import dataclass, field
from typing import Any


@dataclass
class TextChunk:
    text: str
    source_type: str
    source_file: str
    chunk_index: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_milvus_row(self, vector: list[float]) -> dict[str, Any]:
        return {
            "text": self.text,
            "source_type": self.source_type,
            "source_file": self.source_file,
            "chunk_index": self.chunk_index,
            "standard_no": self.metadata.get("standard_no", ""),
            "standard_name": self.metadata.get("standard_name", ""),
            "clause_no": self.metadata.get("clause_no", ""),
            "applicable_scope": self.metadata.get("applicable_scope", ""),
            "sheet_name": self.metadata.get("sheet_name", ""),
            "row_index": int(self.metadata.get("row_index") or 0),
            "dense_vector": vector,
        }


@dataclass
class StandardValidityRecord:
    old_standard_text: str
    new_standard_text: str
    new_publish_date: str
    new_effective_date: str
    involved_content: str
    verified_date: str
    note: str
    source_url: str
    source_file: str
    sheet_name: str
    row_index: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "old_standard_text": self.old_standard_text,
            "new_standard_text": self.new_standard_text,
            "new_publish_date": self.new_publish_date,
            "new_effective_date": self.new_effective_date,
            "involved_content": self.involved_content,
            "verified_date": self.verified_date,
            "note": self.note,
            "source_url": self.source_url,
            "source_file": self.source_file,
            "sheet_name": self.sheet_name,
            "row_index": self.row_index,
        }
