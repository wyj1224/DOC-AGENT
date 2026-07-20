import argparse
import json
from pathlib import Path

from app.services.knowledge_base import search_knowledge


def main() -> None:
    parser = argparse.ArgumentParser(description="评测知识库混合检索命中率")
    parser.add_argument("dataset", help="JSONL 测试集路径")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    cases = load_cases(Path(args.dataset))
    passed = 0
    for index, case in enumerate(cases, start=1):
        sources = search_knowledge(case["question"], limit=args.top_k)
        source_hit = any(
            case["expected_source"] in item["source_file"] for item in sources
        )
        retrieved_text = "\n".join(str(item["text"]) for item in sources)
        keyword_hit = all(
            keyword in retrieved_text for keyword in case["expected_keywords"]
        )
        case_passed = source_hit and keyword_hit
        passed += int(case_passed)
        print(
            f"[{index}] {'通过' if case_passed else '失败'} "
            f"来源命中={source_hit} 关键词命中={keyword_hit} {case['question']}"
        )

    rate = passed / len(cases) if cases else 0
    print(f"\n检索通过率：{passed}/{len(cases)} = {rate:.1%}")


def load_cases(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


if __name__ == "__main__":
    main()
