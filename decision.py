from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse
from typing import Any

from config import Settings
from llm_client import GeminiClient
from schemas import DecisionInput, DecisionOutput, ToolCall

DECISION_SYSTEM_PROMPT = """
You are the Decision role.

Return exactly one of:
1) answer: final text for the current goal
2) tool_call: one MCP tool call with arguments

Rules:
- Never return both answer and tool_call.
- Use only tools listed in available_tools.
- Tool names and arguments must comply with each tool's input_schema.
- Do not invent aliases, parameter names, or argument shapes that are not in input_schema.
- Never pass internal artifact handles (values beginning with "art:") to tools.
- Use scenario_meta and scenario_hints as planning hints.
- If scenario_hints indicate durable persistence is preferred, prefer tool-backed persistence before confirmation answers.
- Use memory_hits, history, attached_artifacts, and current_goal_context as evidence.
- For memory-recall goals (recall/remember/stored memory), treat memory_hits/history as primary evidence and prefer answer from internal evidence before external web tools.
- Always inspect evidence_state before choosing answer/tool_call.
- Prefer attached_artifacts as primary evidence for extraction, analysis, and synthesis goals.
- Avoid web_search when attached_artifacts already contain relevant source content, unless the goal explicitly asks for additional/new sources.
- For source-dependent goals, do not answer from prior knowledge; gather run evidence first.
- Do not use local file tools (read_file/list_dir/create_file/update_file/edit_file) unless the goal explicitly requires local filesystem operations.
- Do not refetch the same URL when a previous successful retrieval exists in this run, unless the goal explicitly requests a refresh/retry.
- If evidence_state.has_attached_evidence is true and the goal is extraction/analysis/synthesis, prefer answer over another fetch/search.
- If choosing fetch_url, prefer evidence_state.remaining_candidate_urls and avoid evidence_state.successful_retrieval_url_identities_run unless refresh/retry is explicit.
- If scenario_hints specify blocked search domains, include -site:<domain> exclusions in web_search queries and avoid those domains in URL candidates.
- Avoid web_search/fetch_url for memory-recall goals unless the goal explicitly asks for online/web verification.
- If evidence is sufficient to satisfy the goal, return answer.
- If evidence is insufficient, return one minimal tool_call that makes concrete progress.
- Never claim external side effects (scheduled/saved/written/created/updated) unless supported by history evidence.
- If an action failed recently, choose a different next action instead of repeating the same failed call.
- Keep each step minimal: do exactly one actionable step per iteration.
- Return strict JSON only.
""".strip()

DECISION_ANSWER_ONLY_PROMPT = """
You are the Decision role in answer-only recovery mode.

Return exactly one of:
1) answer: final text for the current goal
2) tool_call: one MCP tool call with arguments

Rules:
- You MUST return answer.
- You MUST NOT return tool_call.
- Use attached_artifacts, history, and memory_hits as evidence.
- Do not claim external side effects unless supported by evidence.
- Keep the answer concise and goal-complete.
- Return strict JSON only.
""".strip()


