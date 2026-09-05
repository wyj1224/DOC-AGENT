import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


EvaluationStatus = Literal[
    "success",
    "retryable_failure",
    "manual_review",
    "terminal_failure",
]


class AgentAction(BaseModel):
    """The only model-controlled instruction accepted by the runner."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["call_tool", "finish", "manual_review"]
    tool: str = ""
    args: dict = Field(default_factory=dict)
    reason_summary: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "call_tool" and not self.tool:
            raise ValueError("call_tool 必须指定 tool")
        if self.action != "call_tool" and (self.tool or self.args):
            raise ValueError("finish/manual_review 不得携带工具或参数")
        return self


class ToolObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    tool: str
    result: dict = Field(default_factory=dict)
    error: str = ""


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: EvaluationStatus
    summary: str
    failed_checks: list[str] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)
    retry_strategy: str = ""


class ReflectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_code: str = Field(max_length=64)
    failure_stage: str = Field(default="", max_length=64)
    failure_summary: str = Field(max_length=1000)
    lesson: str = Field(max_length=1000)
    retry_strategy: str = Field(max_length=1000)
    corrective_actions: list[str] = Field(default_factory=list, max_length=8)


def parse_json_model(raw: str, model_type: type[BaseModel]) -> BaseModel:
    """Parse a JSON object even when a model wrapped it in a Markdown fence."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return model_type.model_validate(json.loads(text))
