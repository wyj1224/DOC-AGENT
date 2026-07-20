import base64
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz
import numpy as np
from openai import OpenAI
from PIL import Image

from app.config import get_settings


VISION_BATCH_SIZE = 1
VISION_CONCURRENCY = 4
VISION_MAX_IMAGE_EDGE = 2000
PIXEL_RENDER_SCALE = 3.0
CLAUSE_NO_PATTERN = re.compile(r"(?<!\d)(\d{1,2}(?:[.．。]\d{1,2}){1,3})(?!\d)")
VISION_PROMPT = """
你是工程建设规范 PDF 的视觉证据识别器。你会收到若干张按 PDF 物理页码标注的页面图片。

只依据页面中肉眼可见的内容和排版作答，不得依据条文中的“必须、严禁、应、不得”等语义猜测强条。
同一物理页会拆成有重叠的上、中、下三个区域。必须逐行检查三个区域直到页面底部，合并为该物理页的一条结果，不能只检查页面开头。

每页需要识别：
1. announcement_clause_nos：仅提取页面明确声明“第……条为强制性条文”时，该声明列出的完整条号。
2. bold_clause_nos：仅提取条号和整条正文采用黑体/粗体排版的条文。必须同时比较同一区域的相邻普通条文；中文黑体与普通宋体的差异还包括笔画粗细更均匀、字形更方正、衬线和收笔不同，不一定表现为整行灰度大幅变黑。普通条号本身偏粗、章节标题、表名、表头、编号列表和水印都不是强条证据。若只有措辞强烈但字体与相邻正文相同，不得返回。
3. has_bold_rule：页面是否明确写明“黑体字/粗体标注的条文为强制性条文”。
4. has_explicit_no_mandatory：页面是否明确写明本规范无强制性条文或不设强制性条文。仅仅没有看到粗体不能算明确无强条。
5. evidence_text：最多保留两条支持上述判断的短原文，不要抄整页。
6. confidence：0 到 1。

只返回 JSON，不要 Markdown，不要解释。格式必须是：
{
  "pages": [
    {
      "page_no": 1,
      "announcement_clause_nos": [],
      "bold_clause_nos": [],
      "has_bold_rule": false,
      "has_explicit_no_mandatory": false,
      "evidence_text": [],
      "confidence": 0.0
    }
  ]
}
""".strip()

BOLD_LINE_OCR_PROMPT = """
这些图片是从工程规范原页中按实际黑色笔画厚度筛出的“粗体文本行”，每张图都标注了物理页码。

你只负责读取图片：若图片左侧以完整规范条号开头（如 1.0.6、2.0.10、3.3.5），把条号写入该页的 bold_clause_nos；续行、章节标题、表名、表头、页码和看不清的图片都忽略。不得根据文字语义增加图片中不存在的条号。

只返回 JSON，不要 Markdown，不要解释：
{
  "pages": [
    {
      "page_no": 1,
      "announcement_clause_nos": [],
      "bold_clause_nos": [],
      "has_bold_rule": false,
      "has_explicit_no_mandatory": false,
      "evidence_text": ["最多两条实际读到的粗体行短原文"],
      "confidence": 0.0
    }
  ]
}
""".strip()


def pdf_page_count(path: Path) -> int:
    with fitz.open(path) as document:
        return len(document)


def analyze_pdf_visual_evidence(
    path: Path,
    *,
    page_indexes: list[int],
    batch_size: int = VISION_BATCH_SIZE,
    prompt: str = VISION_PROMPT,
) -> dict[str, object]:
    settings = get_settings()
    if not settings.qwen_vision_api_key:
        raise ValueError("请先配置 DASHSCOPE_API_KEY 或 QWEN_API_KEY")
    if not page_indexes:
        return {"model": settings.qwen_vision_model, "pages": []}

    page_count = pdf_page_count(path)
    indexes = sorted(set(page_indexes))
    if indexes[0] < 0 or indexes[-1] >= page_count:
        raise ValueError("视觉识别页码超出 PDF 范围")

    client = OpenAI(
        api_key=settings.qwen_vision_api_key,
        base_url=settings.qwen_vision_base_url,
    )
    results: list[dict[str, object]] = []
    safe_batch_size = max(1, min(int(batch_size), 8))
    if safe_batch_size == 1:
        with ThreadPoolExecutor(max_workers=VISION_CONCURRENCY) as executor:
            for start in range(0, len(indexes), VISION_CONCURRENCY):
                wave = indexes[start : start + VISION_CONCURRENCY]
                rendered = render_pdf_pages(path, wave)
                regions_by_page = {
                    page_index + 1: [
                        page
                        for page in rendered
                        if int(page["page_no"]) == page_index + 1
                    ]
                    for page_index in wave
                }
                futures = [
                    executor.submit(
                        analyze_visual_batch,
                        client,
                        model=settings.qwen_vision_model,
                        rendered_pages=regions_by_page[page_index + 1],
                        prompt=prompt,
                    )
                    for page_index in wave
                ]
                for future in futures:
                    results.extend(future.result())
        return {"model": settings.qwen_vision_model, "pages": results}

    for start in range(0, len(indexes), safe_batch_size):
        batch = indexes[start : start + safe_batch_size]
        rendered = render_pdf_pages(path, batch)
        results.extend(
            analyze_visual_batch(
                client,
                model=settings.qwen_vision_model,
                rendered_pages=rendered,
                prompt=prompt,
            )
        )
    return {"model": settings.qwen_vision_model, "pages": results}


