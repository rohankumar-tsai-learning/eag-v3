from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import BaseModel, Field

from config import Settings
from llm_client import GeminiClient
from schemas import (
    HistoryEvent,
    MemoryClassification,
    MemoryFilterRequest,
    MemoryItem,
    MemoryReadRequest,
    MemoryReadResponse,
    MemoryRecordOutcomeRequest,
    MemoryRelevantRequest,
    MemoryRememberRequest,
)

STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "of",
    "for",
    "on",
    "in",
    "at",
    "is",
    "are",
    "be",
    "was",
    "were",
    "it",
    "this",
    "that",
    "with",
    "from",
    "by",
    "as",
    "my",
    "me",
    "we",
    "you",
    "your",
}


class _MemoryRankOutput(BaseModel):
    selected_ids: list[str] = Field(default_factory=list)


class MemoryService:
    def __init__(self, settings: Settings, llm: GeminiClient) -> None:
        self.settings = settings
        self.llm = llm
        self.path = settings.memory_path
        self._items: list[MemoryItem] | None = None

    def read(self, request: MemoryReadRequest) -> MemoryReadResponse:
        self._load()
        assert self._items is not None

        candidates = self._items
        if request.kinds:
            allowed = set(request.kinds)
            candidates = [item for item in candidates if item.kind in allowed]

        query_text = f"{request.query}\n{self._history_digest(request.history)}"
        q_tokens = self._tokens(query_text)

        scored: list[tuple[int, MemoryItem]] = []
        for item in candidates:
            keyword_tokens: set[str] = set()
            for kw in item.keywords:
                keyword_tokens |= self._tokens(kw)
            item_tokens = keyword_tokens | self._tokens(item.descriptor)
            score = len(q_tokens.intersection(item_tokens))
            if score > 0:
                scored.append((score, item))

        scored.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
        top = [item for _, item in scored[: request.top_k]]
        return MemoryReadResponse(hits=top)

    def filter(self, request: MemoryFilterRequest) -> MemoryReadResponse:
        self._load()
        assert self._items is not None

        items = self._items
        if request.kinds:
            allowed = set(request.kinds)
            items = [item for item in items if item.kind in allowed]
        if request.goal_id:
            items = [item for item in items if item.goal_id == request.goal_id]
        if request.recent is not None:
            items = sorted(items, key=lambda i: i.created_at, reverse=True)[: request.recent]
        return MemoryReadResponse(hits=items)

    async def relevant(self, request: MemoryRelevantRequest) -> MemoryReadResponse:
        filtered = self.filter(MemoryFilterRequest(kinds=request.kinds, recent=30)).hits
        if not filtered:
            return MemoryReadResponse(hits=[])

        prompt_lines = [f"query: {request.query}", "candidates:"]
        for item in filtered:
            prompt_lines.append(
                f"- id={item.id} kind={item.kind} descriptor={item.descriptor}"
            )
        prompt = "\n".join(prompt_lines)

        out = await self.llm.generate_typed(
            role="memory",
            system_prompt=(
                "Select the most relevant memory candidate IDs for the query. "
                "Return only selected_ids as a JSON list."
            ),
            user_prompt=prompt,
            response_model=_MemoryRankOutput,
            temperature=self.settings.memory_temperature,
        )

        ids = set(out.selected_ids[: request.top_k])
        picked = [item for item in filtered if item.id in ids]
        return MemoryReadResponse(hits=picked)

    async def remember(self, request: MemoryRememberRequest) -> MemoryItem:
        self._load()
        assert self._items is not None

        classify_prompt = (
            "Classify user text into one memory item with fields: kind, keywords, "
            "descriptor, value, confidence.\n"
            "Kinds: fact, preference, tool_outcome, scratchpad.\n"
            "Use tool_outcome only when the text clearly describes a completed tool action.\n"
            "Use concise descriptor. Extract useful keywords.\n"
            f"Text: {request.raw_text}"
        )

        classified = await self.llm.generate_typed(
            role="memory",
            system_prompt="You are a strict memory classifier for an agent architecture.",
            user_prompt=classify_prompt,
            response_model=MemoryClassification,
            temperature=self.settings.memory_temperature,
        )

        if request.source == "user_query" and classified.kind == "tool_outcome":
            classified = classified.model_copy(update={"kind": "scratchpad"})

        keywords = [token for token in classified.keywords if token.strip()]
        if not keywords:
            keywords = sorted(self._tokens(classified.descriptor))[:12]

        item = MemoryItem(
            id=f"mem:{uuid.uuid4().hex[:12]}",
            kind=classified.kind,
            keywords=keywords,
            descriptor=classified.descriptor.strip()[:200],
            value=classified.value,
            artifact_id=None,
            source=request.source,
            run_id=request.run_id,
            goal_id=request.goal_id,
            confidence=classified.confidence,
        )
        self._items.append(item)
        self._save()
        return item

    def record_outcome(self, request: MemoryRecordOutcomeRequest) -> MemoryItem:
        self._load()
        assert self._items is not None

        descriptor = request.result_text.strip().replace("\n", " ")[:200]
        arg_tokens = self._tokens(json.dumps(request.tool_call.arguments, ensure_ascii=False))
        keywords = sorted(set(arg_tokens | self._tokens(request.tool_call.name) | self._tokens(descriptor)))

        item = MemoryItem(
            id=f"mem:{uuid.uuid4().hex[:12]}",
            kind="tool_outcome",
            keywords=keywords[:20],
            descriptor=f"{request.tool_call.name}: {descriptor}",
            value={
                "tool_name": request.tool_call.name,
                "arguments": request.tool_call.arguments,
                "result_text": request.result_text[:6000],
            },
            artifact_id=request.artifact_id,
            source=request.source,
            run_id=request.run_id,
            goal_id=request.goal_id,
            confidence=1.0,
        )
        self._items.append(item)
        self._save()
        return item

    def _load(self) -> None:
        if self._items is not None:
            return
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")
        raw = self.path.read_text(encoding="utf-8")
        data = json.loads(raw)
        self._items = [MemoryItem.model_validate(item) for item in data]

    def _save(self) -> None:
        assert self._items is not None
        payload = [item.model_dump(mode="json") for item in self._items]
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _history_digest(self, history: list[HistoryEvent]) -> str:
        lines: list[str] = []
        for event in history[-6:]:
            if event.kind == "action":
                lines.append(
                    f"action goal={event.goal_id} tool={event.tool} descriptor={event.result_descriptor[:120]}"
                )
            else:
                lines.append(f"answer goal={event.goal_id} text={event.text[:120]}")
        return "\n".join(lines)

    def _tokens(self, text: str) -> set[str]:
        cleaned = []
        for ch in text.lower():
            if ch.isalnum() or ch in {"_", "-"}:
                cleaned.append(ch)
            else:
                cleaned.append(" ")
        tokens = {tok for tok in "".join(cleaned).split() if tok and tok not in STOPWORDS and len(tok) > 1}
        return tokens