class DecisionRole:
    def __init__(self, settings: Settings, llm: GeminiClient) -> None:
        self.settings = settings
        self.llm = llm

    async def next_step(self, request: DecisionInput) -> DecisionOutput:
        tool_registry = self._tool_registry(request.mcp_tools)
        payload = self._build_payload(request)

        out = await self._generate(payload)
        violation = self._validate_output(out, request, tool_registry)
        if violation is None:
            repaired = self._repair_without_llm(out, violation, request, tool_registry)
            return repaired or out

        repaired = self._repair_without_llm(out, violation, request, tool_registry)
        if repaired is not None:
            repaired_violation = self._validate_output(repaired, request, tool_registry)
            if repaired_violation is None:
                return repaired

            # Allow one more local repair step when first repair fixes one
            # contract issue but exposes a second one (e.g., search -> fetch pivot).
            second_repair = self._repair_without_llm(
                repaired,
                repaired_violation,
                request,
                tool_registry,
            )
            if second_repair is not None:
                second_violation = self._validate_output(second_repair, request, tool_registry)
                if second_violation is None:
                    return second_repair
                violation = second_violation
            else:
                violation = repaired_violation

        if self._should_attempt_answer_recovery(violation, request):
            recovered = await self._generate_answer_only(payload, violation)
            recovered_violation = self._validate_output(recovered, request, tool_registry)
            if recovered_violation is None:
                return recovered
            violation = recovered_violation

        raise RuntimeError(f"Decision output invalid for goal '{request.goal.text}': {violation}")

    async def _generate(
        self,
        payload: dict[str, Any],
    ) -> DecisionOutput:
        return await self.llm.generate_typed(
            role="decision",
            system_prompt=DECISION_SYSTEM_PROMPT,
            user_prompt=json.dumps(payload, ensure_ascii=False, indent=2),
            response_model=DecisionOutput,
            temperature=self.settings.decision_temperature,
        )

    async def _generate_answer_only(
        self,
        payload: dict[str, Any],
        violation: str | None,
    ) -> DecisionOutput:
        recovery_payload = dict(payload)
        recovery_payload["recovery_context"] = {
            "mode": "answer_only",
            "trigger_violation": violation,
        }
        return await self.llm.generate_typed(
            role="decision",
            system_prompt=DECISION_ANSWER_ONLY_PROMPT,
            user_prompt=json.dumps(recovery_payload, ensure_ascii=False, indent=2),
            response_model=DecisionOutput,
            temperature=self.settings.decision_temperature,
        )

    def _build_payload(self, request: DecisionInput) -> dict[str, Any]:
        run_progress = self._run_progress(request)
        current_goal_context = self._current_goal_context(request)
        goal_intent = self._goal_intent(request.goal.text)
        evidence_state = self._decision_evidence_state(request)
        return {
            "scenario_name": request.scenario_name,
            "scenario_meta": request.scenario_meta.model_dump() if request.scenario_meta else None,
            "scenario_hints": request.scenario_meta.metadata if request.scenario_meta else {},
            "run_progress": run_progress,
            "current_goal_context": current_goal_context,
            "goal_intent": goal_intent,
            "evidence_state": evidence_state,
            "goal": request.goal.model_dump(),
            "memory_hits": [self._compact_hit(hit) for hit in request.hits[:12]],
            "history": [event.model_dump(mode="json") for event in request.history[-12:]],
            "attached_artifacts": [
                {
                    "artifact_id": att.artifact_id,
                    "size_bytes": att.size_bytes,
                    "text": att.text[: self.settings.attach_max_chars],
                }
                for att in request.attached
            ],
            "available_tools": request.mcp_tools,
            "tool_contracts": self._tool_contracts(request.mcp_tools),
            "decision_policy": {
                "one_step_per_iteration": True,
                "schema_first_tool_calling": True,
                "only_answer_when_goal_semantically_complete": True,
                "do_not_repeat_recent_failed_action": True,
                "prefer_evidence_first_reasoning": True,
                "avoid_redundant_successful_url_refetch": True,
            },
        }

    def _tool_contracts(self, mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        contracts: list[dict[str, Any]] = []
        for tool in mcp_tools:
            if not isinstance(tool, dict):
                continue

            name = str(tool.get("name", "")).strip()
            if not name:
                continue

            schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {}
            contracts.append(
                {
                    "name": name,
                    "description": str(tool.get("description") or "")[:500],
                    "required": self._schema_required_fields(schema),
                    "properties": self._schema_property_types(schema),
                    "additional_properties": schema.get("additionalProperties", True),
                }
            )
        return contracts

    def _goal_intent(self, goal_text: str) -> dict[str, Any]:
        lowered = goal_text.lower()
        search_tokens = ("search", "find", "lookup", "look up", "web", "online", "internet")
        return {
            "prefers_url_retrieval": self._goal_prefers_url_retrieval(goal_text),
            "prefers_file_ops": self._goal_prefers_file_path_ops(lowered),
            "prefers_evidence_answer": self._goal_prefers_evidence_answer(lowered),
            "explicit_search_requested": any(token in lowered for token in search_tokens),
        }

    def _decision_evidence_state(self, request: DecisionInput) -> dict[str, Any]:
        successful_run: set[str] = set()
        successful_goal: set[str] = set()
        failed_run: set[str] = set()
        retrieval_events: list[dict[str, Any]] = []

        for event in request.history:
            if getattr(event, "kind", None) != "action":
                continue

            tool = str(getattr(event, "tool", "")).lower().strip()
            if not self._tool_matches_action_kind(tool, "retrieval"):
                continue

            arguments = getattr(event, "arguments", {}) or {}
            if not isinstance(arguments, dict):
                continue

            raw_url = arguments.get("url")
            if not isinstance(raw_url, str) or not raw_url.strip():
                continue

            normalized_url = self._normalize_candidate_url(raw_url.strip(), blocked_domains=self._blocked_domains(request))
            identity = self._url_identity(normalized_url or raw_url.strip())
            if not identity:
                continue

            descriptor = str(getattr(event, "result_descriptor", "")).strip()
            success = bool(descriptor) and descriptor not in {"[]", "{}", "null"} and not self._action_failed(descriptor)

            retrieval_events.append(
                {
                    "iter": getattr(event, "iter", None),
                    "goal_id": getattr(event, "goal_id", None),
                    "tool": tool,
                    "url": normalized_url or raw_url.strip(),
                    "url_identity": identity,
                    "success": success,
                }
            )

            if success:
                successful_run.add(identity)
                if getattr(event, "goal_id", None) == request.goal.id:
                    successful_goal.add(identity)
            else:
                failed_run.add(identity)

        candidate_urls = self._collect_candidate_urls(
            request,
            exclude_urls=set(),
            blocked_domains=self._blocked_domains(request),
        )
        remaining_candidate_urls: list[str] = []
        for url in candidate_urls:
            identity = self._url_identity(url)
            if not identity:
                continue
            if identity in successful_run:
                continue
            remaining_candidate_urls.append(url)

        return {
            "has_attached_evidence": self._has_attached_evidence(request),
            "attached_artifact_count": len(request.attached),
            "attached_artifact_ids": [att.artifact_id for att in request.attached if getattr(att, "artifact_id", None)],
            "successful_retrieval_url_identities_run": sorted(successful_run),
            "successful_retrieval_url_identities_current_goal": sorted(successful_goal),
            "failed_retrieval_url_identities_run": sorted(failed_run),
            "candidate_urls": candidate_urls,
            "remaining_candidate_urls": remaining_candidate_urls,
            "recent_retrieval_events": retrieval_events[-6:],
        }

    def _schema_required_fields(self, schema: dict[str, Any]) -> list[str]:
        required = schema.get("required")
        if isinstance(required, list):
            return [str(item) for item in required if isinstance(item, str)]
        return []

    def _schema_property_types(self, schema: dict[str, Any]) -> dict[str, str]:
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        summary: dict[str, str] = {}
        for key, field_schema in properties.items():
            if not isinstance(field_schema, dict):
                continue
            field_type = field_schema.get("type")
            if isinstance(field_type, list):
                summary[str(key)] = " | ".join(str(item) for item in field_type)
            elif isinstance(field_type, str):
                summary[str(key)] = field_type
            elif isinstance(field_schema.get("anyOf"), list):
                summary[str(key)] = "anyOf"
            elif isinstance(field_schema.get("oneOf"), list):
                summary[str(key)] = "oneOf"
            else:
                summary[str(key)] = "unknown"
        return summary

    def _tool_registry(self, mcp_tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        registry: dict[str, dict[str, Any]] = {}
        for tool in mcp_tools:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name", "")).strip()
            if not name:
                continue
            schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {}
            registry[name] = {
                "schema": schema,
                "description": str(tool.get("description") or ""),
            }
        return registry

    def _validate_output(
        self,
        out: DecisionOutput,
        request: DecisionInput,
        tool_registry: dict[str, dict[str, Any]],
    ) -> str | None:
        if out.tool_call is not None:
            resolved_name = self._resolve_tool_name(out.tool_call.name, tool_registry)
            if resolved_name is None:
                return (
                    f"Tool '{out.tool_call.name}' is unavailable. "
                    f"Choose one of {sorted(tool_registry.keys())}."
                )

            if self._has_artifact_handle(out.tool_call.arguments):
                return "Tool arguments cannot include values that start with 'art:'."

            schema = tool_registry.get(resolved_name, {}).get("schema")
            if isinstance(schema, dict) and schema:
                schema_error = self._validate_against_schema(out.tool_call.arguments, schema, path="arguments")
                if schema_error is not None:
                    return f"Tool arguments do not match input_schema for '{resolved_name}': {schema_error}"

            if (
                self._is_memory_recall_context(request)
                and self._has_memory_hit_evidence(request)
                and not self._goal_explicit_external_search(request.goal.text)
                and (
                    "search" in resolved_name.lower()
                    or self._tool_has_field(schema if isinstance(schema, dict) else {}, "url")
                )
            ):
                return (
                    "Memory recall goal has internal evidence; "
                    "answer from memory_hits/history instead of external web tools."
                )

            normalized_args = dict(out.tool_call.arguments or {})
            call_sig = self._tool_call_signature(resolved_name, normalized_args)
            if self._is_repeated_tool_call(request, call_sig):
                return "Repeated identical action for this goal without new context; choose a different next step."

            raw_url = normalized_args.get("url") if isinstance(normalized_args, dict) else None
            if isinstance(raw_url, str) and raw_url.strip():
                normalized_url = self._normalize_candidate_url(raw_url, blocked_domains=self._blocked_domains(request))
                url_identity = self._url_identity(normalized_url or raw_url.strip())
                if (
                    url_identity
                    and self._was_url_retrieved_successfully(request, url_identity)
                    and not self._goal_requests_refetch(request.goal.text)
                ):
                    return (
                        "URL already retrieved successfully in this run; "
                        "use existing evidence or choose a different URL."
                    )

            if (
                isinstance(schema, dict)
                and self._tool_has_field(schema, "query")
                and not self._tool_has_field(schema, "url")
                and self._goal_prefers_url_retrieval(request.goal.text)
                and bool(
                    self._collect_candidate_urls(
                        request,
                        exclude_urls=self._used_urls(request, goal_only=True),
                        blocked_domains=self._blocked_domains(request),
                        goal_scoped=True,
                    )
                )
            ):
                return (
                    "Goal appears to require reading source content and candidate URLs already exist; "
                    "choose a URL retrieval tool instead of repeating search."
                )

            if (
                self._goal_prefers_evidence_answer(request.goal.text)
                and self._has_attached_evidence(request)
                and self._has_successful_retrieval_in_run(request)
                and not self._goal_explicit_external_search(request.goal.text)
            ):
                return (
                    "Goal already has attached evidence and prior retrieval context; "
                    "answer directly instead of issuing another tool call."
                )
            return None

        answer = (out.answer or "").strip()
        if not answer:
            return "Answer cannot be empty."
        if self._claims_external_side_effect(answer) and not self._goal_has_successful_action(request):
            return "Answer claims side effects without supporting action evidence."
        if self._answer_requires_grounded_evidence(request) and not self._answer_supported_by_evidence(request):
            return "Answer is unsupported by run evidence for this goal; gather evidence with tools first."
        if self._is_low_value_answer(answer):
            return "Answer is too short or meta; provide a substantive goal-completing answer."
        return None

    def _repair_without_llm(
        self,
        out: DecisionOutput,
        violation: str | None,
        request: DecisionInput,
        tool_registry: dict[str, dict[str, Any]],
    ) -> DecisionOutput | None:
        # Contract repair remains local so we avoid extra LLM cooldown loops.
        if out.tool_call is None:
            lowered_violation = (violation or "").lower()
            if "side effects" in lowered_violation or "unsupported by run evidence" in lowered_violation:
                blocked: set[str] | None = None
                if (
                    "unsupported by run evidence" in lowered_violation
                    and self._goal_prefers_url_retrieval(request.goal.text)
                    and not self._goal_requests_refetch(request.goal.text)
                ):
                    blocked = self._history_retrieval_signatures(request, goal_only=False)

                inferred = self._infer_tool_call_from_goal(
                    request,
                    tool_registry,
                    blocked_signatures=blocked,
                )
                if inferred is not None:
                    return DecisionOutput(tool_call=inferred)
            return None

        resolved_name = self._resolve_tool_name(out.tool_call.name, tool_registry)
        if resolved_name is None:
            return None

        changed = resolved_name != out.tool_call.name
        arguments = dict(out.tool_call.arguments or {})

        if self._has_artifact_handle(arguments):
            arguments = {
                key: value
                for key, value in arguments.items()
                if not (isinstance(value, str) and value.startswith("art:"))
            }
            changed = True

        schema = tool_registry.get(resolved_name, {}).get("schema")
        schema_error_after_coerce: str | None = None
        if isinstance(schema, dict) and schema:
            coerced = self._coerce_to_schema(arguments, schema)
            if isinstance(coerced, dict):
                if coerced != arguments:
                    changed = True
                arguments = coerced
            schema_error_after_coerce = self._validate_against_schema(arguments, schema, path="arguments")

        lowered_violation = (violation or "").lower()
        schema_violation = schema_error_after_coerce is not None or any(
            token in lowered_violation
            for token in (
                "input_schema",
                "missing required fields",
                "unexpected fields",
                "expected type",
                "must satisfy",
                "anyof",
                "oneof",
            )
        )
        if (
            (
                schema_violation
                or "repeated identical action" in lowered_violation
                or "candidate urls already exist" in lowered_violation
                or "reading source content" in lowered_violation
                or "already retrieved successfully" in lowered_violation
            )
        ):
            blocked = self._history_blocked_signatures(request, goal_only=True)
            if "already retrieved successfully" in lowered_violation:
                blocked.update(self._history_retrieval_signatures(request, goal_only=False))
            blocked.add(self._tool_call_signature(resolved_name, arguments))
            inferred = self._infer_tool_call_from_goal(
                request,
                tool_registry,
                blocked_signatures=blocked,
            )
            if inferred is not None:
                return DecisionOutput(tool_call=inferred)

        if not changed:
            return None

        return DecisionOutput(tool_call=ToolCall(name=resolved_name, arguments=arguments))

    def _infer_tool_call_from_goal(
        self,
        request: DecisionInput,
        tool_registry: dict[str, dict[str, Any]],
        blocked_signatures: set[str] | None = None,
    ) -> ToolCall | None:
        if not tool_registry:
            return None

        goal_text = request.goal.text.strip()
        if not goal_text:
            return None

        blocked = set(blocked_signatures or set())
        used_urls = self._used_urls(request, goal_only=True)
        if self._goal_prefers_url_retrieval(goal_text) and not self._goal_requests_refetch(goal_text):
            used_urls.update(self._used_urls(request, goal_only=False))

        ranked: list[tuple[int, str, dict[str, Any]]] = []
        for tool_name, meta in tool_registry.items():
            schema = meta.get("schema") if isinstance(meta.get("schema"), dict) else {}
            score = self._score_tool_for_goal(goal_text, tool_name, meta, schema, request)
            if score > 0:
                ranked.append((score, tool_name, schema))

        ranked.sort(key=lambda item: item[0], reverse=True)
        for _, tool_name, schema in ranked:
            arguments = self._build_required_arguments(
                tool_name,
                schema,
                request,
                blocked_urls=used_urls,
            )
            if arguments is None:
                continue
            if self._has_artifact_handle(arguments):
                continue

            call_sig = self._tool_call_signature(tool_name, arguments)
            if call_sig in blocked:
                continue

            if isinstance(schema, dict) and schema:
                coerced = self._coerce_to_schema(arguments, schema)
                if not isinstance(coerced, dict):
                    continue
                err = self._validate_against_schema(coerced, schema, path="arguments")
                if err is not None:
                    continue
                arguments = coerced

            return ToolCall(name=tool_name, arguments=arguments)

        return None

    def _score_tool_for_goal(
        self,
        goal_text: str,
        tool_name: str,
        meta: dict[str, Any],
        schema: dict[str, Any],
        request: DecisionInput,
    ) -> int:
        lowered_goal = goal_text.lower()
        goal_tokens = set(self._tokenize(lowered_goal))
        name_tokens = set(self._tokenize(tool_name.replace("_", " ")))
        desc_tokens = set(self._tokenize(str(meta.get("description") or "")))

        score = len(goal_tokens.intersection(name_tokens.union(desc_tokens)))
        required = {item.lower() for item in self._schema_required_fields(schema)}
        candidate_urls_exist = bool(
            self._collect_candidate_urls(
                request,
                exclude_urls=self._used_urls(request, goal_only=True),
                blocked_domains=self._blocked_domains(request),
                goal_scoped=True,
            )
        )

        if any(token in lowered_goal for token in ("create", "write", "save", "reminder", "note")):
            if {"path", "content"}.issubset(required):
                score += 4

        if any(token in lowered_goal for token in ("read", "access", "content", "source", "result", "fetch", "retrieve", "retrieved")):
            if "url" in required:
                score += 4
            if "query" in required and "url" not in required:
                score -= 2
                if not candidate_urls_exist:
                    score += 3

        if any(token in lowered_goal for token in ("read", "open", "view")):
            if "path" in required and "content" not in required:
                if self._goal_prefers_file_path_ops(lowered_goal):
                    score += 2
                else:
                    score -= 3

        if any(token in lowered_goal for token in ("list", "directory", "folder")):
            if "path" in required:
                if self._goal_prefers_file_path_ops(lowered_goal):
                    score += 2
                else:
                    score -= 2

        if any(token in lowered_goal for token in ("search", "find", "lookup", "look up")):
            if "query" in required:
                score += 2

        # Weather retrieval goals should usually query forecast providers instead
        # of reusing previously discovered non-weather content URLs.
        if any(token in lowered_goal for token in ("weather", "forecast", "temperature", "rain", "wind", "humidity")):
            if "query" in required and "url" not in required:
                score += 5
            if "url" in required:
                score -= 4

        if "fetch" in lowered_goal and "url" in required:
            score += 2

        if candidate_urls_exist and "url" in required:
            score += 2

        if self._is_memory_recall_context(request) and not self._goal_explicit_external_search(lowered_goal):
            if "url" in required:
                score -= 6
            if "query" in required and "url" not in required:
                score -= 5
            if "path" in required and "content" not in required:
                score += 3
                if self._has_memory_hit_evidence(request):
                    score += 1

        metadata = request.scenario_meta.metadata if request.scenario_meta else {}
        preferences = metadata.get("preferences") if isinstance(metadata, dict) else {}
        if isinstance(preferences, dict):
            persistence = str(preferences.get("persistence", "")).lower()
            if persistence in {"durable_external_artifact", "durable"} and {"path", "content"}.issubset(required):
                score += 2
            if preferences.get("location_hint") and "path" in required:
                score += 1

        return score

    def _build_required_arguments(
        self,
        tool_name: str,
        schema: dict[str, Any],
        request: DecisionInput,
        blocked_urls: set[str] | None = None,
    ) -> dict[str, Any] | None:
        required = self._schema_required_fields(schema)
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}

        args: dict[str, Any] = {}
        for key in required:
            field_schema = properties.get(key) if isinstance(properties.get(key), dict) else {}
            value = self._infer_required_argument(
                tool_name,
                key,
                field_schema,
                request,
                blocked_urls=blocked_urls,
            )
            if value is None:
                return None
            args[key] = value

        return args

    def _infer_required_argument(
        self,
        tool_name: str,
        key: str,
        field_schema: dict[str, Any],
        request: DecisionInput,
        blocked_urls: set[str] | None = None,
    ) -> Any | None:
        lowered_key = key.lower()
        goal_text = request.goal.text.strip()

        if "default" in field_schema:
            return field_schema.get("default")

        if "path" in lowered_key:
            if not self._goal_prefers_file_path_ops(goal_text.lower()):
                return None
            return self._path_hint_for_goal(request)

        if any(token in lowered_key for token in ("content", "text", "body", "message")):
            return self._content_hint_for_goal(goal_text)

        if "query" in lowered_key:
            return self._query_hint_for_goal(request, goal_text)

        if "url" in lowered_key:
            return self._extract_url_from_context(request, exclude_urls=blocked_urls)

        if "timeout" in lowered_key:
            return 20

        if "max_results" in lowered_key:
            return 5

        if "replace_all" in lowered_key:
            return False

        expected_type = field_schema.get("type")
        if expected_type == "string":
            return f"{tool_name}:{goal_text}"
        if expected_type == "integer":
            return 1
        if expected_type == "number":
            return 1.0
        if expected_type == "boolean":
            return False
        if expected_type == "array":
            return []
        if expected_type == "object":
            return {}

        return None

    def _path_hint_for_goal(self, request: DecisionInput) -> str:
        metadata = request.scenario_meta.metadata if request.scenario_meta else {}
        preferences = metadata.get("preferences") if isinstance(metadata, dict) else {}
        folder = "notes"
        if isinstance(preferences, dict):
            location_hint = preferences.get("location_hint")
            if isinstance(location_hint, str) and location_hint.strip():
                folder = location_hint.strip().strip("/\\")

        suffix = self._date_suffix(request.goal.text) or self._slugify(request.goal.text)
        if not suffix:
            suffix = "item"
        filename = f"reminder_{suffix}.txt"

        if folder in {"", ".", "./"}:
            return filename
        return f"{folder}/{filename}"

    def _content_hint_for_goal(self, goal_text: str) -> str:
        text = goal_text.strip()
        if not text:
            return "Reminder"
        return f"Reminder: {text}"

    def _query_hint_for_goal(self, request: DecisionInput, goal_text: str) -> str:
        blocked_domains = self._blocked_domains(request)

        for event in reversed(request.history):
            if getattr(event, "kind", None) != "action":
                continue
            tool = str(getattr(event, "tool", "")).lower().strip()
            if "search" not in tool:
                continue

            arguments = getattr(event, "arguments", {}) or {}
            if not isinstance(arguments, dict):
                continue

            raw_query = arguments.get("query")
            if isinstance(raw_query, str) and raw_query.strip():
                return self._apply_search_domain_exclusions(raw_query.strip(), blocked_domains)

        for hit in request.hits:
            kind = str(getattr(hit, "kind", "")).lower().strip()
            if kind not in {"scratchpad", "fact", "preference"}:
                continue

            value = hit.value if isinstance(hit.value, dict) else {}
            candidates = [
                value.get("text"),
                value.get("query"),
                getattr(hit, "descriptor", ""),
            ]
            for candidate in candidates:
                if not isinstance(candidate, str):
                    continue
                text = candidate.strip()
                if not text:
                    continue
                if text.startswith("{") or text.startswith("["):
                    continue
                return self._apply_search_domain_exclusions(text[:220], blocked_domains)

        return self._apply_search_domain_exclusions(goal_text, blocked_domains)

    def _extract_url_from_context(
        self,
        request: DecisionInput,
        exclude_urls: set[str] | None = None,
    ) -> str | None:
        blocked = exclude_urls or set()
        blocked_domains = self._blocked_domains(request)

        goal_urls = self._extract_urls(request.goal.text)
        if goal_urls:
            for url in goal_urls:
                normalized = self._normalize_candidate_url(url, blocked_domains=blocked_domains)
                identity = self._url_identity(normalized) if normalized else ""
                if normalized and identity and identity not in blocked:
                    return normalized

        for url in self._scenario_candidate_urls(request):
            normalized = self._normalize_candidate_url(url, blocked_domains=blocked_domains)
            identity = self._url_identity(normalized) if normalized else ""
            if normalized and identity and identity not in blocked:
                return normalized

        candidate_urls = self._collect_candidate_urls(
            request,
            exclude_urls=blocked,
            blocked_domains=blocked_domains,
            goal_scoped=True,
        )
        if candidate_urls:
            return candidate_urls[0]

        # Fallback to broader run-level candidates when goal-scoped context has none.
        candidate_urls = self._collect_candidate_urls(
            request,
            exclude_urls=blocked,
            blocked_domains=blocked_domains,
            goal_scoped=False,
        )
        if candidate_urls:
            return candidate_urls[0]

        return None

    def _collect_candidate_urls(
        self,
        request: DecisionInput,
        exclude_urls: set[str] | None = None,
        blocked_domains: set[str] | None = None,
        goal_scoped: bool = False,
    ) -> list[str]:
        blocked = exclude_urls or set()
        blocked_identities: set[str] = set()
        for item in blocked:
            if not item:
                continue
            blocked_identities.add(item)
            identity = self._url_identity(item)
            if identity:
                blocked_identities.add(identity)
        seen: set[str] = set()
        candidates: list[str] = []

        def _add(url: str) -> None:
            normalized = self._normalize_candidate_url(url, blocked_domains=blocked_domains)
            if not normalized:
                return
            identity = self._url_identity(normalized)
            if not identity:
                return
            if identity in blocked_identities or identity in seen:
                return
            seen.add(identity)
            candidates.append(normalized)

        for url in self._scenario_candidate_urls(request):
            _add(url)

        for hit in request.hits:
            if goal_scoped and getattr(hit, "goal_id", None) != request.goal.id:
                continue
            for url in self._search_result_urls_from_hit(hit):
                _add(url)

        for event in request.history:
            if getattr(event, "kind", None) != "action":
                continue
            if goal_scoped and getattr(event, "goal_id", None) != request.goal.id:
                continue
            tool = str(getattr(event, "tool", "")).lower().strip()
            if tool != "web_search":
                continue

            descriptor = str(getattr(event, "result_descriptor", ""))
            for url in self._search_result_urls_from_text(descriptor):
                _add(url)

        return candidates

    def _scenario_candidate_urls(self, request: DecisionInput) -> list[str]:
        metadata = request.scenario_meta.metadata if request.scenario_meta else {}
        if not isinstance(metadata, dict):
            return []

        context = metadata.get("context") if isinstance(metadata.get("context"), dict) else {}
        urls: list[str] = []

        primary = context.get("primary_source_url")
        if isinstance(primary, str) and primary.strip():
            urls.append(primary.strip())

        source_urls = context.get("source_urls")
        if isinstance(source_urls, list):
            for item in source_urls:
                if isinstance(item, str) and item.strip():
                    urls.append(item.strip())

        return urls

    def _used_urls(self, request: DecisionInput, goal_only: bool = False) -> set[str]:
        used: set[str] = set()
        for event in request.history:
            if getattr(event, "kind", None) != "action":
                continue
            if goal_only and getattr(event, "goal_id", None) != request.goal.id:
                continue
            arguments = getattr(event, "arguments", {}) or {}
            if not isinstance(arguments, dict):
                continue
            raw = arguments.get("url")
            if isinstance(raw, str) and raw.strip():
                normalized = self._normalize_candidate_url(raw.strip())
                identity = self._url_identity(normalized or raw.strip())
                if identity:
                    used.add(identity)
        return used

    def _tool_call_signature(self, name: str, arguments: dict[str, Any]) -> str:
        normalized_args = dict(arguments or {})
        raw_url = normalized_args.get("url")
        if isinstance(raw_url, str) and raw_url.strip():
            normalized_url = self._normalize_candidate_url(raw_url)
            if normalized_url:
                normalized_args["url"] = self._url_identity(normalized_url) or normalized_url
        return f"{name}:{json.dumps(normalized_args, sort_keys=True, ensure_ascii=False)}"

    def _search_result_urls_from_hit(self, hit: Any) -> list[str]:
        value = hit.value if isinstance(hit.value, dict) else {}
        tool_name = str(value.get("tool_name", "")).lower().strip()
        if tool_name != "web_search":
            return []

        result_text = value.get("result_text")
        if isinstance(result_text, str) and result_text.strip():
            urls = self._search_result_urls_from_text(result_text)
            if urls:
                return urls

        descriptor = str(getattr(hit, "descriptor", ""))
        return self._search_result_urls_from_text(descriptor)

    def _search_result_urls_from_text(self, text: str) -> list[str]:
        cleaned = text.strip()
        if not cleaned:
            return []

        urls: list[str] = []
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            payload = None

        if payload is not None:
            urls.extend(self._urls_from_search_payload(payload))

        if not urls:
            urls.extend(self._extract_urls(cleaned))

        return urls

    def _urls_from_search_payload(self, payload: Any) -> list[str]:
        urls: list[str] = []

        if isinstance(payload, list):
            for row in payload:
                if not isinstance(row, dict):
                    continue
                raw = row.get("url")
                if isinstance(raw, str) and raw.strip():
                    urls.append(raw.strip())
            return urls

        if isinstance(payload, dict):
            for key in ("results", "items", "data"):
                child = payload.get(key)
                if isinstance(child, list):
                    urls.extend(self._urls_from_search_payload(child))

            raw = payload.get("url")
            if isinstance(raw, str) and raw.strip():
                urls.append(raw.strip())

        return urls

    def _is_repeated_tool_call(self, request: DecisionInput, signature: str) -> bool:
        for event in reversed(request.history):
            if getattr(event, "goal_id", None) != request.goal.id:
                continue
            if getattr(event, "kind", None) != "action":
                continue

            args = getattr(event, "arguments", {}) if isinstance(getattr(event, "arguments", {}), dict) else {}
            prev_signature = self._tool_call_signature(str(getattr(event, "tool", "")), args)
            if prev_signature == signature:
                return True
        return False

    def _history_blocked_signatures(self, request: DecisionInput, goal_only: bool) -> set[str]:
        blocked: set[str] = set()
        for event in request.history:
            if getattr(event, "kind", None) != "action":
                continue
            if goal_only and getattr(event, "goal_id", None) != request.goal.id:
                continue

            args = getattr(event, "arguments", {}) if isinstance(getattr(event, "arguments", {}), dict) else {}
            blocked.add(self._tool_call_signature(str(getattr(event, "tool", "")), args))
        return blocked

    def _history_retrieval_signatures(self, request: DecisionInput, goal_only: bool) -> set[str]:
        blocked: set[str] = set()
        for event in request.history:
            if getattr(event, "kind", None) != "action":
                continue
            if goal_only and getattr(event, "goal_id", None) != request.goal.id:
                continue

            tool = str(getattr(event, "tool", "")).lower().strip()
            if not self._tool_matches_action_kind(tool, "retrieval"):
                continue

            args = getattr(event, "arguments", {}) if isinstance(getattr(event, "arguments", {}), dict) else {}
            blocked.add(self._tool_call_signature(str(getattr(event, "tool", "")), args))
        return blocked

    def _goal_prefers_url_retrieval(self, goal_text: str) -> bool:
        if self._goal_mentions_memory_recall(goal_text):
            return False
        lowered = goal_text.lower()
        cues = ("read", "access", "content", "source", "result", "fetch", "open", "retrieve", "retrieved")
        return any(token in lowered for token in cues)

    def _goal_prefers_file_path_ops(self, goal_text: str) -> bool:
        lowered = goal_text.lower()

        file_cues = (
            "file",
            "folder",
            "directory",
            "path",
            "local",
            "disk",
            "sandbox",
            "reminder",
            "calendar reminder",
            "stored memory",
            "memory",
            "recall",
            "remember",
            "create file",
            "read file",
            "update file",
            "list dir",
            "list directory",
            "write note",
            "save note",
            "save reminder",
        )
        return any(cue in lowered for cue in file_cues)

    def _goal_prefers_evidence_answer(self, goal_text: str) -> bool:
        lowered = goal_text.lower()
        cues = (
            "extract",
            "identify",
            "analyze",
            "summarize",
            "synthesize",
            "list",
            "contribution",
            "based on the retrieved",
            "based on retrieved",
            "from the source",
            "from source",
            "from provided content",
        )
        return any(cue in lowered for cue in cues)

    def _goal_mentions_memory_recall(self, goal_text: str) -> bool:
        lowered = goal_text.lower()
        cues = (
            "memory",
            "remember",
            "recall",
            "stored",
            "prior run",
            "previous run",
        )
        return any(cue in lowered for cue in cues)

    def _is_memory_recall_context(self, request: DecisionInput) -> bool:
        query_type = (request.scenario_meta.query_type if request.scenario_meta else "") or ""
        lowered_type = query_type.lower()
        if "memory" in lowered_type or "recall" in lowered_type:
            return True
        return self._goal_mentions_memory_recall(request.goal.text)

    def _goal_explicit_external_search(self, goal_text: str) -> bool:
        lowered = goal_text.lower()
        cues = (
            "search",
            "look up",
            "lookup",
            "web",
            "online",
            "internet",
            "wikipedia",
            "verify online",
        )
        return any(cue in lowered for cue in cues)

    def _has_memory_hit_evidence(self, request: DecisionInput) -> bool:
        goal_tokens = set(self._tokenize(request.goal.text))
        for hit in request.hits:
            descriptor = str(getattr(hit, "descriptor", ""))
            value = getattr(hit, "value", {})
            value_text = json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else str(value)
            keywords = getattr(hit, "keywords", [])
            keyword_text = " ".join(str(item) for item in keywords if isinstance(item, str))
            combined = f"{descriptor} {value_text} {keyword_text}".strip()
            if not combined:
                continue

            if not goal_tokens:
                return True

            hit_tokens = set(self._tokenize(combined))
            if goal_tokens.intersection(hit_tokens):
                return True

        return False

    def _goal_requests_refetch(self, goal_text: str) -> bool:
        lowered = goal_text.lower()
        refetch_cues = (
            "refetch",
            "re-fetch",
            "fetch again",
            "retrieve again",
            "refresh",
            "latest",
            "updated",
            "retry",
            "re-read",
        )
        return any(cue in lowered for cue in refetch_cues)

    def _was_url_retrieved_successfully(self, request: DecisionInput, url_identity: str) -> bool:
        for event in request.history:
            if getattr(event, "kind", None) != "action":
                continue

            tool = str(getattr(event, "tool", "")).lower().strip()
            if not self._tool_matches_action_kind(tool, "retrieval"):
                continue

            arguments = getattr(event, "arguments", {}) or {}
            if not isinstance(arguments, dict):
                continue

            raw_url = arguments.get("url")
            if not isinstance(raw_url, str) or not raw_url.strip():
                continue

            normalized = self._normalize_candidate_url(raw_url)
            identity = self._url_identity(normalized or raw_url.strip())
            if identity != url_identity:
                continue

            descriptor = str(getattr(event, "result_descriptor", "")).strip()
            if not descriptor or descriptor in {"[]", "{}", "null"}:
                continue
            if self._action_failed(descriptor):
                continue
            return True

        return False

    def _tool_has_field(self, schema: dict[str, Any], field: str) -> bool:
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if field in properties:
            return True
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        return field in {str(item) for item in required if isinstance(item, str)}

    def _extract_urls(self, text: str) -> list[str]:
        return re.findall(r"https?://[^\s\"'<>]+", text)

    def _normalize_candidate_url(self, raw: str, blocked_domains: set[str] | None = None) -> str:
        cleaned = raw.strip().strip('"\'')

        # Remove common spillover from serialized descriptors like "URL Source: ...\\n\\nWarning: ..."
        for breaker in ("\\n", "\\r", "\n", "\r", " ", "\t"):
            if breaker in cleaned:
                cleaned = cleaned.split(breaker, 1)[0].strip()

        for stopper in ('"', "'", "}", "]", ")", ",", ";"):
            if stopper in cleaned:
                cleaned = cleaned.split(stopper, 1)[0].strip()

        cleaned = cleaned.rstrip("\\")
        cleaned = cleaned.strip('.,);]')
        if not cleaned:
            return ""

        lowered = cleaned.lower()
        if any(token in lowered for token in ("warning:", "url source:", "%0a", "%0d")):
            return ""

        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"}:
            return ""
        host = (parsed.netloc or "").lower().split("@")[-1]
        if host.startswith("www."):
            host = host[4:]
        if not host:
            return ""

        for domain in blocked_domains or set():
            if host == domain or host.endswith(f".{domain}"):
                return ""

        if any(ch in host for ch in (" ", "\\", "\n", "\r")):
            return ""

        if "\\" in cleaned:
            return ""

        normalized = cleaned.split("#", 1)[0]
        if parsed.path and parsed.path != "/" and normalized.endswith("/"):
            normalized = normalized[:-1]
        if not normalized:
            return ""

        return normalized

    def _url_identity(self, raw: str) -> str:
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"}:
            return ""

        host = (parsed.netloc or "").lower().split("@")[-1]
        if host.startswith("www."):
            host = host[4:]
        if not host:
            return ""

        path = parsed.path or "/"
        if path != "/" and path.endswith("/"):
            path = path[:-1]

        query = f"?{parsed.query}" if parsed.query else ""
        return f"{host}{path}{query}"

    def _blocked_domains(self, request: DecisionInput) -> set[str]:
        domains: set[str] = set()

        env_raw = os.environ.get("SEARCH_BLOCKED_DOMAINS", "medium.com")
        domains.update(self._extract_domains_from_value(env_raw))
        domains.update(self._scenario_blocked_domains(request))

        return domains

    def _scenario_blocked_domains(self, request: DecisionInput) -> set[str]:
        metadata = request.scenario_meta.metadata if request.scenario_meta else {}
        if not isinstance(metadata, dict):
            return set()

        context = metadata.get("context") if isinstance(metadata.get("context"), dict) else {}
        preferences = metadata.get("preferences") if isinstance(metadata.get("preferences"), dict) else {}
        weather_search = context.get("weather_search") if isinstance(context.get("weather_search"), dict) else {}

        domains: set[str] = set()
        domains.update(self._extract_domains_from_value(metadata.get("search_blocked_domains")))
        domains.update(self._extract_domains_from_value(context.get("search_blocked_domains")))
        domains.update(self._extract_domains_from_value(preferences.get("search_blocked_domains")))
        domains.update(self._extract_domains_from_value(preferences.get("weather_search_blocked_domains")))
        domains.update(self._extract_domains_from_value(weather_search.get("blocked_domains")))
        return domains

    def _extract_domains_from_value(self, value: Any) -> set[str]:
        domains: set[str] = set()

        def _add_token(raw_token: Any) -> None:
            if not isinstance(raw_token, str):
                return

            token = raw_token.strip().lower().lstrip(".")
            if not token:
                return

            if "://" in token:
                parsed = urlparse(token)
                token = (parsed.netloc or "").lower()
            else:
                token = token.split("/", 1)[0].lower()

            token = token.split("@")[-1]
            if token.startswith("www."):
                token = token[4:]

            if token:
                domains.add(token)

        if value is None:
            return domains

        if isinstance(value, str):
            for part in value.split(","):
                _add_token(part)
            return domains

        if isinstance(value, (list, tuple, set)):
            for item in value:
                _add_token(item)
            return domains

        return domains

    def _apply_search_domain_exclusions(self, query: str, blocked_domains: set[str]) -> str:
        text = query.strip()
        if not text or not blocked_domains:
            return text

        lowered = text.lower()
        for domain in sorted(blocked_domains):
            token = f"-site:{domain}"
            if token in lowered:
                continue
            text = f"{text} {token}"
            lowered = text.lower()

        return text

    def _date_suffix(self, text: str) -> str:
        lowered = text.lower()
        iso = re.search(r"\b\d{4}-\d{2}-\d{2}\b", lowered)
        if iso:
            return iso.group(0)

        human = re.search(r"\b([a-z]+)\s+(\d{1,2}),?\s+(\d{4})\b", lowered)
        if human:
            month = human.group(1)
            day = int(human.group(2))
            year = human.group(3)
            month_num = {
                "january": "01",
                "february": "02",
                "march": "03",
                "april": "04",
                "may": "05",
                "june": "06",
                "july": "07",
                "august": "08",
                "september": "09",
                "october": "10",
                "november": "11",
                "december": "12",
            }.get(month)
            if month_num:
                return f"{year}-{month_num}-{day:02d}"

        return ""

    def _slugify(self, text: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
        return slug[:40]

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9]{3,}", text.lower())

    def _resolve_tool_name(
        self,
        tool_name: str,
        tool_registry: dict[str, dict[str, Any]],
    ) -> str | None:
        if tool_name in tool_registry:
            return tool_name

        lowered = tool_name.lower().strip()
        lower_matches = [name for name in tool_registry if name.lower() == lowered]
        if len(lower_matches) == 1:
            return lower_matches[0]

        normalized = self._normalize_tool_token(tool_name)
        normalized_matches = [
            name for name in tool_registry if self._normalize_tool_token(name) == normalized
        ]
        if len(normalized_matches) == 1:
            return normalized_matches[0]

        return None

    def _normalize_tool_token(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]", "", text.lower())

    def _coerce_to_schema(self, value: Any, schema: dict[str, Any]) -> Any:
        if not isinstance(schema, dict) or not schema:
            return value

        for key in ("anyOf", "oneOf"):
            branches = schema.get(key)
            if isinstance(branches, list):
                for branch in branches:
                    if not isinstance(branch, dict):
                        continue
                    candidate = self._coerce_to_schema(value, branch)
                    if self._validate_against_schema(candidate, branch, path="arguments") is None:
                        return candidate

        expected_type = schema.get("type")
        if isinstance(expected_type, list):
            for candidate_type in expected_type:
                candidate_schema = dict(schema)
                candidate_schema["type"] = candidate_type
                candidate = self._coerce_to_schema(value, candidate_schema)
                if self._validate_against_schema(candidate, candidate_schema, path="arguments") is None:
                    return candidate

        is_object_schema = expected_type == "object" or any(
            key in schema for key in ("properties", "required", "additionalProperties")
        )
        if is_object_schema:
            working = value
            if isinstance(working, str):
                try:
                    parsed = json.loads(working)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    working = parsed

            if not isinstance(working, dict):
                return value

            properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            additional_properties = schema.get("additionalProperties", True)
            coerced_object: dict[str, Any] = {}

            for key, raw in working.items():
                field_schema = properties.get(key)
                if isinstance(field_schema, dict):
                    coerced_object[key] = self._coerce_to_schema(raw, field_schema)
                    continue

                if additional_properties is False:
                    continue

                if isinstance(additional_properties, dict):
                    coerced_object[key] = self._coerce_to_schema(raw, additional_properties)
                    continue

                coerced_object[key] = raw

            required = schema.get("required") if isinstance(schema.get("required"), list) else []
            for key in required:
                if not isinstance(key, str):
                    continue
                if key in coerced_object:
                    continue
                field_schema = properties.get(key)
                if isinstance(field_schema, dict) and "default" in field_schema:
                    coerced_object[key] = field_schema["default"]

            return coerced_object

        is_array_schema = expected_type == "array" or "items" in schema
        if is_array_schema:
            working = value
            if isinstance(working, tuple):
                working = list(working)
            if not isinstance(working, list):
                working = [working]

            item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else None
            if item_schema is None:
                return working
            return [self._coerce_to_schema(item, item_schema) for item in working]

        if expected_type == "string":
            if isinstance(value, str):
                return value
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            if value is None:
                return value
            return str(value)

        if expected_type == "integer":
            if isinstance(value, bool):
                return value
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)
            if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
                return int(value.strip())
            return value

        if expected_type == "number":
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return value
            if isinstance(value, str):
                text = value.strip()
                if re.fullmatch(r"[+-]?\d+(\.\d+)?", text):
                    return float(text)
            return value

        if expected_type == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, int) and value in (0, 1):
                return bool(value)
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "yes", "1"}:
                    return True
                if lowered in {"false", "no", "0"}:
                    return False
            return value

        if expected_type == "null":
            if isinstance(value, str) and value.strip().lower() == "null":
                return None
            return value

        return value

    def _validate_against_schema(self, value: Any, schema: dict[str, Any], path: str) -> str | None:
        if not isinstance(schema, dict) or not schema:
            return None

        any_of = schema.get("anyOf")
        if isinstance(any_of, list) and any_of:
            if any(
                self._validate_against_schema(value, branch, path) is None
                for branch in any_of
                if isinstance(branch, dict)
            ):
                return None
            return f"{path} does not satisfy anyOf constraints"

        one_of = schema.get("oneOf")
        if isinstance(one_of, list) and one_of:
            matches = sum(
                1
                for branch in one_of
                if isinstance(branch, dict) and self._validate_against_schema(value, branch, path) is None
            )
            if matches == 1:
                return None
            return f"{path} must satisfy exactly one oneOf branch (matched {matches})"

        all_of = schema.get("allOf")
        if isinstance(all_of, list):
            for branch in all_of:
                if not isinstance(branch, dict):
                    continue
                err = self._validate_against_schema(value, branch, path)
                if err is not None:
                    return err

        expected_type = schema.get("type")
        if isinstance(expected_type, str):
            if not self._matches_type(value, expected_type):
                return (
                    f"{path} expected type {expected_type}, got {self._type_name(value)}"
                )
        elif isinstance(expected_type, list):
            if not any(self._matches_type(value, item) for item in expected_type if isinstance(item, str)):
                return (
                    f"{path} expected one of {expected_type}, got {self._type_name(value)}"
                )

        if "const" in schema and value != schema.get("const"):
            return f"{path} must equal {schema.get('const')!r}"

        if isinstance(schema.get("enum"), list) and value not in schema.get("enum"):
            return f"{path} must be one of {schema.get('enum')}"

        is_object_schema = expected_type == "object" or any(
            key in schema for key in ("properties", "required", "additionalProperties")
        )
        if is_object_schema:
            if not isinstance(value, dict):
                return f"{path} expected object, got {self._type_name(value)}"

            properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            required = schema.get("required") if isinstance(schema.get("required"), list) else []
            missing = [key for key in required if isinstance(key, str) and key not in value]
            if missing:
                return f"{path} missing required fields: {missing}"

            for key, field_schema in properties.items():
                if key not in value or not isinstance(field_schema, dict):
                    continue
                err = self._validate_against_schema(value[key], field_schema, f"{path}.{key}")
                if err is not None:
                    return err

            additional_properties = schema.get("additionalProperties", True)
            if additional_properties is False:
                extras = [key for key in value if key not in properties]
                if extras:
                    return f"{path} has unexpected fields: {extras}"
            elif isinstance(additional_properties, dict):
                for key, raw in value.items():
                    if key in properties:
                        continue
                    err = self._validate_against_schema(raw, additional_properties, f"{path}.{key}")
                    if err is not None:
                        return err

        is_array_schema = expected_type == "array" or "items" in schema
        if is_array_schema:
            if not isinstance(value, list):
                return f"{path} expected array, got {self._type_name(value)}"

            min_items = schema.get("minItems")
            if isinstance(min_items, int) and len(value) < min_items:
                return f"{path} must contain at least {min_items} items"

            max_items = schema.get("maxItems")
            if isinstance(max_items, int) and len(value) > max_items:
                return f"{path} must contain at most {max_items} items"

            items_schema = schema.get("items") if isinstance(schema.get("items"), dict) else None
            if items_schema is not None:
                for idx, item in enumerate(value):
                    err = self._validate_against_schema(item, items_schema, f"{path}[{idx}]")
                    if err is not None:
                        return err

        if expected_type == "string" and isinstance(value, str):
            min_len = schema.get("minLength")
            if isinstance(min_len, int) and len(value) < min_len:
                return f"{path} length must be >= {min_len}"
            max_len = schema.get("maxLength")
            if isinstance(max_len, int) and len(value) > max_len:
                return f"{path} length must be <= {max_len}"

        if expected_type in {"integer", "number"} and isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = schema.get("minimum")
            if isinstance(minimum, (int, float)) and value < minimum:
                return f"{path} must be >= {minimum}"

            maximum = schema.get("maximum")
            if isinstance(maximum, (int, float)) and value > maximum:
                return f"{path} must be <= {maximum}"

        return None

    def _matches_type(self, value: Any, expected_type: str) -> bool:
        if expected_type == "object":
            return isinstance(value, dict)
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "null":
            return value is None
        return True

    def _type_name(self, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return type(value).__name__

    def _run_progress(self, request: DecisionInput) -> dict[str, Any]:
        action_count = sum(1 for event in request.history if getattr(event, "kind", None) == "action")
        answer_count = sum(1 for event in request.history if getattr(event, "kind", None) == "answer")
        expected_iterations = request.scenario_meta.expected_iterations if request.scenario_meta else None
        return {
            "query_type": request.scenario_meta.query_type if request.scenario_meta else None,
            "current_iteration": len(request.history) + 1,
            "action_count": action_count,
            "answer_count": answer_count,
            "expected_iterations": expected_iterations,
            "is_late_stage": bool(
                expected_iterations
                and (len(request.history) + 1) >= max(1, expected_iterations - 1)
            ),
        }

    def _compact_hit(self, hit: Any) -> dict[str, Any]:
        value = hit.value if isinstance(hit.value, dict) else {}
        return {
            "id": hit.id,
            "kind": hit.kind,
            "descriptor": hit.descriptor,
            "artifact_id": hit.artifact_id,
            "value_excerpt": json.dumps(value, ensure_ascii=False)[:500],
        }

    def _current_goal_context(self, request: DecisionInput) -> dict[str, Any]:
        goal_events = [event for event in request.history if getattr(event, "goal_id", None) == request.goal.id]
        actions = [event for event in goal_events if getattr(event, "kind", None) == "action"]
        answers = [event for event in goal_events if getattr(event, "kind", None) == "answer"]

        tool_attempts: dict[str, dict[str, Any]] = {}
        recent_failed_tools: list[str] = []
        for event in actions:
            tool = str(getattr(event, "tool", "")).strip() or "<unknown>"
            desc = str(getattr(event, "result_descriptor", ""))
            failed = self._action_failed(desc)

            stats = tool_attempts.setdefault(
                tool,
                {
                    "count": 0,
                    "failed_count": 0,
                    "last_descriptor": "",
                },
            )
            stats["count"] += 1
            if failed:
                stats["failed_count"] += 1
                recent_failed_tools.append(tool)
            stats["last_descriptor"] = desc[:220]

        recent_action_tools = [str(getattr(event, "tool", "")) for event in actions[-4:]]
        recent_descriptors = [str(getattr(event, "result_descriptor", ""))[:220] for event in actions[-3:]]

        return {
            "goal_action_count": len(actions),
            "goal_answer_count": len(answers),
            "has_any_successful_action": any(
                stats.get("count", 0) > stats.get("failed_count", 0)
                for stats in tool_attempts.values()
            ),
            "recent_action_tools": recent_action_tools,
            "recent_failed_tools": list(dict.fromkeys(recent_failed_tools))[-4:],
            "recent_action_descriptors": recent_descriptors,
            "tool_attempts": tool_attempts,
        }

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

    def _is_low_value_answer(self, text: str) -> bool:
        lowered = text.lower().strip()
        if not lowered:
            return True

        if any(
            phrase in lowered
            for phrase in (
                "how would you like",
                "would you like",
                "i can help",
                "let me know",
            )
        ):
            return True

        if len(lowered) >= 30:
            return False

        if self._looks_factual_short_answer(text):
            return False

        return True

    def _looks_factual_short_answer(self, text: str) -> bool:
        lowered = text.lower().strip()

        date_patterns = (
            r"\b\d{4}-\d{2}-\d{2}\b",
            r"\b\d{1,2}\s+[a-z]+\s+\d{4}\b",
            r"\b[a-z]+\s+\d{1,2},\s*\d{4}\b",
        )
        if any(re.search(pattern, lowered) for pattern in date_patterns):
            return True

        if re.search(r"\d", lowered) and len(lowered.split()) >= 4:
            return True

        return False

    def _claims_external_side_effect(self, text: str) -> bool:
        lowered = text.lower()
        markers = (
            "scheduled",
            "saved",
            "written",
            "created",
            "updated",
            "stored",
            "persisted",
        )
        return any(marker in lowered for marker in markers)

    def _should_attempt_answer_recovery(self, violation: str | None, request: DecisionInput) -> bool:
        if not violation:
            return False
        if not self._has_attached_evidence(request) and not self._has_memory_hit_evidence(request):
            return False

        lowered = violation.lower()
        triggers = (
            "already retrieved successfully",
            "repeated identical action",
            "choose a url retrieval tool",
            "memory recall goal has internal evidence",
            "answer directly instead of issuing another tool call",
            "tool arguments do not match input_schema",
            "missing required fields",
            "unexpected fields",
            "expected type",
        )
        return any(token in lowered for token in triggers)

    def _answer_requires_grounded_evidence(self, request: DecisionInput) -> bool:
        goal_text = request.goal.text.lower()
        evidence_cues = (
            "fetch",
            "retrieve",
            "search",
            "read",
            "open",
            "extract",
            "identify",
            "summarize",
            "synthesize",
            "from the source",
            "from source",
            "from provided content",
        )
        if any(token in goal_text for token in evidence_cues):
            return True

        query_type = (request.scenario_meta.query_type if request.scenario_meta else "") or ""
        lowered_type = query_type.lower()
        return any(token in lowered_type for token in ("fact_extraction", "source", "search", "synthesis"))

    def _answer_supported_by_evidence(self, request: DecisionInput) -> bool:
        goal_text = request.goal.text.lower()

        if self._is_memory_recall_context(request) and self._has_memory_hit_evidence(request):
            return True

        if self._has_attached_evidence(request):
            return True

        requires_retrieval = any(token in goal_text for token in ("fetch", "retrieve", "read", "open"))
        requires_search = any(token in goal_text for token in ("search", "find", "lookup", "look up"))

        if requires_retrieval:
            return self._has_successful_action_for_goal(request, action_kind="retrieval")
        if requires_search:
            return self._has_successful_action_for_goal(request, action_kind="search")

        if self._goal_has_successful_action(request):
            return True
        if self._has_successful_retrieval_in_run(request):
            return True

        return False

    def _has_attached_evidence(self, request: DecisionInput) -> bool:
        for att in request.attached:
            text = str(getattr(att, "text", "")).strip()
            if len(text) >= 40:
                return True
        return False

    def _has_successful_action_for_goal(self, request: DecisionInput, action_kind: str) -> bool:
        for event in reversed(request.history):
            if getattr(event, "goal_id", None) != request.goal.id:
                continue
            if getattr(event, "kind", None) != "action":
                continue

            tool = str(getattr(event, "tool", "")).lower().strip()
            if not self._tool_matches_action_kind(tool, action_kind):
                continue

            descriptor = str(getattr(event, "result_descriptor", "")).strip()
            if not descriptor or descriptor in {"[]", "{}", "null"}:
                continue
            if self._action_failed(descriptor):
                continue
            return True

        return False

    def _has_successful_retrieval_in_run(self, request: DecisionInput) -> bool:
        for event in reversed(request.history):
            if getattr(event, "kind", None) != "action":
                continue

            tool = str(getattr(event, "tool", "")).lower().strip()
            if not self._tool_matches_action_kind(tool, "retrieval"):
                continue

            descriptor = str(getattr(event, "result_descriptor", "")).strip()
            if not descriptor or descriptor in {"[]", "{}", "null"}:
                continue
            if self._action_failed(descriptor):
                continue
            return True

        return False

    def _tool_matches_action_kind(self, tool_name: str, action_kind: str) -> bool:
        if action_kind == "search":
            return "search" in tool_name

        if action_kind == "retrieval":
            retrieval_tokens = ("fetch", "read", "open", "crawl", "download")
            return any(token in tool_name for token in retrieval_tokens)

        return False

    def _goal_has_successful_action(self, request: DecisionInput) -> bool:
        for event in reversed(request.history):
            if getattr(event, "goal_id", None) != request.goal.id:
                continue
            if getattr(event, "kind", None) != "action":
                continue

            descriptor = str(getattr(event, "result_descriptor", "")).strip()
            if not descriptor or descriptor in {"[]", "{}", "null"}:
                continue
            if self._action_failed(descriptor):
                continue
            return True

        return False

    def _has_artifact_handle(self, arguments: dict[str, Any]) -> bool:
        for value in arguments.values():
            if isinstance(value, str) and value.startswith("art:"):
                return True
        return False