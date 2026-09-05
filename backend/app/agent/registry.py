from dataclasses import dataclass
from typing import Callable

from app.agent.tools import (
    completeness_check_tool,
    get_issues_tool,
    word_check_tool,
)
from app.agent.word_edit_tools import (
    apply_word_edit_tool,
    inspect_consistency_issues_tool,
    prepare_word_edit_tool,
    verify_word_edit_tool,
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    func: Callable
    description: str
    args: str


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "word_check_tool": ToolSpec(
        name="word_check_tool",
        func=word_check_tool,
        description="统一执行依据章节 vs 标准库、正文 vs 依据章节两类检查，并写入 check_issues。",
        args='{"document_id": 1, "replace": true, "issue_limit": 1}',
    ),
    "completeness_check_tool": ToolSpec(
        name="completeness_check_tool",
        func=completeness_check_tool,
        description="自动匹配模板，检查缺少章节、正文为空和占位符，并逐项比较安全生产要求、工程验收、电磁防护与环境保护三章及其子章节编号；低于 95% 报警。",
        args='{"document_id": 1, "replace": true, "issue_limit": 50}，必要时可传 {"template_id": 1}',
    ),
    "get_issues_tool": ToolSpec(
        name="get_issues_tool",
        func=get_issues_tool,
        description="查询检查结果，可按 check_scope、issue_type、severity 过滤。",
        args='{"document_id": 1, "check_scope": "basis_excel", "issue_limit": 50}',
    ),
    "inspect_consistency_issues_tool": ToolSpec(
        name="inspect_consistency_issues_tool",
        func=inspect_consistency_issues_tool,
        description="检查当前 Word 工作副本，返回可安全修改的一致性问题；只接受当前 edit_run_id。",
        args='{"edit_run_id": 1}',
    ),
    "prepare_word_edit_tool": ToolSpec(
        name="prepare_word_edit_tool",
        func=prepare_word_edit_tool,
        description="从数据库问题生成可信修改指令，并追加到同一个 WordEditRun.changes。LLM 只能选择 issue_id。",
        args='{"edit_run_id": 1, "selected_issue_ids": [1, 2], "expected_document_id": 1}',
    ),
    "apply_word_edit_tool": ToolSpec(
        name="apply_word_edit_tool",
        func=apply_word_edit_tool,
        description="只读取并执行当前 edit_run 中最新一批 pending changes，生成新的 Word 副本。",
        args='{"edit_run_id": 1}',
    ),
    "verify_word_edit_tool": ToolSpec(
        name="verify_word_edit_tool",
        func=verify_word_edit_tool,
        description="重新解析最新 Word 副本并复检，把观察结果交还给 Agent 决定继续或结束。",
        args='{"edit_run_id": 1}',
    ),
}


WORD_EDIT_TOOL_NAMES = (
    "inspect_consistency_issues_tool",
    "prepare_word_edit_tool",
    "apply_word_edit_tool",
    "verify_word_edit_tool",
)
def word_edit_tool_prompt_text() -> str:
    return prompt_text(WORD_EDIT_TOOL_NAMES)


def prompt_text(tool_names: tuple[str, ...]) -> str:
    lines = []
    for index, tool_name in enumerate(tool_names, start=1):
        tool = TOOL_REGISTRY[tool_name]
        lines.append(f"{index}. {tool.name}\n   参数：{tool.args}\n   作用：{tool.description}")
    return "\n\n".join(lines)


def run_tool(tool_name: str, args: dict[str, object]) -> dict[str, object]:
    return TOOL_REGISTRY[tool_name].func(**args)
