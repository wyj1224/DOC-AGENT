import unittest

from app.services.key_section_diff import compare_key_sections, extract_key_sections


class KeySectionDiffTest(unittest.TestCase):
    def test_extracts_three_root_subtrees(self):
        sections = [
            section(0, 1, "1", "安全生产要求", "安全正文"),
            section(1, 2, "1.1", "施工安全", "施工正文"),
            section(2, 1, "2", "工程验收", "验收正文"),
            section(3, 2, "2.1", "验收资料", "资料正文"),
            section(4, 1, "3", "电磁防护与环境保护", "环保正文"),
        ]

        extracted = extract_key_sections(sections)

        self.assertEqual([item["section_key"] for item in extracted], [
            "safety_production",
            "project_acceptance",
            "emc_environment",
        ])
        self.assertIn("1.1 施工安全", extracted[0]["raw_text"])
        self.assertNotIn("工程验收", extracted[0]["raw_text"])

    def test_reports_child_heading_number_change(self):
        template = extract_key_sections([
            section(0, 1, "1", "安全生产要求", "安全正文"),
            section(1, 2, "1.1", "施工安全", "施工正文"),
        ])[0]
        document = extract_key_sections([
            section(0, 1, "1", "安全生产要求", "安全正文"),
            section(1, 2, "1.2", "施工安全", "施工正文"),
        ])[0]

        result = compare_key_sections(template, document)

        number_changes = [item for item in result["differences"] if item["type"] == "heading_no_changed"]
        self.assertEqual(len(number_changes), 1)
        self.assertEqual(number_changes[0]["template_text"], "1.1")
        self.assertEqual(number_changes[0]["document_text"], "1.2")
        self.assertLess(result["similarity_percent"], 100)

    def test_reports_added_deleted_and_modified_content(self):
        template = extract_key_sections([
            section(0, 1, "1", "工程验收", "第一段\n第二段\n删除段"),
        ])[0]
        document = extract_key_sections([
            section(0, 1, "1", "工程验收", "第一段\n第二段已修改\n新增段"),
        ])[0]

        result = compare_key_sections(template, document)

        self.assertTrue(result["differences"])
        self.assertIn("modified", {item["type"] for item in result["differences"]})
        self.assertLess(result["similarity_percent"], 100)


def section(index: int, level: int, heading_no: str, title: str, body: str) -> dict[str, object]:
    return {
        "section_index": index,
        "paragraph_start": index * 10,
        "paragraph_end": index * 10 + max(1, len(body.splitlines())),
        "level": level,
        "heading_no": heading_no,
        "title": title,
        "full_title": f"{heading_no} {title}",
        "section_path": title,
        "body_text": body,
    }


if __name__ == "__main__":
    unittest.main()
