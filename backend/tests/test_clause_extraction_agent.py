import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent.workflow import (
    allowed_clause_extraction_actions,
    run_clause_extraction_loop,
)
from app.services.clause_extraction import (
    aggregate_visual_evidence,
    continuation_pages_to_refine,
    detect_clause_signals,
    extract_candidates_from_pages,
    inspect_pdf_visual_evidence,
    merge_visual_signals,
    parsed_pages_are_usable,
)


def extraction_state(status: str, *, requires_review: bool = False) -> dict[str, object]:
    return {
        "extraction_run_id": 31,
        "status": status,
        "file_name": "测试规范.pdf",
        "mandatory_status": "present" if status == "verified" else "",
        "detection_methods": ["announcement_list"],
        "page_count": 3,
        "clause_count": 2 if status in ("extracted", "verified") else 0,
        "listed_clause_count": 2,
        "missing_clause_count": 0,
        "requires_review": requires_review,
        "error_message": "",
    }


class ClauseExtractionAgentLoopTest(unittest.TestCase):
    @patch("app.agent.workflow.fail_clause_extraction_run")
    @patch("app.agent.workflow.finalize_clause_extraction_run")
    @patch("app.agent.workflow.append_clause_extraction_trace")
    @patch("app.agent.workflow.run_tool")
    @patch("app.agent.workflow.get_clause_extraction_state")
    @patch("app.agent.workflow.start_clause_extraction_run")
    @patch("app.agent.workflow.call_llm")
    def test_agent_runs_inspect_extract_verify_finish(
        self,
        call_llm,
        start_run,
        get_state,
        run_tool,
        append_trace,
        finalize,
        fail_run,
    ):
        call_llm.side_effect = [
            json.dumps({"action": "call_tool", "tool": "inspect_clause_pdf_tool", "reason": "先检查 PDF"}),
            json.dumps({"action": "call_tool", "tool": "extract_clause_candidates_tool", "reason": "按证据抽取"}),
            json.dumps({"action": "call_tool", "tool": "verify_clause_candidates_tool", "reason": "核对条号和正文"}),
            json.dumps({"action": "finish", "reason": "证据完整"}),
        ]
        start_run.return_value = extraction_state("planning")
        get_state.side_effect = [
            extraction_state("planning"),
            extraction_state("inspected"),
            extraction_state("extracted"),
            extraction_state("verified"),
        ]
        tool_results = {
            "inspect_clause_pdf_tool": {"status": "inspected", "page_count": 3},
            "extract_clause_candidates_tool": {"status": "extracted", "clause_count": 2},
            "verify_clause_candidates_tool": {
                "status": "verified",
                "mandatory_status": "present",
                "requires_review": False,
            },
        }
        run_tool.side_effect = lambda name, args: tool_results[name]
        finalize.return_value = {
            "status": "completed",
            "extraction_run_id": 31,
            "clause_count": 2,
        }

        result = run_clause_extraction_loop(
            message="自动抽取这个 PDF 的强条",
            file_path="/tmp/测试规范.pdf",
            owner_user_id=7,
            session_id=9,
        )

        self.assertEqual(result["status"], "completed")
        start_run.assert_called_once_with(
            file_path="/tmp/测试规范.pdf", owner_user_id=7, session_id=9
        )
        self.assertEqual(
            [item.args[0] for item in run_tool.call_args_list],
            [
                "inspect_clause_pdf_tool",
                "extract_clause_candidates_tool",
                "verify_clause_candidates_tool",
            ],
        )
        self.assertTrue(all(item.args[1]["extraction_run_id"] == 31 for item in run_tool.call_args_list))
        self.assertGreater(append_trace.call_count, run_tool.call_count)
        finalize.assert_called_once_with(
            extraction_run_id=31,
            owner_user_id=7,
            action="finish",
            reason="证据完整",
        )
        fail_run.assert_not_called()

    @patch("app.agent.workflow.fail_clause_extraction_run")
    @patch("app.agent.workflow.get_clause_extraction_state")
    @patch("app.agent.workflow.start_clause_extraction_run")
    @patch("app.agent.workflow.call_llm")
    def test_disallowed_action_fails_closed(self, call_llm, start_run, get_state, fail_run):
        start_run.return_value = extraction_state("planning")
        get_state.return_value = extraction_state("planning")
        call_llm.return_value = json.dumps(
            {"action": "call_tool", "tool": "verify_clause_candidates_tool", "reason": "跳过检查"}
        )

        with self.assertRaisesRegex(ValueError, "不允许的动作"):
            run_clause_extraction_loop(
                message="抽取强条", file_path="/tmp/测试规范.pdf", owner_user_id=7
            )

        fail_run.assert_called_once()

    def test_verified_review_state_cannot_finish(self):
        self.assertEqual(
            allowed_clause_extraction_actions(
                extraction_state("verified", requires_review=True)
            ),
            [{"action": "manual_review"}],
        )

    @patch("app.services.clause_extraction.analyze_pdf_bold_lines")
    @patch("app.services.clause_extraction.analyze_pdf_visual_evidence")
    def test_announcement_has_priority_over_bold_full_scan(
        self, analyze_visual, analyze_bold
    ):
        analyze_visual.return_value = {
            "model": "vision-test",
            "pages": [
                {
                    "page_no": 3,
                    "announcement_clause_nos": ["1.0.2", "3.1.1"],
                    "bold_clause_nos": [],
                    "has_bold_rule": False,
                    "has_explicit_no_mandatory": False,
                },
                {
                    "page_no": 5,
                    "announcement_clause_nos": [],
                    "bold_clause_nos": [],
                    "has_bold_rule": True,
                    "has_explicit_no_mandatory": False,
                },
            ],
        }

        result = inspect_pdf_visual_evidence(Path("announcement.pdf"), 534)

        self.assertEqual(result["listed_clause_nos"], ["1.0.2", "3.1.1"])
        self.assertEqual(result["vision_scanned_page_count"], 2)
        analyze_visual.assert_called_once()
        analyze_bold.assert_not_called()

    def test_announced_clause_numbers_are_matched_to_body(self):
        pages = [
            "现批准《测试规范》为国家标准，编号为 GB 50011-2010。"
            "其中，第 1.0.2、3.1.1 条为强制性条文，必须严格执行。",
            "# 1.0.2 建筑抗震设防必须符合规定。\n\n# 1.0.3 其他规定。",
            "# 3.1.1 建筑工程应按规定确定抗震设防类别。",
        ]

        inspection = detect_clause_signals(pages, "GB 50011-2010 测试规范.pdf")
        clauses = extract_candidates_from_pages(
            pages, listed_clause_nos=list(inspection["listed_clause_nos"])
        )

        self.assertEqual(inspection["detection_methods"], ["announcement_list"])
        self.assertEqual(inspection["listed_clause_nos"], ["1.0.2", "3.1.1"])
        self.assertEqual([item["clause_no"] for item in clauses], ["1.0.2", "3.1.1"])
        self.assertTrue(all(item["evidence_type"] == "announcement_and_body" for item in clauses))

    def test_bold_clause_number_uses_following_body_text(self):
        pages = [
            "本规范中以黑体字标志的条文为强制性条文。",
            "2.0.10 机房内严禁存放易燃、易爆物品。\n\n2.0.11 其他要求。",
        ]

        inspection = detect_clause_signals(pages, "测试规范.pdf")
        clauses = extract_candidates_from_pages(
            pages,
            listed_clause_nos=[],
            visual_bold_clause_nos=["2.0.10"],
        )

        self.assertIn("bold_rule", inspection["detection_methods"])
        self.assertEqual(len(clauses), 1)
        self.assertEqual(clauses[0]["clause_no"], "2.0.10")
        self.assertIn("严禁存放", clauses[0]["clause_text"])

    def test_watermark_only_parse_is_low_quality(self):
        inspection = detect_clause_signals(
            ["# 住房城乡建设部信息公开\n\n浏览专用"] * 8,
            "扫描型规范.pdf",
        )

        self.assertEqual(inspection["parse_quality"], "low")
        self.assertEqual(inspection["detection_methods"], ["no_evidence"])

    def test_empty_page_slots_are_not_a_reusable_ocr_cache(self):
        self.assertFalse(parsed_pages_are_usable([""] * 534, 534))
        self.assertTrue(
            parsed_pages_are_usable(
                ["1.0.1 有效规范正文。" * 10] * 534,
                534,
            )
        )

    def test_strict_visual_bold_result_does_not_infer_from_semantics(self):
        pages = [
            "# 总则\n\n"
            "1.0.5 在施工中不得安装损坏设备。\n"
            "1.0.6 在七度地区使用的设备必须满足抗震要求。",
            "# 机房环境和安全\n\n"
            "2.0.8 电源设备应采取防水措施。\n"
            "2.0.10 机房内严禁存放易燃、易爆等危险物品。",
        ]

        clauses = extract_candidates_from_pages(
            pages,
            listed_clause_nos=[],
            visual_bold_clause_nos=["1.0.6", "2.0.10"],
        )

        self.assertEqual(
            [item["clause_no"] for item in clauses], ["1.0.6", "2.0.10"]
        )

    def test_visual_evidence_is_merged_without_markdown_bold_guess(self):
        visual_pages = [
            {
                "page_no": 6,
                "announcement_clause_nos": [],
                "bold_clause_nos": ["1.0.6"],
                "has_bold_rule": False,
                "has_explicit_no_mandatory": False,
            }
        ]
        visual = aggregate_visual_evidence(visual_pages)
        visual.update({"vision_completed": True, "vision_full_scan": True})
        text = detect_clause_signals(
            ["1.0.5 普通正文。\n1.0.6 原页确实为黑体。"], "测试规范.pdf"
        )
        inspection = merge_visual_signals(text, visual)

        self.assertEqual(inspection["visual_bold_clause_nos"], ["1.0.6"])
        self.assertEqual(inspection["detection_methods"], ["vision_bold_body"])

    def test_spaced_announcement_skips_toc_and_recovers_lost_last_digit(self):
        pages = [
            "关于发布国家标准《测试规范》的公告\n"
            "其中，第 1. 0. 2、3. 1. 1 条为强制性条文，必须严格执行。",
            "# 目录\n3.1 建筑抗震设防分类和设防标准 ........ 6",
            "# 总则\n\n1. O. 抗震设防地区的建筑必须进行抗震设计。",
            "# 3.1 建筑抗震设防分类和设防标准\n\n# 3.1.1\n\n"
            "抗震设防的所有建筑应确定其抗震设防类别及抗震设防标准。",
            "# 中华人民共和国国家标准\n# 条文说明\n# 3.1.1\n本条用于解释正文。",
        ]

        inspection = detect_clause_signals(pages, "测试规范.pdf")
        clauses = extract_candidates_from_pages(
            pages, listed_clause_nos=list(inspection["listed_clause_nos"])
        )

        self.assertEqual(inspection["announcement_pages"], [1])
        self.assertEqual(inspection["listed_clause_nos"], ["1.0.2", "3.1.1"])
        self.assertEqual([item["clause_no"] for item in clauses], ["1.0.2", "3.1.1"])
        self.assertEqual([item["page_no"] for item in clauses], [3, 4])
        self.assertEqual(
            clauses[0]["evidence_type"], "announcement_and_body_ocr_recovered"
        )
        self.assertNotIn("解释正文", clauses[1]["clause_text"])

    def test_cross_page_clause_merges_continuation_and_ignores_page_footer(self):
        pages = [
            "# 总则\n\n1.0.2 建筑结构必须满足下列跨页要求，具体措施应\n• 15 •",
            "符合本规范规定。\n\n1.0.3 其他一般规定。\n16",
        ]

        clauses = extract_candidates_from_pages(
            pages, listed_clause_nos=["1.0.2"]
        )
        continuation_pages = continuation_pages_to_refine(
            pages, clauses, [1]
        )

        self.assertEqual(continuation_pages, [2])
        self.assertEqual(len(clauses), 1)
        self.assertEqual(
            clauses[0]["clause_text"],
            "建筑结构必须满足下列跨页要求，具体措施应 符合本规范规定。",
        )
        self.assertNotIn("15", clauses[0]["clause_text"])


if __name__ == "__main__":
    unittest.main()
