import argparse

from app.embedding_qwen import QwenEmbedder
from app.milvus_store import MilvusStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Search Milvus mandatory clause chunks.")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--standard-no", default="")
    args = parser.parse_args()

    filter_expr = ""
    if args.standard_no:
        filter_expr = f'standard_no == "{args.standard_no}"'

    vector = QwenEmbedder().embed_query(args.query)
    hits = MilvusStore().search(vector, limit=args.limit, filter_expr=filter_expr)
    for i, hit in enumerate(hits, start=1):
        entity = hit.get("entity", {})
        print(f"\n## {i}. score={hit.get('distance')}")
        print(f"标准号：{entity.get('standard_no', '')}")
        print(f"条号：{entity.get('clause_no', '')}")
        print(f"来源：{entity.get('source_file', '')} / {entity.get('sheet_name', '')} 第 {entity.get('row_index', '')} 行")
        print(entity.get("text", ""))


if __name__ == "__main__":
    main()

