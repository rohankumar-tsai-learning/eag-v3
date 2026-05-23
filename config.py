from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.1-flash-lite", alias="GEMINI_MODEL")

    llm_cooldown_seconds: int = Field(default=60, alias="LLM_COOLDOWN_SECONDS", ge=0)
    llm_timeout_seconds: int = Field(default=90, alias="LLM_TIMEOUT_SECONDS", ge=10)
    tool_timeout_seconds: int = Field(default=60, alias="TOOL_TIMEOUT_SECONDS", ge=5)

    max_iterations: int = Field(default=14, alias="MAX_ITERATIONS", ge=1)
    artifact_threshold_bytes: int = Field(default=4096, alias="ARTIFACT_THRESHOLD_BYTES", ge=256)
    attach_max_chars: int = Field(default=20000, alias="ATTACH_MAX_CHARS", ge=1000)

    state_dir: Path = Field(default=Path("state"), alias="STATE_DIR")
    memory_file: str = Field(default="memory.json", alias="MEMORY_FILE")
    artifact_dir: str = Field(default="artifacts", alias="ARTIFACT_DIR")

    mcp_server_command: str = Field(default="uv", alias="MCP_SERVER_COMMAND")
    mcp_server_args: str = Field(default="run,mcp_server.py", alias="MCP_SERVER_ARGS")

    perception_temperature: float = Field(default=1.0, alias="PERCEPTION_TEMPERATURE")
    decision_temperature: float = Field(default=0.3, alias="DECISION_TEMPERATURE")
    memory_temperature: float = Field(default=0.2, alias="MEMORY_TEMPERATURE")

    memory_top_k: int = Field(default=8, alias="MEMORY_TOP_K", ge=1)
    memory_relevant_top_k: int = Field(default=5, alias="MEMORY_RELEVANT_TOP_K", ge=1)

    mock_llm: bool = Field(default=False, alias="MOCK_LLM")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def memory_path(self) -> Path:
        return self.state_dir / self.memory_file

    @field_validator("llm_cooldown_seconds", mode="after")
    @classmethod
    def _min_cooldown(cls, v: int) -> int:
        # Enforce at least one-minute spacing between all LLM calls.
        return 20 if v < 20 else v

    @property
    def artifacts_path(self) -> Path:
        return self.state_dir / self.artifact_dir

    @property
    def mcp_args(self) -> list[str]:
        raw = self.mcp_server_args.strip()
        if not raw:
            return []
        return [piece.strip() for piece in raw.split(",") if piece.strip()]


def ensure_state_dirs(settings: Settings) -> None:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    settings.artifacts_path.mkdir(parents=True, exist_ok=True)
    if not settings.memory_path.exists():
        settings.memory_path.write_text("[]", encoding="utf-8")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
