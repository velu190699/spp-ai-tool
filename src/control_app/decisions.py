"""PM decisions for the RR Control app — the half of the dashboard a human owns.

The tool owns ``metadata.json`` and never writes here; this store owns
``decisions.db`` and never writes there. The two are joined by RR number when the
table is drawn. That split is the whole point: a weekly run can never overwrite
what a PM just marked, and the run keeps working whether or not anyone ever opens
the app.

The file is meant to live on the NAS, NOT in the OneDrive-synced folder: OneDrive
syncs whole files and resolves clashes by making conflict copies, which for
SQLite means silent corruption. Only PMs write, and rarely, so plain rollback
journaling with a long busy timeout is enough — WAL is deliberately not used
because its shared-memory file does not work on SMB shares.
"""

from __future__ import annotations

import getpass
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Columns a PM edits. Everything else on the row comes from the tool.
EDITABLE = (
    "applies",
    "reviewed",
    "initiative_validated",
    "related_rr",
    "jira_key",
    "note",
)

APPLIES_VALUES = ("", "Yes", "No")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS initiatives (
    name       TEXT PRIMARY KEY,
    active     INTEGER NOT NULL DEFAULT 1,
    note       TEXT NOT NULL DEFAULT '',
    added_by   TEXT NOT NULL DEFAULT '',
    added_at   TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS decisions (
    rr_number            TEXT PRIMARY KEY,
    domain               TEXT NOT NULL DEFAULT '',
    applies              TEXT NOT NULL DEFAULT '',
    reviewed             INTEGER NOT NULL DEFAULT 0,
    reviewed_by          TEXT NOT NULL DEFAULT '',
    reviewed_at          TEXT NOT NULL DEFAULT '',
    initiative_validated TEXT NOT NULL DEFAULT '',
    related_rr           TEXT NOT NULL DEFAULT '',
    jira_key             TEXT NOT NULL DEFAULT '',
    note                 TEXT NOT NULL DEFAULT '',
    class_when_decided   TEXT NOT NULL DEFAULT '',
    updated_at           TEXT NOT NULL DEFAULT ''
);
"""


def current_user() -> str:
    """Who is marking. Records authorship; it is not access control."""
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


class DecisionStore:
    def __init__(self, db_path: Path | str):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self):
        # 15s covers another PM's write landing over SMB; the alternative is an
        # immediate "database is locked" in someone's face.
        conn = sqlite3.connect(self.path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def all(self) -> dict[str, dict[str, Any]]:
        """Every decision, keyed by RR number."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM decisions").fetchall()
        return {r["rr_number"]: dict(r) for r in rows}

    def get(self, rr_number: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM decisions WHERE rr_number = ?", (rr_number,)
            ).fetchone()
        return dict(row) if row else {}

    def save(
        self,
        rr_number: str,
        changes: dict[str, Any],
        *,
        domain: str = "",
        tool_class: str = "",
        user: str | None = None,
    ) -> dict[str, Any]:
        """Apply ``changes`` to one RR's decision row, creating it if needed.

        ``tool_class`` is stamped as ``class_when_decided`` whenever a judgement
        is recorded (applies / reviewed). That is what lets the app say "the tool
        changed its mind since you reviewed this" instead of silently keeping a
        decision that was made about a different classification — the failure
        that left two RRs offering a story while claiming no calculation impact.
        """
        unknown = set(changes) - set(EDITABLE)
        if unknown:
            raise ValueError(f"not PM-editable: {sorted(unknown)}")

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        who = user or current_user()
        existing = self.get(rr_number)
        row = {
            "rr_number": rr_number,
            "domain": domain or existing.get("domain", ""),
            "applies": existing.get("applies", ""),
            "reviewed": int(existing.get("reviewed", 0)),
            "reviewed_by": existing.get("reviewed_by", ""),
            "reviewed_at": existing.get("reviewed_at", ""),
            "initiative_validated": existing.get("initiative_validated", ""),
            "related_rr": existing.get("related_rr", ""),
            "jira_key": existing.get("jira_key", ""),
            "note": existing.get("note", ""),
            "class_when_decided": existing.get("class_when_decided", ""),
            "updated_at": now,
        }
        for key, value in changes.items():
            row[key] = int(bool(value)) if key == "reviewed" else ("" if value is None else str(value))

        judged = "applies" in changes or "reviewed" in changes
        if judged:
            row["class_when_decided"] = tool_class
            # Attribution follows the review flag: ticking it claims the review,
            # unticking it releases the claim rather than leaving a stale name.
            if row["reviewed"]:
                row["reviewed_by"], row["reviewed_at"] = who, now
            else:
                row["reviewed_by"], row["reviewed_at"] = "", ""

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO decisions (rr_number, domain, applies, reviewed, reviewed_by,
                    reviewed_at, initiative_validated, related_rr, jira_key, note,
                    class_when_decided, updated_at)
                VALUES (:rr_number, :domain, :applies, :reviewed, :reviewed_by,
                    :reviewed_at, :initiative_validated, :related_rr, :jira_key, :note,
                    :class_when_decided, :updated_at)
                ON CONFLICT(rr_number) DO UPDATE SET
                    domain=excluded.domain, applies=excluded.applies,
                    reviewed=excluded.reviewed, reviewed_by=excluded.reviewed_by,
                    reviewed_at=excluded.reviewed_at,
                    initiative_validated=excluded.initiative_validated,
                    related_rr=excluded.related_rr, jira_key=excluded.jira_key,
                    note=excluded.note, class_when_decided=excluded.class_when_decided,
                    updated_at=excluded.updated_at
                """,
                row,
            )
        return row


    # ----------------------------------------------------------------
    # Initiative catalog: the curated list behind the validated dropdown.
    # The same initiative reaches us under different names depending on which
    # CUF/SUF slide or footnote it came from ("Releasing Fall 2026" vs "2026
    # Settlements Fall Bundle"), which is what made RRs impossible to group. A
    # PM picks the official name from here; retired names stay in the table
    # (inactive) so an RR decided under an old label still resolves.
    # ----------------------------------------------------------------

    def initiatives(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM initiatives"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY name"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql).fetchall()]

    def add_initiative(self, name: str, *, note: str = "", user: str | None = None) -> bool:
        """Add a name to the catalog. False if it was already there (any state)."""
        name = (name or "").strip()
        if not name:
            raise ValueError("an initiative needs a name")
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT active FROM initiatives WHERE name = ?", (name,)
            ).fetchone()
            if existing:
                # Re-adding a retired name revives it rather than erroring.
                if not existing["active"]:
                    conn.execute("UPDATE initiatives SET active = 1 WHERE name = ?", (name,))
                    return True
                return False
            conn.execute(
                "INSERT INTO initiatives (name, active, note, added_by, added_at) VALUES (?, 1, ?, ?, ?)",
                (name, note, user or current_user(),
                 datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
        return True

    def set_initiative_active(self, name: str, active: bool) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE initiatives SET active = ? WHERE name = ?", (int(active), name))

    def initiative_usage(self) -> dict[str, int]:
        """How many RRs each catalog name is validated against."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT initiative_validated AS n, COUNT(*) AS c FROM decisions "
                "WHERE initiative_validated <> '' GROUP BY initiative_validated"
            ).fetchall()
        return {r["n"]: r["c"] for r in rows}


def stale_decision(decision: dict[str, Any], tool_class: str) -> bool:
    """True when the tool reclassified an RR after someone judged it.

    Not an error: the PM may well decide the same thing again. It only means the
    row must say so instead of presenting an old judgement as current.
    """
    if not decision:
        return False
    if not (decision.get("applies") or decision.get("reviewed")):
        return False
    stamped = decision.get("class_when_decided", "")
    return bool(stamped) and stamped != tool_class
