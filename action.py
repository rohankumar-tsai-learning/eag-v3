from __future__ import annotations

import asyncio
import json
from typing import Any

from artifacts import ArtifactStore
from config import Settings
from schemas import ActionInput, ActionOutput


class ActionRole:
    def __init__(self, settings: Settings, artifacts: ArtifactStore) -> None:
        self.settings = settings
        self.artifacts = artifacts

    async def execute(self, session: Any, request: ActionInput) -> ActionOutput:
        if self._contains_artifact_handle(request.tool_call.arguments):
            return ActionOutput(
                descriptor=(
                    "[error] artifact handles (art:...) are internal references, "
                    "not valid paths or URLs for MCP tools"
                ),
                artifact_id=None,
            )

        try:
            result = await asyncio.wait_for(
                session.call_tool(
                    request.tool_call.name,
                    arguments=request.tool_call.arguments,
                ),
                timeout=self.settings.tool_timeout_seconds,
            )
        except TimeoutError:
            return ActionOutput(
                descriptor=(
                    f"[tool_timeout] {request.tool_call.name} exceeded "
                    f"{self.settings.tool_timeout_seconds}s"
                ),
                artifact_id=None,
            )
        except Exception as exc:
            return ActionOutput(descriptor=f"[tool_error] {exc}", artifact_id=None)

        text = self._collapse_result(result)
        blob = text.encode("utf-8")

        if len(blob) > self.settings.artifact_threshold_bytes:
            descriptor = text[:300].replace("\n", " ").strip()
            artifact_id = self.artifacts.put(
                blob,
                content_type="text/plain",
                source=request.tool_call.name,
                descriptor=descriptor,
            )
            return ActionOutput(
                descriptor=f"[artifact {artifact_id}, {len(blob)} bytes] preview: {descriptor}",
                artifact_id=artifact_id,
            )

        return ActionOutput(descriptor=text, artifact_id=None)

    def _contains_artifact_handle(self, arguments: dict[str, Any]) -> bool:
        for value in arguments.values():
            if isinstance(value, str) and value.startswith("art:"):
                return True
        return False

    def _collapse_result(self, result: Any) -> str:
        if result is None:
            return ""

        if isinstance(result, str):
            return result

        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False, indent=2)

        content = getattr(result, "content", None)
        if isinstance(content, list):
            chunks: list[str] = []
            for block in content:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    chunks.append(text)
                    continue
                dump = getattr(block, "model_dump", None)
                if callable(dump):
                    chunks.append(json.dumps(dump(), ensure_ascii=False))
                    continue
                if isinstance(block, dict):
                    chunks.append(json.dumps(block, ensure_ascii=False))
                    continue
                chunks.append(str(block))
            return "\n".join(chunks)

        dump_result = getattr(result, "model_dump", None)
        if callable(dump_result):
            return json.dumps(dump_result(), ensure_ascii=False, indent=2)

        return str(result)
