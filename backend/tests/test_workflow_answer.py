from app.agent.workflow import ensure_answer_issue_count


def test_answer_total_is_added_when_model_omits_it():
    answer = ensure_answer_issue_count("结论\n发现若干引用问题。", 12)
    assert answer.startswith("本次检查共发现 12 个问题。")


def test_answer_total_is_corrected_when_model_reports_wrong_count():
    answer = ensure_answer_issue_count("本次检查共发现 8 个问题。\n详细说明", 12)
    assert answer == "本次检查共发现 12 个问题。\n详细说明"