def analyze_pdf_bold_lines(
    path: Path, *, page_indexes: list[int]
) -> dict[str, object]:
    settings = get_settings()
    if not settings.qwen_vision_api_key:
        raise ValueError("请先配置 DASHSCOPE_API_KEY 或 QWEN_API_KEY")
    indexes = sorted(set(page_indexes))
    candidates, metrics = render_bold_line_candidates(path, indexes)
    candidates_by_page = {
        page_index + 1: [
            item for item in candidates if int(item["page_no"]) == page_index + 1
        ]
        for page_index in indexes
    }
    client = OpenAI(
        api_key=settings.qwen_vision_api_key,
        base_url=settings.qwen_vision_base_url,
    )
    detected_by_page: dict[int, dict[str, object]] = {}
    pages_with_candidates = [
        page_no for page_no, items in candidates_by_page.items() if items
    ]
    with ThreadPoolExecutor(max_workers=VISION_CONCURRENCY) as executor:
        futures = {
            page_no: executor.submit(
                analyze_visual_batch,
                client,
                model=settings.qwen_vision_model,
                rendered_pages=candidates_by_page[page_no],
                prompt=BOLD_LINE_OCR_PROMPT,
            )
            for page_no in pages_with_candidates
        }
        for page_no, future in futures.items():
            result_pages = future.result()
            if result_pages:
                detected_by_page[page_no] = result_pages[0]

    pages = [
        detected_by_page.get(page_index + 1, normalize_visual_page({}, page_index + 1))
        for page_index in indexes
    ]
    return {
        "model": settings.qwen_vision_model,
        "pages": pages,
        "candidate_metrics": metrics,
    }


def render_bold_line_candidates(
    path: Path, page_indexes: list[int]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    candidates: list[dict[str, object]] = []
    metrics: list[dict[str, object]] = []
    with fitz.open(path) as document:
        for page_index in page_indexes:
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(PIXEL_RENDER_SCALE, PIXEL_RENDER_SCALE),
                colorspace=fitz.csRGB,
                alpha=False,
            )
            image = Image.frombytes(
                "RGB", (pixmap.width, pixmap.height), pixmap.samples
            )
            page_candidates, page_metrics = detect_bold_line_regions(image)
            for candidate_index, item in enumerate(page_candidates, start=1):
                crop = item.pop("crop")
                candidates.append(
                    {
                        "page_no": page_index + 1,
                        "region": f"像素粗体候选行 {candidate_index}",
                        "image_url": image_data_url(crop, image_format="PNG"),
                    }
                )
            metrics.extend(
                {"page_no": page_index + 1, **item} for item in page_metrics
            )
    return candidates, metrics


