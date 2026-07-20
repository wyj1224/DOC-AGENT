import math
import re
import zlib
from collections import Counter

import jieba


STANDARD_NO_RE = re.compile(
    r"(?i)(?:[A-Z]{1,8}(?:/[A-Z]{1,8})?)\s*\d+(?:\.\d+)*(?:\s*[-—–－]\s*\d{2,4})?"
)


def keyword_terms(text: str) -> list[str]:
    normalized = text.lower().replace("－", "-").replace("—", "-").replace("–", "-")
    terms = [normalize_term(item) for item in jieba.lcut_for_search(normalized)]
    terms.extend(normalize_term(item) for item in STANDARD_NO_RE.findall(normalized))
    return [term for term in terms if keep_term(term)]


def keyword_text(text: str) -> str:
    return " ".join(dict.fromkeys(keyword_terms(text)))


def sparse_vector(text: str) -> dict[int, float]:
    counts = Counter(keyword_terms(text))
    weighted: dict[int, float] = {}
    for term, count in counts.items():
        index = (zlib.crc32(term.encode("utf-8")) & 0x7FFFFFFF) + 1
        weighted[index] = weighted.get(index, 0.0) + 1.0 + math.log(count)

    norm = math.sqrt(sum(value * value for value in weighted.values())) or 1.0
    return {index: value / norm for index, value in weighted.items()}


def normalize_term(term: str) -> str:
    return re.sub(r"\s+", "", term.strip().lower())


def keep_term(term: str) -> bool:
    if not term or re.fullmatch(r"[\W_]+", term):
        return False
    return len(term) > 1 or bool(re.search(r"[a-z0-9]", term))
