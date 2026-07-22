from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentCheck:
    is_new: bool
    hash_changed: bool
    existing: dict[str, Any] | None


def current_initiative(mentions_seen: list[dict[str, Any]]) -> tuple[str, str]:
    """The market initiative from the NEWEST-dated mention that names one.

    Each ``mentions_seen`` entry is one CUF/SUF edition that mentioned the RR,
    carrying ``meeting_date`` (ISO, sortable), ``initiative`` and
    ``initiative_citation``. A later edition updates the current initiative; a
    silent edition (blank initiative) never blanks a value an earlier edition
    captured. Returns ``("", "")`` when no edition named one.
    """
    best_key: tuple[str, str] | None = None
    best: tuple[str, str] = ("", "")
    for entry in mentions_seen:
        if not entry.get("initiative"):
            continue
        key = (entry.get("meeting_date") or "", entry.get("edition") or "")
        if best_key is None or key >= best_key:
            best_key = key
            best = (entry.get("initiative", ""), entry.get("initiative_citation", ""))
    return best


class MetadataStore:
    """JSON ledger of every document the tool has seen and every analysis it ran.

    The store lives in the synced SharePoint folder (see config.yaml
    ``state_file``) so any machine that runs the tool — a teammate's laptop
    today, a VM later — continues from the same state instead of reprocessing
    everything. It is the tool's memory across runs:

    - ``documents``: what was downloaded, from where, with which content hash.
    - ``analyses``: which outputs were produced from which document version,
      so a re-published document (new hash) is re-analyzed and flagged as an
      UPDATE instead of silently skipped or silently overwritten.
    - ``relevant_rrs``: the last computed cross-reference, carried forward on
      no-change runs and shared across machines.
    - ``mentions_cache`` / ``runs``: parse cache and run audit trail.
    """

    def __init__(self, path: Path, legacy_path: Path | None = None) -> None:
        self.path = path
        self.legacy_path = legacy_path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        # One-time migration: older versions kept state repo-local
        # (data/state/metadata.json). If the shared file doesn't exist yet but
        # the legacy one does, start from the legacy content; the next save()
        # writes it to the shared location.
        source = self.path
        if not source.exists() and self.legacy_path and self.legacy_path.exists():
            LOGGER.info("Migrating state from legacy %s to %s", self.legacy_path, self.path)
            source = self.legacy_path
        if not source.exists():
            return {"documents": {}, "runs": []}
        with source.open("r", encoding="utf-8") as handle:
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

    # ------------------------------------------------------------------
    # Analysis ledger: which outputs were produced from which input version.
    # ------------------------------------------------------------------

    def check_analysis(self, kind: str, key: str, input_hash: str) -> str:
        """Has ``kind`` already been run for ``key`` at this input version?

        Returns ``"new"`` (never analyzed), ``"unchanged"`` (analyzed at this
        exact input hash — safe to skip), or ``"updated"`` (analyzed before,
        but the input has changed since — re-analyze and flag as an UPDATE).
        """
        existing = self.data.setdefault("analyses", {}).get(f"{kind}|{key}")
        if not existing:
            return "new"
        return "unchanged" if existing.get("input_hash") == input_hash else "updated"

    def get_analysis(self, kind: str, key: str) -> dict[str, Any] | None:
        """The recorded analysis entry for ``kind|key`` (or None), incl. outputs."""
        return self.data.get("analyses", {}).get(f"{kind}|{key}")

    def record_analysis(self, kind: str, key: str, input_hash: str, outputs: dict[str, Any] | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        entry_key = f"{kind}|{key}"
        previous = self.data.setdefault("analyses", {}).get(entry_key, {})
        history = previous.get("history", [])
        if previous and previous.get("input_hash") != input_hash:
            # Keep a compact trail of superseded versions for auditability.
            history = history + [{"input_hash": previous.get("input_hash"), "analyzed_at": previous.get("analyzed_at")}]
        self.data["analyses"][entry_key] = {
            "kind": kind,
            "key": key,
            "input_hash": input_hash,
            "analyzed_at": now,
            "outputs": outputs or {},
            "history": history,
        }

    # ------------------------------------------------------------------
    # Relevant-RRs carry-forward (shared across machines via the store).
    # ------------------------------------------------------------------

    def save_relevant_rrs(self, relevant_rrs: list[dict[str, Any]]) -> None:
        self.data["relevant_rrs"] = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "items": relevant_rrs,
        }

    def load_relevant_rrs(self) -> list[dict[str, Any]] | None:
        entry = self.data.get("relevant_rrs")
        if not entry:
            return None
        return entry.get("items") or None

    # ------------------------------------------------------------------
    # Watch list (Option B): RRs tracked for settlement while OPEN. CUF/SUF only
    # DISCOVERS an RR and names its market initiative; from then on the RR is
    # watched by Recommendation-Report change for as long as the RR Master List
    # shows it open — so a late revision isn't missed just because a newer
    # CUF/SUF stopped mentioning it. On close it gets one final capture, then is
    # removed. Keyed by RR number (digits, no "RR" prefix).
    # ------------------------------------------------------------------

    def upsert_watched(self, rr_number: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Add or update a watched RR, merging ``fields``.

        Preserves ``first_seen`` and never lets a later blank overwrite a value
        already captured — e.g. the market initiative discovered on an earlier
        CUF/SUF edition survives a later run whose materials don't name it.
        """
        now = datetime.now(timezone.utc).isoformat()
        watched = self.data.setdefault("watched_rrs", {})
        merged = dict(watched.get(rr_number, {}))
        for field, value in fields.items():
            if value not in (None, "") or field not in merged:
                merged[field] = value
        merged["rr_number"] = str(rr_number)
        merged.setdefault("first_seen", now)
        merged["last_seen"] = now
        merged.setdefault("status", "open")
        watched[rr_number] = merged
        return merged

    def list_watched(self, *, status: str | None = None) -> list[dict[str, Any]]:
        items = list(self.data.get("watched_rrs", {}).values())
        if status is not None:
            items = [w for w in items if w.get("status") == status]
        return sorted(items, key=lambda w: int(w["rr_number"]) if str(w.get("rr_number", "")).isdigit() else 0)

    def get_watched(self, rr_number: str) -> dict[str, Any] | None:
        return self.data.get("watched_rrs", {}).get(rr_number)

    def set_watched_status(self, rr_number: str, status: str) -> None:
        watched = self.data.setdefault("watched_rrs", {}).get(rr_number)
        if watched:
            watched["status"] = status
            watched["last_seen"] = datetime.now(timezone.utc).isoformat()

    def remove_watched(self, rr_number: str) -> None:
        self.data.setdefault("watched_rrs", {}).pop(rr_number, None)

    # ------------------------------------------------------------------
    # Initiative accumulation across CUF/SUF editions (Option B). Each edition is
    # parsed ONCE (tracked here); a watched RR keeps a per-edition mentions_seen
    # history so an initiative named only in an OLDER edition (e.g. RR750) is
    # recovered, and its "current" initiative is the newest edition that names one.
    # ------------------------------------------------------------------

    def is_edition_parsed(self, edition_key: str) -> bool:
        return edition_key in self.data.get("parsed_editions", {})

    def mark_edition_parsed(self, edition_key: str, meta: dict[str, Any] | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.data.setdefault("parsed_editions", {})[edition_key] = {**(meta or {}), "parsed_at": now}

    def add_watched_mention(self, rr_number: str, entry: dict[str, Any]) -> dict[str, Any] | None:
        """Record one edition's mention of a WATCHED RR and refresh its initiative.

        No-op if the RR isn't watched: the backfill fills watched RRs only, never
        resurrecting an RR discovered solely in an old edition. Dedupes by
        ``edition`` so re-accumulation is idempotent, then recomputes
        ``market_initiative`` from :func:`current_initiative` — a later edition
        updates it, a silent edition never blanks it.
        """
        watched = self.data.setdefault("watched_rrs", {}).get(str(rr_number))
        if watched is None:
            return None
        history = watched.setdefault("mentions_seen", [])
        edition_key = entry.get("edition", "")
        history[:] = [h for h in history if h.get("edition") != edition_key]
        history.append(entry)
        label, citation = current_initiative(history)
        if label:
            watched["market_initiative"] = label
            watched["market_initiative_citation"] = citation
        watched["last_seen"] = datetime.now(timezone.utc).isoformat()
        return watched

    def save_mentions(self, family: str, mentions: dict[str, Any]) -> None:
        self.data.setdefault("mentions_cache", {})[family] = mentions

    def load_mentions(self, family: str) -> dict[str, Any] | None:
        return self.data.get("mentions_cache", {}).get(family)

    def append_run(self, run_summary: dict[str, Any]) -> None:
        self.data.setdefault("runs", []).append(run_summary)

    def save(self) -> None:
        # Atomic write (temp file + rename): the store lives in a OneDrive-synced
        # folder, and a partially-written JSON there would sync as corruption.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temp_name, self.path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