def detect_bold_line_regions(
    image: Image.Image,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    gray = np.array(image.convert("L"))
    ink = gray < 90
    runs = horizontal_text_runs(ink)
    line_metrics: list[dict[str, object]] = []
    for y0, y1 in runs:
        band = ink[y0 : y1 + 1]
        ys, xs = np.where(band)
        if len(xs) < 30:
            continue
        x0, x1 = int(xs.min()), int(xs.max())
        height = y1 - y0 + 1
        width = x1 - x0 + 1
        if not 18 <= height <= 45 or width < 60:
            continue
        crop_ink = band[:, x0 : x1 + 1]
        interior = (
            crop_ink[1:-1, 1:-1]
            & crop_ink[:-2, 1:-1]
            & crop_ink[2:, 1:-1]
            & crop_ink[1:-1, :-2]
            & crop_ink[1:-1, 2:]
        )
        ink_count = int(crop_ink.sum())
        line_metrics.append(
            {
                "bbox": [x0, y0, x1 + 1, y1 + 1],
                "density": float(ink_count / crop_ink.size),
                "interior_ratio": float(interior.sum() / max(ink_count, 1)),
            }
        )
    if not line_metrics:
        return [], []

    median_density = float(np.median([item["density"] for item in line_metrics]))
    median_interior = float(
        np.median([item["interior_ratio"] for item in line_metrics])
    )
    density_threshold = max(0.20, median_density * 1.3)
    interior_threshold = max(0.12, median_interior * 2.0)
    candidates: list[dict[str, object]] = []
    output_metrics: list[dict[str, object]] = []
    for item in line_metrics:
        is_bold = bool(
            item["density"] >= density_threshold
            and item["interior_ratio"] >= interior_threshold
        )
        x0, y0, x1, y1 = item["bbox"]
        output_metrics.append(
            {
                "bbox": item["bbox"],
                "density": round(float(item["density"]), 3),
                "interior_ratio": round(float(item["interior_ratio"]), 3),
                "is_bold_candidate": is_bold,
            }
        )
        if is_bold:
            candidates.append(
                {
                    **item,
                    "crop": image.crop(
                        (
                            max(0, x0 - 8),
                            max(0, y0 - 5),
                            min(image.width, x1 + 8),
                            min(image.height, y1 + 5),
                        )
                    ),
                }
            )
    return candidates, output_metrics


def horizontal_text_runs(ink: np.ndarray) -> list[tuple[int, int]]:
    projection = ink.sum(axis=1)
    runs: list[tuple[int, int]] = []
    start: int | None = None
    last: int | None = None
    for y, count in enumerate(projection):
        if count > 5:
            if start is None:
                start = y
            last = y
        elif start is not None and last is not None and y - last > 5:
            runs.append((start, last))
            start = None
            last = None
    if start is not None and last is not None:
        runs.append((start, last))
    return runs


def image_data_url(image: Image.Image, *, image_format: str = "JPEG") -> str:
    buffer = io.BytesIO()
    save_args = {"optimize": True}
    if image_format.upper() == "JPEG":
        save_args["quality"] = 90
    image.save(buffer, format=image_format, **save_args)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/{image_format.lower()};base64,{encoded}"


def render_pdf_pages(
    path: Path, page_indexes: list[int]
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    with fitz.open(path) as document:
        for page_index in page_indexes:
            page = document.load_page(page_index)
            longest_edge = max(float(page.rect.width), float(page.rect.height), 1.0)
            scale = min(3.0, VISION_MAX_IMAGE_EDGE / longest_edge)
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale),
                colorspace=fitz.csRGB,
                alpha=False,
            )
            image = Image.frombytes(
                "RGB", (pixmap.width, pixmap.height), pixmap.samples
            )
            for region, crop in (
                ("上部", image.crop((0, 0, image.width, int(image.height * 0.42)))),
                (
                    "中部",
                    image.crop(
                        (
                            0,
                            int(image.height * 0.29),
                            image.width,
                            int(image.height * 0.71),
                        )
                    ),
                ),
                (
                    "下部",
                    image.crop(
                        (0, int(image.height * 0.58), image.width, image.height)
                    ),
                ),
            ):
                buffer = io.BytesIO()
                crop.save(buffer, format="JPEG", quality=90, optimize=True)
                encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
                output.append(
                    {
                        "page_no": page_index + 1,
                        "region": region,
                        "image_url": f"data:image/jpeg;base64,{encoded}",
                    }
                )
    return output


def analyze_visual_batch(
    client: OpenAI,
    *,
    model: str,
    rendered_pages: list[dict[str, object]],
    prompt: str = VISION_PROMPT,
) -> list[dict[str, object]]:
    content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
    expected_page_nos = []
    for page in rendered_pages:
        page_no = int(page["page_no"])
        if page_no not in expected_page_nos:
            expected_page_nos.append(page_no)
        region = str(page.get("region") or "整页")
        content.extend(
            [
                {
                    "type": "text",
                    "text": f"下面是 PDF 第 {page_no} 页的{region}；同页不同区域的结果要合并：",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": str(page["image_url"])},
                },
            ]
        )

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        temperature=0,
        response_format={"type": "json_object"},
        extra_body={"enable_thinking": False},
    )
    raw = response.choices[0].message.content or ""
    payload = parse_json_object(raw)
    returned = {
        int(item.get("page_no") or 0): item
        for item in list(payload.get("pages") or [])
        if isinstance(item, dict)
    }
    return [
        normalize_visual_page(returned.get(page_no, {}), page_no)
        for page_no in expected_page_nos
    ]


def normalize_visual_page(
    value: dict[str, object], page_no: int
) -> dict[str, object]:
    return {
        "page_no": page_no,
        "announcement_clause_nos": normalize_clause_numbers(
            value.get("announcement_clause_nos")
        ),
        "bold_clause_nos": normalize_clause_numbers(value.get("bold_clause_nos")),
        "has_bold_rule": bool(value.get("has_bold_rule")),
        "has_explicit_no_mandatory": bool(
            value.get("has_explicit_no_mandatory")
        ),
        "evidence_text": [
            str(item).strip()[:200]
            for item in list(value.get("evidence_text") or [])[:2]
            if str(item).strip()
        ],
        "confidence": normalize_confidence(value.get("confidence")),
    }


def normalize_clause_numbers(value: object) -> list[str]:
    if isinstance(value, str):
        items = CLAUSE_NO_PATTERN.findall(value)
    elif isinstance(value, list):
        items = []
        for item in value:
            items.extend(CLAUSE_NO_PATTERN.findall(str(item)))
    else:
        items = []
    output = []
    for item in items:
        clause_no = item.replace("．", ".").replace("。", ".")
        if clause_no not in output:
            output.append(clause_no)
    return output


def normalize_confidence(value: object) -> float:
    try:
        return round(max(0.0, min(float(value), 1.0)), 3)
    except (TypeError, ValueError):
        return 0.0


def parse_json_object(value: str) -> dict[str, object]:
    clean = value.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        start = clean.find("{")
        end = clean.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("视觉模型未返回有效 JSON")
        parsed = json.loads(clean[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("视觉模型返回结果不是 JSON 对象")
    return parsed
