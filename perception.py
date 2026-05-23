from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from config import Settings
from llm_client import GeminiClient
from schemas import Goal, Observation, PerceptionInput, PerceptionRawOutput

PERCEPTION_SYSTEM_PROMPT = """
You are the Perception role in a four-role architecture.

Responsibilities each iteration:
1) Maintain stable goal identity and order.
2) Mark goals done only when evidence supports completion.
3) Attach one relevant artifact by index for unfinished evidence-use goals when artifacts are available.

Rules:
- If prior_goals are provided, preserve count, ids, and order.
- If prior_goals are empty, generate a complete goal plan from query + scenario metadata.
- Use scenario_meta and goal_generation_constraints.scenario_metadata as planning hints, not deterministic rules.
- Keep goals atomic and concise.
- Prefer the smallest complete plan; avoid checklist-style meta goals.
- Do not turn operational/tool policies (blocked domains, retries, cooldowns, quotas, validation) into goals.
- When source artifacts are available, attach the most relevant artifact_index for extraction/analysis/synthesis goals.
- If an unfinished goal needs source-grounded extraction/analysis/synthesis and artifact_indices is non-empty, include attach_artifact_index.
- For multi-source reading goals, mark done only after enough successful distinct source fetches.
- For synthesis/recommendation goals, mark done only after an answer event exists for that goal.
- Mark done=true only when history or memory provides explicit evidence.
- Every returned goal item must include a non-empty text field.
- Do not invent artifact handles; only use provided artifact_index.
- Return strict JSON only.
""".strip()


