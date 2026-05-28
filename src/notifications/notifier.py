from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


def format_slack_draft(relevant_rrs: list[dict[str, Any]], warnings: list[str]) -> str:
    lines = ["SPP RR automation draft notification", ""]
    if not relevant_rrs:
        lines.append("No relevant open RRs were identified in the latest CUF/SUF materials.")
    else:
        lines.append("Relevant open RRs identified:")
        for rr in relevant_rrs:
            dates = ", ".join(rr.get("dates", [])) or "No nearby dates found"
            title = rr.get("title") or "(no title)"
            sources = ", ".join(rr.get("sources", [])) or "unknown source"
            lines.append(f"- RR{rr['rr_number']}: {title} | dates: {dates} | sources: {sources}")
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend(["", "Slack delivery and stakeholder routing are pending in v1."])
    return "\n".join(lines)


def log_slack_draft(relevant_rrs: list[dict[str, Any]], warnings: list[str]) -> str:
    draft = format_slack_draft(relevant_rrs, warnings)
    LOGGER.info("Slack draft notification:\n%s", draft)
    return draft
