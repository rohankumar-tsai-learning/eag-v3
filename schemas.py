from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MemoryKind = Literal["fact", "preference", "tool_outcome", "scratchpad"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryItem(BaseModel):
    id: str
    kind: MemoryKind
    keywords: list[str] = Field(default_factory=list)
    descriptor: str
    value: dict[str, Any] = Field(default_factory=dict)
    artifact_id: str | None = None
    source: str
    run_id: str
    goal_id: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=utc_now)


class Artifact(BaseModel):
    id: str
    content_type: str
    size_bytes: int
    source: str
    descriptor: str


class Goal(BaseModel):
    id: str
    text: str
    done: bool = False
    attach_artifact_id: str | None = None


class ScenarioMeta(BaseModel):
    name: str
    display_name: str
    query_type: str | None = None
    expected_iterations: int
    max_pass_iterations: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class Observation(BaseModel):
    goals: list[Goal] = Field(default_factory=list)

    @property
    def all_done(self) -> bool:
        return bool(self.goals) and all(goal.done for goal in self.goals)

    def next_unfinished(self) -> Goal | None:
        for goal in self.goals:
            if not goal.done:
                return goal
        return None


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class DecisionOutput(BaseModel):
    answer: str | None = None
    tool_call: ToolCall | None = None

    @model_validator(mode="after")
    def exactly_one(self) -> "DecisionOutput":
        if (self.answer is None) == (self.tool_call is None):
            raise ValueError("Exactly one of answer or tool_call must be populated")
        return self

    @property
    def is_answer(self) -> bool:
        return self.answer is not None


class PerceptionGoalDraft(BaseModel):
    text: str
    done: bool = False
    attach_artifact_index: int | None = None


class PerceptionRawOutput(BaseModel):
    goals: list[PerceptionGoalDraft] = Field(default_factory=list)


class MemoryClassification(BaseModel):
    kind: MemoryKind
    keywords: list[str] = Field(default_factory=list)
    descriptor: str
    value: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)

    @field_validator("keywords", mode="before")
    @classmethod
    def _coerce_keywords(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()]
        if isinstance(v, str):
            text = v.replace(";", ",")
            parts = [part.strip() for part in text.split(",")]
            return [part for part in parts if part]
        return [str(v).strip()] if str(v).strip() else []

    @field_validator("value", mode="before")
    @classmethod
    def _coerce_value(cls, v: Any) -> dict[str, Any]:
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            text = v.strip()
            return {"text": text} if text else {}
        if isinstance(v, list):
            return {"items": v}
        return {"raw": str(v)}


class AttachedArtifact(BaseModel):
    artifact_id: str
    text: str
    size_bytes: int


class HistoryActionEvent(BaseModel):
    iter: int
    kind: Literal["action"] = "action"
    goal_id: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_descriptor: str
    artifact_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class HistoryAnswerEvent(BaseModel):
    iter: int
    kind: Literal["answer"] = "answer"
    goal_id: str
    text: str
    created_at: datetime = Field(default_factory=utc_now)


HistoryEvent = Annotated[
    HistoryActionEvent | HistoryAnswerEvent,
    Field(discriminator="kind"),
]


class MemoryReadRequest(BaseModel):
    query: str
    history: list[HistoryEvent] = Field(default_factory=list)
    kinds: list[MemoryKind] | None = None
    top_k: int = 8


class MemoryReadResponse(BaseModel):
    hits: list[MemoryItem]


class MemoryFilterRequest(BaseModel):
    kinds: list[MemoryKind] | None = None
    goal_id: str | None = None
    recent: int | None = None


class MemoryRelevantRequest(BaseModel):
    query: str
    kinds: list[MemoryKind] | None = None
    top_k: int = 5


class MemoryRememberRequest(BaseModel):
    raw_text: str
    source: str
    run_id: str
    goal_id: str | None = None


class MemoryRecordOutcomeRequest(BaseModel):
    tool_call: ToolCall
    result_text: str
    artifact_id: str | None = None
    run_id: str
    goal_id: str | None = None
    source: str = "action"


class PerceptionInput(BaseModel):
    query: str
    hits: list[MemoryItem] = Field(default_factory=list)
    history: list[HistoryEvent] = Field(default_factory=list)
    prior_goals: list[Goal] = Field(default_factory=list)
    run_id: str
    scenario_name: str | None = None
    scenario_meta: ScenarioMeta | None = None


class DecisionInput(BaseModel):
    goal: Goal
    hits: list[MemoryItem] = Field(default_factory=list)
    attached: list[AttachedArtifact] = Field(default_factory=list)
    history: list[HistoryEvent] = Field(default_factory=list)
    mcp_tools: list[dict[str, Any]] = Field(default_factory=list)
    scenario_name: str | None = None
    scenario_meta: ScenarioMeta | None = None


class ActionInput(BaseModel):
    tool_call: ToolCall
    run_id: str
    goal_id: str | None = None


class ActionOutput(BaseModel):
    descriptor: str
    artifact_id: str | None = None
