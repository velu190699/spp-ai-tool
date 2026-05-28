from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DocumentCheck:
    is_new: bool
    hash_changed: bool
    existing: dict[str, Any] | None


class MetadataStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"documents": {}, "runs": []}
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def key(document_id: str, filename: str) -> str:
        # This mirrors the business duplicate rule; hashes are advisory only.
        return f"{document_id}|{filename}"

    def check_document(self, document_id: str, filename: str, sha256: str | None = None) -> DocumentCheck:
        existing = self.data.setdefault("documents", {}).get(self.key(document_id, filename))
        if not existing:
            return DocumentCheck(is_new=True, hash_changed=False, existing=None)
        hash_changed = bool(sha256 and existing.get("sha256") and existing.get("sha256") != sha256)
        return DocumentCheck(is_new=False, hash_changed=hash_changed, existing=existing)

    def record_document(self, document_id: str, filename: str, metadata: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        key = self.key(document_id, filename)
        previous = self.data.setdefault("documents", {}).get(key, {})
        self.data["documents"][key] = {**previous, **metadata, "document_id": document_id, "filename": filename, "seen_at": now}

    def latest_local_path(self, document_id: str, filename: str) -> Path | None:
        existing = self.data.setdefault("documents", {}).get(self.key(document_id, filename))
        if not existing or not existing.get("local_path"):
            return None
        path = Path(existing["local_path"])
        return path if path.exists() else None

    def append_run(self, run_summary: dict[str, Any]) -> None:
        self.data.setdefault("runs", []).append(run_summary)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2, sort_keys=True)
            handle.write("\n")
