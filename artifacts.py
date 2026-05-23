from __future__ import annotations

import hashlib
import json
from pathlib import Path

from schemas import Artifact


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put(
        self,
        blob: bytes,
        *,
        content_type: str,
        source: str,
        descriptor: str,
    ) -> str:
        digest = hashlib.sha256(blob).hexdigest()
        artifact_id = f"art:{digest[:16]}"

        bin_path = self.root / f"{artifact_id}.bin"
        meta_path = self.root / f"{artifact_id}.json"

        if not bin_path.exists():
            bin_path.write_bytes(blob)
        if not meta_path.exists():
            meta = Artifact(
                id=artifact_id,
                content_type=content_type,
                size_bytes=len(blob),
                source=source,
                descriptor=descriptor,
            )
            meta_path.write_text(json.dumps(meta.model_dump(mode="json"), indent=2), encoding="utf-8")

        return artifact_id

    def get_bytes(self, artifact_id: str) -> bytes:
        return (self.root / f"{artifact_id}.bin").read_bytes()

    def get_meta(self, artifact_id: str) -> Artifact:
        text = (self.root / f"{artifact_id}.json").read_text(encoding="utf-8")
        return Artifact.model_validate_json(text)

    def exists(self, artifact_id: str) -> bool:
        return (
            (self.root / f"{artifact_id}.bin").exists()
            and (self.root / f"{artifact_id}.json").exists()
        )
