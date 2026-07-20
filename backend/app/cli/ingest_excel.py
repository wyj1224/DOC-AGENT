import argparse
import json
from pathlib import Path


def print_chunk_preview(chunks, limit: int) -> None:
    print(f"\n=== Chunk preview: first {min(limit, len(chunks))} / {len(chunks)} ===")
    for i, chunk in enumerate(chunks[:limit], start=1):
        print(f"\n--- chunk {i} ---")
        print("standard_no:", chunk.metadata.get("standard_no", ""))
        print("clause_no:", chunk.metadata.get("clause_no", ""))
        print("source:", chunk.source_file, chunk.metadata.get("sheet_name", ""), chunk.metadata.get("row_index", ""))
        print(chunk.text[:1000])


def export_chunks_jsonl(chunks, output_path: str) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            record = {
                "text": chunk.text,
                "source_type": chunk.source_type,
                "source_file": chunk.source_file,
                "chunk_index": chunk.chunk_index,
                "metadata": chunk.metadata,
            }
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def print_standard_preview(records, limit: int) -> None:
    print(f"\n=== Standard validity preview: first {min(limit, len(records))} / {len(records)} ===")
    for i, record in enumerate(records[:limit], start=1):
        data = record.as_dict()
        print(f"\n--- standard record {i} ---")
        print("old:", data["old_standard_text"])
        print("new:", data["new_standard_text"])
        print("publish:", data["new_publish_date"], "effective:", data["new_effective_date"])
        print("content:", data["involved_content"])
        print("note:", data["note"])


def export_records_jsonl(records, output_path: str) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record.as_dict(), ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Excel mandatory clauses into Milvus.")
    parser.add_argument("xlsx_path")
    parser.add_argument("--sheet", default="强条")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--preview-only", action="store_true", help="Only parse and preview chunks; do not embed or write Milvus.")
    parser.add_argument("--preview-limit", type=int, default=10)
    parser.add_argument("--export-chunks", default="", help="Optional JSONL path for chunks before embedding.")
    parser.add_argument("--export-standards", default="", help="Optional JSONL path for records from the 清单 sheet.")
    args = parser.parse_args()

    from app.excel_loader import load_clause_chunks, load_standard_validity_records

    chunks = load_clause_chunks(args.xlsx_path, sheet_name=args.sheet)
    if not chunks:
        raise RuntimeError("没有从 Excel 中解析到强条 chunk")

    print(f"[OK] parsed {len(chunks)} chunks from Excel")
    print_chunk_preview(chunks, limit=args.preview_limit)

    if not args.xlsx_path.lower().endswith(".csv"):
        standard_records = load_standard_validity_records(args.xlsx_path)
        print(f"\n[OK] parsed {len(standard_records)} standard validity records from 清单")
        print_standard_preview(standard_records, limit=args.preview_limit)
        if args.export_standards:
            export_records_jsonl(standard_records, args.export_standards)
            print(f"[OK] exported standard records to {args.export_standards}")

    if args.export_chunks:
        export_chunks_jsonl(chunks, args.export_chunks)
        print(f"[OK] exported chunks to {args.export_chunks}")

    if args.preview_only:
        print("[OK] preview only, skipped embedding and Milvus insert")
        return

    from app.embedding_qwen import QwenEmbedder
    from app.milvus_store import MilvusStore

    embedder = QwenEmbedder()
    vectors = embedder.embed_texts([chunk.text for chunk in chunks], batch_size=args.batch_size)
    print(f"[OK] generated {len(vectors)} embeddings")

    store = MilvusStore()
    store.recreate_collection(dim=len(vectors[0]))
    store.insert_chunks(chunks, vectors)
    print("[OK] inserted chunks into Milvus")


if __name__ == "__main__":
    main()
