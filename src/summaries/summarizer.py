from __future__ import annotations

from datetime import datetime
from typing import Any


def build_run_summary(
    *,
    run_id: str,
    dry_run: bool,
    discovered: dict[str, Any],
    relevant_rrs: list[dict[str, Any]],
    warnings: list[str],
    skipped: list[str],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "summary_mode": "structured-extraction-only",
        "discovered_documents": discovered,
        "relevant_rrs": relevant_rrs,
        "warnings": warnings,
        "skipped": skipped,
        "pending": {
            "sharepoint": "Real Microsoft Graph upload is pending.",
            "stakeholders": "PCI stakeholder routing is pending.",
            "slack": "Real Slack delivery is pending.",
        },
    }
