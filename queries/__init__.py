from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from queries.models import QueryScenario


def _discover_scenarios() -> dict[str, QueryScenario]:
    scenarios: dict[str, QueryScenario] = {}
    package_dir = Path(__file__).parent

    for module_info in pkgutil.iter_modules([str(package_dir)]):
        module_name = module_info.name
        if not module_name.startswith("query_"):
            continue

        module = importlib.import_module(f"{__name__}.{module_name}")
        for value in vars(module).values():
            if not isinstance(value, QueryScenario):
                continue
            if value.name in scenarios:
                raise ValueError(f"Duplicate scenario name discovered: {value.name}")
            scenarios[value.name] = value

    return scenarios


SCENARIOS: dict[str, QueryScenario] = _discover_scenarios()
DEFAULT_ORDER = sorted(SCENARIOS.keys())


def get_scenario(name: str) -> QueryScenario:
    if name not in SCENARIOS:
        raise KeyError(f"Unknown scenario: {name}")
    return SCENARIOS[name]


def list_scenarios() -> list[QueryScenario]:
    return [SCENARIOS[name] for name in DEFAULT_ORDER]


def list_query_choices() -> list[str]:
    scenario_names = [scenario.name for scenario in list_scenarios()]
    alias_names = _list_query_aliases()
    return scenario_names + [alias for alias in alias_names if alias not in scenario_names]


def expand_query_selection(name: str) -> list[QueryScenario]:
    if name in SCENARIOS:
        return [SCENARIOS[name]]

    prefix = f"{name}_"
    matched = [SCENARIOS[scenario_name] for scenario_name in DEFAULT_ORDER if scenario_name.startswith(prefix)]
    if matched:
        return matched

    raise KeyError(f"Unknown query selection: {name}")


def _list_query_aliases() -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()

    for scenario_name in DEFAULT_ORDER:
        parts = scenario_name.split("_")
        if len(parts) < 2:
            continue
        alias = "_".join(parts[:2])
        if alias in seen:
            continue
        seen.add(alias)
        aliases.append(alias)

    return aliases
