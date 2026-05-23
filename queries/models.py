from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QueryScenario:
    name: str
    display_name: str
    query_text: str
    query_type: str
    expected_iterations: int
    max_pass_iterations: int
    metadata: dict[str, Any] | None = None
