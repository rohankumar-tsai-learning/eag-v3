from __future__ import annotations

import asyncio
import json
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from config import Settings
from schemas import MemoryClassification

T = TypeVar("T", bound=BaseModel)


class RoleCooldown:
    def __init__(self, seconds: int) -> None:
        self.seconds = max(0, seconds)
        self._lock = asyncio.Lock()
        self._last_role: str | None = None
        self._last_completed_at: float | None = None

    async def wait_if_needed(self, role: str) -> None:
        async with self._lock:
            if self._last_role is None or self._last_completed_at is None:
                return
            elapsed = time.monotonic() - self._last_completed_at
            wait_seconds = self.seconds - elapsed
            if wait_seconds > 0:
                print(
                    f"[cooldown] waiting {wait_seconds:.1f}s before next LLM call "
                    f"(last role: {self._last_role})"
                )
                await asyncio.sleep(wait_seconds)

    async def mark_complete(self, role: str) -> None:
        async with self._lock:
            self._last_role = role
            self._last_completed_at = time.monotonic()


class GeminiClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cooldown = RoleCooldown(settings.llm_cooldown_seconds)

    async def generate_typed(
        self,
        *,
        role: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float,
    ) -> T:
        await self.cooldown.wait_if_needed(role)
        call_completed = False
        try:
            if self.settings.mock_llm:
                out = self._mock_response(response_model, user_prompt)
                call_completed = True
                return out
            if not self.settings.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY is missing. Configure it in .env")

            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.settings.gemini_model}:generateContent"
            )
            payload = {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "responseMimeType": "application/json",
                },
            }

            params = {"key": self.settings.gemini_api_key}
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
                max_attempts = 3
                response: httpx.Response | None = None
                for attempt in range(1, max_attempts + 1):
                    try:
                        response = await client.post(url, params=params, json=payload)
                    except httpx.HTTPError as exc:
                        call_completed = True
                        if attempt < max_attempts:
                            delay = self._retry_delay_seconds(attempt, retry_after=None)
                            print(
                                f"[llm] transport error on {role} attempt {attempt}/{max_attempts}; "
                                f"retrying in {delay:.1f}s ({type(exc).__name__})"
                            )
                            await asyncio.sleep(delay)
                            continue
                        raise RuntimeError(f"Gemini transport error: {exc}") from exc

                    call_completed = True
                    if response.status_code < 400:
                        break

                    if self._is_retryable_gemini_status(response.status_code) and attempt < max_attempts:
                        retry_after = response.headers.get("Retry-After")
                        delay = self._retry_delay_seconds(attempt, retry_after=retry_after)
                        print(
                            f"[llm] transient Gemini error {response.status_code} on "
                            f"{role} attempt {attempt}/{max_attempts}; retrying in {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                        continue

                    break

            if response is None:
                raise RuntimeError("Gemini API call did not return a response")

            if response.status_code >= 400:
                raise RuntimeError(
                    f"Gemini API error {response.status_code}: {response.text[:500]}"
                )

            data = response.json()
            raw_text = self._extract_text(data)
            parsed = self._parse_json(raw_text)
            normalized = self._normalize_for_model(parsed, response_model)
            return response_model.model_validate(normalized)
        finally:
            if call_completed:
                await self.cooldown.mark_complete(role)

    def _is_retryable_gemini_status(self, status_code: int) -> bool:
        return status_code in {408, 409, 425, 429, 500, 502, 503, 504}

    def _retry_delay_seconds(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                parsed = float(retry_after.strip())
                if parsed > 0:
                    return min(parsed, 20.0)
            except ValueError:
                pass
        base = 1.5 * attempt
        return min(base, 8.0)

    def _normalize_for_model(self, parsed: Any, response_model: type[T]) -> Any:
        name = response_model.__name__

        if name == "PerceptionRawOutput":
            return self._normalize_perception_output(parsed)

        # Decision occasionally returns the tool call object directly.
        if name == "DecisionOutput" and isinstance(parsed, dict):
            if (
                "tool_call" not in parsed
                and "answer" not in parsed
                and "name" in parsed
                and "arguments" in parsed
            ):
                return {
                    "answer": None,
                    "tool_call": {
                        "name": parsed.get("name"),
                        "arguments": parsed.get("arguments") or {},
                    },
                }

        # Decision may return a plain answer string.
        if name == "DecisionOutput" and isinstance(parsed, str):
            return {"answer": parsed, "tool_call": None}

        # Memory relevance ranker may return a plain list of IDs.
        if name == "_MemoryRankOutput" and isinstance(parsed, list):
            return {"selected_ids": parsed}

        return parsed

    def _normalize_perception_output(self, parsed: Any) -> Any:
        goals_payload: Any = None

        if isinstance(parsed, list):
            goals_payload = parsed
        elif isinstance(parsed, dict):
            if "goals" in parsed:
                goals_payload = parsed.get("goals")
            elif "plan" in parsed and isinstance(parsed.get("plan"), list):
                goals_payload = parsed.get("plan")
            elif "steps" in parsed and isinstance(parsed.get("steps"), list):
                goals_payload = parsed.get("steps")
            elif "open_goals" in parsed or "done_goals" in parsed:
                normalized: list[dict[str, Any]] = []
                for item in parsed.get("open_goals") or []:
                    goal = self._normalize_perception_goal_item(item, forced_done=False)
                    if goal is not None:
                        normalized.append(goal)
                for item in parsed.get("done_goals") or []:
                    goal = self._normalize_perception_goal_item(item, forced_done=True)
                    if goal is not None:
                        normalized.append(goal)
                return {"goals": normalized}

        if not isinstance(goals_payload, list):
            return parsed

        normalized_goals: list[dict[str, Any]] = []
        for item in goals_payload:
            goal = self._normalize_perception_goal_item(item)
            if goal is not None:
                normalized_goals.append(goal)

        return {"goals": normalized_goals}

    def _normalize_perception_goal_item(
        self,
        item: Any,
        *,
        forced_done: bool | None = None,
    ) -> dict[str, Any] | None:
        if isinstance(item, str):
            text = item.strip()
            if not text:
                return None
            return {
                "text": text,
                "done": bool(forced_done) if forced_done is not None else False,
                "attach_artifact_index": None,
            }

        if not isinstance(item, dict):
            return None

        text = self._extract_goal_text(item)
        if not text:
            return None

        done = bool(forced_done) if forced_done is not None else self._extract_goal_done(item)
        attach_index = self._extract_goal_attach_index(item)
        return {
            "text": text,
            "done": done,
            "attach_artifact_index": attach_index,
        }

    def _extract_goal_text(self, goal_like: dict[str, Any]) -> str:
        keys = (
            "text",
            "goal",
            "task",
            "step",
            "objective",
            "description",
            "title",
            "name",
        )
        for key in keys:
            value = goal_like.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = self._extract_goal_text(value)
                if nested:
                    return nested
        return ""

    def _extract_goal_done(self, goal_like: dict[str, Any]) -> bool:
        if isinstance(goal_like.get("done"), bool):
            return bool(goal_like.get("done"))
        if isinstance(goal_like.get("completed"), bool):
            return bool(goal_like.get("completed"))
        status = goal_like.get("status")
        if isinstance(status, str):
            return status.strip().lower() in {"done", "completed", "closed"}
        return False

    def _extract_goal_attach_index(self, goal_like: dict[str, Any]) -> int | None:
        raw = goal_like.get("attach_artifact_index")
        if raw is None:
            raw = goal_like.get("artifact_index")
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.strip().isdigit():
            return int(raw.strip())
        return None

    def _extract_text(self, data: dict[str, Any]) -> str:
        candidates = data.get("candidates") or []
        if not candidates:
            prompt_feedback = data.get("promptFeedback")
            raise RuntimeError(f"Gemini returned no candidates. promptFeedback={prompt_feedback}")

        parts = (candidates[0].get("content") or {}).get("parts") or []
        texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
        joined = "\n".join(t for t in texts if t)
        if not joined:
            finish_reason = candidates[0].get("finishReason")
            raise RuntimeError(f"Gemini candidate had no text content. finishReason={finish_reason}")
        return joined

    def _parse_json(self, raw_text: str) -> Any:
        text = raw_text.strip()

        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            candidate = self._extract_first_json_block(text)
            if candidate is None:
                raise
            return json.loads(candidate)

    def _extract_first_json_block(self, text: str) -> str | None:
        in_string = False
        escape = False
        depth = 0
        start = -1

        for idx, ch in enumerate(text):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue

            if ch in "[{":
                if depth == 0:
                    start = idx
                depth += 1
                continue

            if ch in "]}":
                if depth == 0:
                    continue
                depth -= 1
                if depth == 0 and start >= 0:
                    return text[start: idx + 1]
        return None

    def _mock_response(self, response_model: type[T], user_prompt: str) -> T:
        name = response_model.__name__
        if name == "MemoryClassification":
            kind = "fact" if "birthday" in user_prompt.lower() else "scratchpad"
            data = MemoryClassification(
                kind=kind,
                keywords=["mock", "memory"],
                descriptor="Mock classification output",
                value={"raw": user_prompt[:100]},
                confidence=0.6,
            ).model_dump()
            return response_model.model_validate(data)

        # Generic mock fallback for local syntax-only runs.
        raise RuntimeError(
            "MOCK_LLM=true is enabled, but no mock mapping exists for "
            f"{response_model.__name__}."
        )
