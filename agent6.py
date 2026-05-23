from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import uuid

from action import ActionRole
from artifacts import ArtifactStore
from config import ensure_state_dirs, get_settings
from decision import DecisionRole
from llm_client import GeminiClient
from mcp_runtime import load_tools, mcp_session
from memory import MemoryService
from perception import PerceptionRole
from queries import DEFAULT_ORDER, expand_query_selection, get_scenario, list_query_choices, list_scenarios
from queries.models import QueryScenario
from schemas import (
    ActionInput,
    AttachedArtifact,
    DecisionInput,
    HistoryActionEvent,
    HistoryAnswerEvent,
    MemoryReadRequest,
    MemoryRecordOutcomeRequest,
    MemoryRememberRequest,
    PerceptionInput,
    ScenarioMeta,
)


class Agent6Runner:
    def __init__(self) -> None:
        self.settings = get_settings()
        ensure_state_dirs(self.settings)

        self.llm = GeminiClient(self.settings)
        self.artifacts = ArtifactStore(self.settings.artifacts_path)
        self.memory = MemoryService(self.settings, self.llm)
        self.perception = PerceptionRole(self.settings, self.llm)
        self.decision = DecisionRole(self.settings, self.llm)
        self.action = ActionRole(self.settings, self.artifacts)

    async def run_scenario(self, scenario: QueryScenario) -> str:
        print(f"\n=== {scenario.display_name} ===")
        print(scenario.query_text)
        print()

        run_id = uuid.uuid4().hex[:8]
        history: list[HistoryActionEvent | HistoryAnswerEvent] = []
        prior_goals = []
        scenario_meta = ScenarioMeta(
            name=scenario.name,
            display_name=scenario.display_name,
            query_type=scenario.query_type,
            expected_iterations=scenario.expected_iterations,
            max_pass_iterations=scenario.max_pass_iterations,
            metadata=scenario.metadata or {},
        )

        remembered = await self.memory.remember(
            MemoryRememberRequest(
                raw_text=scenario.query_text,
                source="user_query",
                run_id=run_id,
                goal_id=None,
            )
        )
        print(
            f"[memory.remember] classified as {remembered.kind} | "
            f"keywords={remembered.keywords[:6]}"
        )

        max_iterations = min(self.settings.max_iterations, scenario.max_pass_iterations)

        async with mcp_session(self.settings) as session:
            mcp_tools = await load_tools(session)

            for iteration in range(1, max_iterations + 1):
                print(f"\n--- iter {iteration} ---")

                hits = self.memory.read(
                    MemoryReadRequest(
                        query=scenario.query_text,
                        history=history,
                        top_k=self.settings.memory_top_k,
                    )
                ).hits
                print(f"[memory.read]   {len(hits)} hits")

                obs = await self.perception.observe(
                    PerceptionInput(
                        query=scenario.query_text,
                        hits=hits,
                        history=history,
                        prior_goals=prior_goals,
                        run_id=run_id,
                        scenario_name=scenario.name,
                        scenario_meta=scenario_meta,
                    )
                )
                prior_goals = obs.goals

                for goal in obs.goals:
                    prefix = "done" if goal.done else "open"
                    line = f"[perception]    [{prefix}] {goal.text}"
                    if goal.attach_artifact_id:
                        line += f" | attach={goal.attach_artifact_id}"
                    print(line)

                if obs.all_done:
                    print(f"\n[done] all {len(obs.goals)} goals satisfied")
                    break

                goal = obs.next_unfinished()
                if goal is None:
                    print("[warning] no unfinished goal found; stopping")
                    break

                attached: list[AttachedArtifact] = []
                if goal.attach_artifact_id and self.artifacts.exists(goal.attach_artifact_id):
                    blob = self.artifacts.get_bytes(goal.attach_artifact_id)
                    text = blob.decode("utf-8", errors="replace")
                    attached.append(
                        AttachedArtifact(
                            artifact_id=goal.attach_artifact_id,
                            text=text[: self.settings.attach_max_chars],
                            size_bytes=len(blob),
                        )
                    )
                    print(f"[attach]        {goal.attach_artifact_id} ({len(blob)} bytes)")

                out = await self.decision.next_step(
                    DecisionInput(
                        goal=goal,
                        hits=hits,
                        attached=attached,
                        history=history,
                        mcp_tools=mcp_tools,
                        scenario_name=scenario.name,
                        scenario_meta=scenario_meta,
                    )
                )

                if out.is_answer:
                    answer_text = out.answer or ""
                    print(f"[decision]      ANSWER: {answer_text[:280]}")
                    history.append(
                        HistoryAnswerEvent(
                            iter=iteration,
                            goal_id=goal.id,
                            text=answer_text,
                        )
                    )

                    continue

                assert out.tool_call is not None
                print(
                    f"[decision]      TOOL_CALL: {out.tool_call.name}("
                    f"{json.dumps(out.tool_call.arguments, ensure_ascii=False)})"
                )

                action_out = await self.action.execute(
                    session,
                    ActionInput(
                        tool_call=out.tool_call,
                        run_id=run_id,
                        goal_id=goal.id,
                    ),
                )
                print(f"[action]        -> {action_out.descriptor[:280]}")

                self.memory.record_outcome(
                    MemoryRecordOutcomeRequest(
                        tool_call=out.tool_call,
                        result_text=action_out.descriptor,
                        artifact_id=action_out.artifact_id,
                        run_id=run_id,
                        goal_id=goal.id,
                    )
                )
                history.append(
                    HistoryActionEvent(
                        iter=iteration,
                        goal_id=goal.id,
                        tool=out.tool_call.name,
                        arguments=out.tool_call.arguments,
                        result_descriptor=action_out.descriptor[:500],
                        artifact_id=action_out.artifact_id,
                    )
                )
            else:
                print(
                    f"\n[warning] max iterations reached ({max_iterations}) "
                    f"for scenario {scenario.name}"
                )

        final_answer = self._final_answer_from_history(history, scenario)
        print(f"\nFINAL: {final_answer}\n")
        return final_answer

    def _final_answer_from_history(
        self,
        history: list[HistoryActionEvent | HistoryAnswerEvent],
        scenario: QueryScenario,
    ) -> str:
        answers = [event.text for event in history if event.kind == "answer" and event.text.strip()]
        if answers:
            latest = answers[-1]
            required_outputs = self._required_outputs_for_scenario(scenario)
            if required_outputs and not self._answer_satisfies_required_outputs(latest, required_outputs):
                combined = self._combine_unique_answers(answers)
                if self._answer_satisfies_required_outputs(combined, required_outputs):
                    return combined
            return latest

        actions = [event.result_descriptor for event in history if event.kind == "action"]
        if actions:
            return actions[-1]

        return "No final answer generated."

    def _required_outputs_for_scenario(self, scenario: QueryScenario) -> list[str]:
        metadata = scenario.metadata if isinstance(scenario.metadata, dict) else {}
        context = metadata.get("context") if isinstance(metadata.get("context"), dict) else {}
        raw = context.get("required_outputs")
        if not isinstance(raw, list):
            return []

        required: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                continue
            normalized = item.strip().lower().replace("_", " ")
            if normalized:
                required.append(normalized)
        return required

    def _answer_satisfies_required_outputs(self, answer: str, required_outputs: list[str]) -> bool:
        lowered = answer.lower()
        for field in required_outputs:
            if not self._contains_required_field(lowered, field):
                return False
        return True

    def _contains_required_field(self, answer_lower: str, field: str) -> bool:
        tokens = [token for token in re.findall(r"[a-z0-9]+", field) if token not in {"key"}]
        if not tokens:
            return True

        date_like = bool(re.search(r"\b\d{4}\b", answer_lower))
        for token in tokens:
            variants = {token}
            if token == "birth":
                variants.add("born")
            elif token == "death":
                variants.update({"died", "deceased"})
            elif token.startswith("contribution"):
                variants.update({"contribution", "contributions"})

            if any(variant in answer_lower for variant in variants):
                continue
            if token == "date" and date_like:
                continue
            return False

        return True

    def _combine_unique_answers(self, answers: list[str]) -> str:
        merged: list[str] = []
        seen: set[str] = set()
        for text in answers:
            normalized = " ".join(text.split()).strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(text.strip())
        return "\n".join(merged)