class PerceptionRole:
    def __init__(self, settings: Settings, llm: GeminiClient) -> None:
        self.settings = settings
        self.llm = llm

    async def observe(self, request: PerceptionInput) -> Observation:
        base_goals = self._seed_goals(request)
        artifact_rows, idx_to_artifact = self._indexed_artifacts(request.hits, request.history)

        payload = {
            "query": request.query,
            "run_id": request.run_id,
            "scenario_name": request.scenario_name,
            "scenario_meta": request.scenario_meta.model_dump() if request.scenario_meta else None,
            "prior_goals": [goal.model_dump() for goal in base_goals],
            "history": [event.model_dump(mode="json") for event in request.history[-12:]],
            "memory_hits": [self._compact_hit(hit) for hit in request.hits[:12]],
            "artifact_indices": artifact_rows,
            "instructions": {
                "if_prior_goals_empty": "Generate a bounded end-to-end plan with stable goal order",
                "if_prior_goals_present": "Keep the same ids and order; update done/attachments only",
            },
            "goal_generation_constraints": self._goal_generation_constraints(request),
        }

        llm_output = await self.llm.generate_typed(
            role="perception",
            system_prompt=PERCEPTION_SYSTEM_PROMPT,
            user_prompt=json.dumps(payload, ensure_ascii=False, indent=2),
            response_model=PerceptionRawOutput,
            temperature=self.settings.perception_temperature,
        )

        merged = self._merge_goals(
            base_goals=base_goals,
            model_goals=llm_output.goals,
            idx_to_artifact=idx_to_artifact,
            request=request,
        )
        return Observation(goals=merged)

    def _seed_goals(self, request: PerceptionInput) -> list[Goal]:
        if request.prior_goals:
            return [Goal.model_validate(goal.model_dump()) for goal in request.prior_goals]
        return []

    def _merge_goals(
        self,
        *,
        base_goals: list[Goal],
        model_goals: list[Any],
        idx_to_artifact: dict[int, str],
        request: PerceptionInput,
    ) -> list[Goal]:
        merged: list[Goal] = []
        available_artifacts = set(idx_to_artifact.values())

        if not base_goals:
            return self._initial_goals(model_goals, idx_to_artifact, request)

        for idx, base in enumerate(base_goals):
            model_goal = model_goals[idx] if idx < len(model_goals) else None
            model_done = bool(getattr(model_goal, "done", False)) if model_goal else False
            model_attach = getattr(model_goal, "attach_artifact_index", None) if model_goal else None

            done = (
                base.done
                or self._goal_has_answer_evidence(base.id, request)
                or (model_done and self._goal_has_action_evidence(base.id, base.text, request))
            )
            attach_id = None
            if not done and base.attach_artifact_id in available_artifacts:
                attach_id = base.attach_artifact_id
            if not done and isinstance(model_attach, int):
                attach_id = idx_to_artifact.get(model_attach)
            if not done and not attach_id:
                attach_id = self._default_attach_artifact_id(base.text, idx_to_artifact, request)

            merged.append(
                Goal(
                    id=base.id,
                    text=base.text,
                    done=done,
                    attach_artifact_id=attach_id,
                )
            )

        return merged

    def _initial_goals(
        self,
        model_goals: list[Any],
        idx_to_artifact: dict[int, str],
        request: PerceptionInput,
    ) -> list[Goal]:
        drafted: list[tuple[str, Any | None]] = []
        for item in model_goals:
            text = str(getattr(item, "text", "")).strip()
            if text:
                drafted.append((text, item))

        metadata = request.scenario_meta.metadata if request.scenario_meta else {}
        goal_count_hint = metadata.get("goal_count_hint") if isinstance(metadata, dict) else None
        if isinstance(goal_count_hint, int) and goal_count_hint > 0 and len(drafted) > goal_count_hint:
            drafted = drafted[:goal_count_hint]

        if not drafted:
            drafted.append(("Complete the user request", None))

        initial: list[Goal] = []
        for idx, (text, model_goal) in enumerate(drafted):
            goal_id = f"g{idx + 1}"

            attach_id = None
            if model_goal and isinstance(getattr(model_goal, "attach_artifact_index", None), int):
                attach_id = idx_to_artifact.get(model_goal.attach_artifact_index)
            if not attach_id:
                attach_id = self._default_attach_artifact_id(text, idx_to_artifact, request)

            initial.append(
                Goal(
                    id=goal_id,
                    text=text,
                    done=False,
                    attach_artifact_id=attach_id,
                )
            )

        return initial

    def _goal_generation_constraints(self, request: PerceptionInput) -> dict[str, Any]:
        expected_iterations = request.scenario_meta.expected_iterations if request.scenario_meta else None
        max_pass_iterations = request.scenario_meta.max_pass_iterations if request.scenario_meta else None
        scenario_metadata = request.scenario_meta.metadata if request.scenario_meta else {}

        max_goal_count = 8
        if isinstance(max_pass_iterations, int) and max_pass_iterations > 0:
            max_goal_count = max(1, min(max_pass_iterations, 10))

        target_goal_count_hint = None
        raw_goal_hint = scenario_metadata.get("goal_count_hint") if isinstance(scenario_metadata, dict) else None
        if isinstance(raw_goal_hint, int) and raw_goal_hint > 0:
            target_goal_count_hint = max(1, min(raw_goal_hint, max_goal_count))
        elif isinstance(expected_iterations, int) and expected_iterations > 0:
            target_goal_count_hint = max(1, min(expected_iterations, max_goal_count))

        source_count_hint = self._source_count_from_text(request.query)

        return {
            "query_type_hint": request.scenario_meta.query_type if request.scenario_meta else None,
            "scenario_metadata": scenario_metadata,
            "target_goal_count_hint": target_goal_count_hint,
            "source_count_hint": source_count_hint,
            "max_goal_count": max_goal_count,
            "expected_iterations_hint": expected_iterations,
            "max_pass_iterations_hint": max_pass_iterations,
            "prefer_compact_goal_plan": True,
            "avoid_operational_policy_goals": True,
            "keep_order_stable_after_first_iteration": True,
        }

    def _goal_has_answer_evidence(self, goal_id: str, request: PerceptionInput) -> bool:
        for event in reversed(request.history):
            if getattr(event, "goal_id", None) != goal_id:
                continue

            if getattr(event, "kind", None) == "answer":
                text = str(getattr(event, "text", "")).strip()
                if text:
                    return True

        return False

    def _goal_has_action_evidence(self, goal_id: str, goal_text: str, request: PerceptionInput) -> bool:
        if self._goal_requires_answer_evidence(goal_text):
            return False

        lowered_goal = goal_text.lower()
        read_like_goal = any(
            token in lowered_goal
            for token in ("read", "access", "content", "source", "result", "fetch", "open")
        )
        required_reads = self._required_successful_source_reads(goal_text, request) if read_like_goal else 1
        successful_read_sources: set[str] = set()

        for event in reversed(request.history):
            if getattr(event, "goal_id", None) != goal_id:
                continue
            if getattr(event, "kind", None) != "action":
                continue

            tool_name = str(getattr(event, "tool", "")).lower().strip()
            if read_like_goal and "search" in tool_name and not any(
                token in tool_name for token in ("fetch", "read", "open")
            ):
                continue

            descriptor = str(getattr(event, "result_descriptor", "")).strip()
            if not descriptor:
                continue
            if descriptor in {"[]", "{}", "null"}:
                continue
            if self._action_failed(descriptor):
                continue

            if read_like_goal:
                arguments = getattr(event, "arguments", {}) or {}
                raw_url = arguments.get("url") if isinstance(arguments, dict) else None
                source_id = self._normalize_url_identity(raw_url) if isinstance(raw_url, str) else None
                if not source_id:
                    source_id = f"{tool_name}:{getattr(event, 'iter', 0)}"
                successful_read_sources.add(source_id)
                if len(successful_read_sources) >= required_reads:
                    return True
                continue

            return True

        if read_like_goal:
            return len(successful_read_sources) >= required_reads

        return False

    def _goal_requires_answer_evidence(self, goal_text: str) -> bool:
        lowered = goal_text.lower()
        cues = (
            "synthesize",
            "recommend",
            "most appropriate",
            "which one",
            "best option",
            "final answer",
            "based on",
        )
        return any(cue in lowered for cue in cues)

    def _action_failed(self, descriptor: str) -> bool:
        lowered = descriptor.lower()
        failure_markers = (
            "[tool_timeout]",
            "[tool_error]",
            "[fetch_error]",
            "[error]",
            "traceback",
            "exception",
            "access denied",
            "warning: target url returned error",
            "source url appears blocked or errored",
            "direct fetch blocked",
            '"status": 0',
        )
        return any(marker in lowered for marker in failure_markers)

    def _required_successful_source_reads(self, goal_text: str, request: PerceptionInput) -> int:
        text = f"{request.query} {goal_text}"
        count = self._source_count_from_text(text)
        return count or 1

    def _source_count_from_text(self, text: str) -> int | None:
        lowered = text.lower()

        top_match = re.search(r"\btop\s+(\d+)\b", lowered)
        if top_match:
            return max(1, min(int(top_match.group(1)), 10))

        numeric_match = re.search(r"\b(\d+)\s+(sources|results|links|articles|pages)\b", lowered)
        if numeric_match:
            return max(1, min(int(numeric_match.group(1)), 10))

        word_to_num = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
        }
        word_match = re.search(r"\b(one|two|three|four|five)\s+(sources|results|links|articles|pages)\b", lowered)
        if word_match:
            return word_to_num[word_match.group(1)]

        return None

    def _normalize_url_identity(self, raw: str) -> str | None:
        parsed = urlparse(raw.strip())
        if parsed.scheme not in {"http", "https"}:
            return None

        host = (parsed.netloc or "").lower().split("@")[-1]
        if host.startswith("www."):
            host = host[4:]
        if not host:
            return None

        path = parsed.path or "/"
        if path != "/" and path.endswith("/"):
            path = path[:-1]

        query = f"?{parsed.query}" if parsed.query else ""
        return f"{host}{path}{query}"

    def _indexed_artifacts(
        self,
        hits: list[Any],
        history: list[Any],
    ) -> tuple[list[dict[str, Any]], dict[int, str]]:
        rows: list[dict[str, Any]] = []
        mapping: dict[int, str] = {}
        seen: set[str] = set()

        ordered = sorted(hits, key=lambda h: h.created_at, reverse=True)
        idx = 0
        for hit in ordered:
            if not hit.artifact_id or hit.artifact_id in seen:
                continue
            seen.add(hit.artifact_id)
            rows.append(
                {
                    "artifact_index": idx,
                    "artifact_id": hit.artifact_id,
                    "descriptor": hit.descriptor,
                    "source": hit.source,
                }
            )
            mapping[idx] = hit.artifact_id
            idx += 1

        # Include recent successful run artifacts so attachment does not depend
        # solely on memory-hit retrieval ranking.
        for event in reversed(history):
            if getattr(event, "kind", None) != "action":
                continue

            artifact_id = getattr(event, "artifact_id", None)
            if not isinstance(artifact_id, str) or not artifact_id.strip() or artifact_id in seen:
                continue

            descriptor = str(getattr(event, "result_descriptor", "")).strip()
            if not descriptor or self._action_failed(descriptor):
                continue

            tool_name = str(getattr(event, "tool", "")).strip()
            seen.add(artifact_id)
            rows.append(
                {
                    "artifact_index": idx,
                    "artifact_id": artifact_id,
                    "descriptor": descriptor[:200],
                    "source": tool_name,
                }
            )
            mapping[idx] = artifact_id
            idx += 1

        return rows, mapping

    def _compact_hit(self, hit: Any) -> dict[str, Any]:
        return {
            "id": hit.id,
            "kind": hit.kind,
            "descriptor": hit.descriptor,
            "artifact_id": hit.artifact_id,
            "goal_id": hit.goal_id,
            "keywords": hit.keywords[:12],
            "created_at": hit.created_at.isoformat(),
        }

    def _default_attach_artifact_id(
        self,
        goal_text: str,
        idx_to_artifact: dict[int, str],
        request: PerceptionInput,
    ) -> str | None:
        if not idx_to_artifact:
            return None
        if not self._goal_prefers_evidence_attachment(goal_text):
            return None

        available = set(idx_to_artifact.values())
        for event in reversed(request.history):
            if getattr(event, "kind", None) != "action":
                continue

            artifact_id = getattr(event, "artifact_id", None)
            if not isinstance(artifact_id, str) or artifact_id not in available:
                continue

            descriptor = str(getattr(event, "result_descriptor", "")).strip()
            if not descriptor or self._action_failed(descriptor):
                continue

            return artifact_id

        first_index = min(idx_to_artifact.keys())
        return idx_to_artifact.get(first_index)

    def _goal_prefers_evidence_attachment(self, goal_text: str) -> bool:
        lowered = goal_text.lower()
        evidence_cues = (
            "extract",
            "identify",
            "analyze",
            "summarize",
            "synthesize",
            "compare",
            "list",
            "contribution",
            "fact",
            "from the source",
            "from source",
            "from provided artifact",
            "from the provided artifact",
            "from provided content",
            "from retrieved",
            "from the retrieved",
        )
        if any(cue in lowered for cue in evidence_cues):
            return True

        acquisition_cues = (
            "fetch",
            "search",
            "retrieve",
            "discover",
            "open url",
        )
        if any(cue in lowered for cue in acquisition_cues):
            return False

        return False