import json
import unittest
from types import SimpleNamespace

import numpy as np
from PIL import Image

from app.services.pdf_vision import (
    analyze_visual_batch,
    detect_bold_line_regions,
    normalize_visual_page,
    parse_json_object,
)


class PdfVisionTest(unittest.TestCase):
    def test_normalize_visual_page_keeps_only_clause_numbers(self):
        result = normalize_visual_page(
            {
                "announcement_clause_nos": "第 1.0.6、2.0.10 条",
                "announcement_clause_refs": ["5.1.9#7", "5.1.9第8款"],
                "bold_clause_nos": ["3．3．5", "不是条号"],
                "has_bold_rule": True,
                "confidence": 1.4,
            },
            6,
        )

        self.assertEqual(result["announcement_clause_nos"], ["1.0.6", "2.0.10"])
        self.assertEqual(result["announcement_clause_refs"], ["5.1.9#7", "5.1.9#8"])
        self.assertEqual(result["bold_clause_nos"], ["3.3.5"])
        self.assertTrue(result["has_bold_rule"])
        self.assertEqual(result["confidence"], 1.0)

    def test_analyze_batch_restores_missing_page_as_empty_evidence(self):
        payload = {
            "pages": [
                {
                    "page_no": 6,
                    "bold_clause_nos": ["1.0.6"],
                    "confidence": 0.99,
                }
            ]
        }
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(payload))
                )
            ]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_: response)
            )
        )

        results = analyze_visual_batch(
            client,
            model="vision-test",
            rendered_pages=[
                {"page_no": 6, "image_url": "data:image/jpeg;base64,AA=="},
                {"page_no": 7, "image_url": "data:image/jpeg;base64,AA=="},
            ],
        )

        self.assertEqual(results[0]["bold_clause_nos"], ["1.0.6"])
        self.assertEqual(results[1]["bold_clause_nos"], [])

    def test_parse_json_object_accepts_fenced_json(self):
        self.assertEqual(parse_json_object("```json\n{\"pages\": []}\n```"), {"pages": []})

    def test_pixel_line_filter_separates_heavy_body_line(self):
        pixels = np.full((260, 600), 255, dtype=np.uint8)
        for y in (20, 70, 120):
            for x in range(20, 560, 14):
                pixels[y : y + 24, x : x + 2] = 0
        for x in range(20, 560, 14):
            pixels[180:207, x : x + 9] = 0

        candidates, metrics = detect_bold_line_regions(Image.fromarray(pixels))

        self.assertEqual(len(candidates), 1)
        self.assertEqual(sum(bool(item["is_bold_candidate"]) for item in metrics), 1)


if __name__ == "__main__":
    unittest.main()