def clean_state() -> None:
    settings = get_settings()
    sandbox_dir = settings.state_dir.parent / "sandbox"
    if not settings.state_dir.exists():
        ensure_state_dirs(settings)
        print(f"State cleaned at: {settings.state_dir}")
    else:
        try:
            shutil.rmtree(settings.state_dir)
            ensure_state_dirs(settings)
            print(f"State cleaned at: {settings.state_dir}")
        except PermissionError as exc:
            print(f"[clean_state] full delete blocked: {exc}. Falling back to partial cleanup.")

            # Fallback cleanup when Windows file locks prevent deleting state/artifacts.
            settings.state_dir.mkdir(parents=True, exist_ok=True)
            settings.artifacts_path.mkdir(parents=True, exist_ok=True)

            # Always reset memory for a clean logical run.
            settings.memory_path.write_text("[]", encoding="utf-8")

            locked = 0
            for child in settings.artifacts_path.glob("*"):
                try:
                    if child.is_file() or child.is_symlink():
                        child.unlink()
                    else:
                        shutil.rmtree(child)
                except PermissionError:
                    locked += 1

            if locked:
                print(
                    f"[clean_state] memory reset complete; {locked} locked artifact entries "
                    "could not be deleted right now."
                )
            else:
                print(f"State cleaned at: {settings.state_dir}")

    # Also clear sandbox files created by MCP file tools so query traces stay deterministic.
    if sandbox_dir.exists():
        unresolved: set[str] = set()
        for child in sandbox_dir.glob("*"):
            try:
                if child.is_file() or child.is_symlink():
                    child.unlink()
                else:
                    shutil.rmtree(child)
            except PermissionError:
                # Retry once with relaxed permissions before reporting it as unresolved.
                try:
                    if child.exists() and (child.is_file() or child.is_symlink()):
                        child.chmod(0o666)
                        child.unlink(missing_ok=True)
                    elif child.exists():
                        shutil.rmtree(child)
                except (PermissionError, OSError):
                    if child.exists():
                        unresolved.add(child.name)
            except OSError:
                if child.exists():
                    unresolved.add(child.name)

        # Re-check actual leftovers so warnings are about real remaining entries.
        ignore_names = {"desktop.ini", "thumbs.db"}
        for child in sandbox_dir.glob("*"):
            if child.name.lower() in ignore_names:
                continue
            unresolved.add(child.name)

        if unresolved:
            print(
                f"[clean_state] sandbox cleanup skipped for {len(unresolved)} locked entries."
            )


async def run_selected(query_name: str, run_all: bool) -> None:
    runner = Agent6Runner()

    if run_all:
        for name in DEFAULT_ORDER:
            await runner.run_scenario(get_scenario(name))
        return

    selected = expand_query_selection(query_name)
    for scenario in selected:
        await runner.run_scenario(scenario)


def parse_args() -> argparse.Namespace:
    scenario_names = [scenario.name for scenario in list_scenarios()]
    query_choices = list_query_choices()
    if not scenario_names or not query_choices:
        raise RuntimeError("No scenarios configured")

    parser = argparse.ArgumentParser(description="Session 6-style agentic architecture runner")
    parser.add_argument(
        "--query",
        default=scenario_names[0],
        choices=query_choices,
        help="Named query scenario (or query group alias) to run",
    )
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Run all target scenarios in default order",
    )
    parser.add_argument(
        "--clean-state",
        action="store_true",
        help="Delete and recreate state/ directory, then exit",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.clean_state:
        clean_state()
        return
    asyncio.run(run_selected(args.query, args.run_all))


if __name__ == "__main__":
    main()
