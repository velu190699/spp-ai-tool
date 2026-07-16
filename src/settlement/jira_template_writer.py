"""jira_template_writer.py — fill Miquel's Jira_Story_Creator_template.xlsx.

Technical: loads a COPY of the team's story-creator template (v1.1.0) and
writes Epic/Story rows into the "Jira Stories" sheet. The template's contract:
header row starts with "Create?"; amber columns (Create? .. Acceptance
Criteria) are authored here; green columns (Jira Key, Sync Status, Sync
Timestamp, Sync Error) belong to Miquel's sync app and are NEVER written. The
shipped example rows below the header are replaced with ours.

Business: this is the PM-review artifact — the tool proposes stories, the PM
edits and flips "Create?" to Y, and only then does the sync app create Jira
issues. Every row therefore defaults Create? to blank: the tool must not be
able to push a story into Jira on its own. The epic's Parent Link (initiative
key, e.g. PM-944) is also left blank for the PM.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

LOGGER = logging.getLogger(__name__)

STORIES_SHEET = "Jira Stories"
TESTS_SHEET = "Tests"
SUMMARY_PREFIX = "[SPPIM: Back Office: Settlements]"

# Header text -> StoryRow attribute. Green columns are deliberately absent.
_FIELD_BY_HEADER = {
    "Create?": "create",
    "Issue Type": "issue_type",
    "Local ID": "local_id",
    "Summary": "summary",
    "Description": "description",
    "Steps to Reproduce": "steps_to_reproduce",
    "Client Ticket": "client_ticket",
    "Epic": "epic",
    "Epic Name": "epic_name",
    "Parent Link": "parent_link",
    "Complete After": "complete_after",
    "Priority": "priority",
    "Acceptance Criteria": "acceptance_criteria",
}

# The team's standing acceptance-criteria items (as seen in SP-12813/SP-12814);
# story-specific criteria from the LLM are prepended to these.
BOILERPLATE_AC = (
    "# DST dates have been impact tested (if applicable)\n"
    "# Changes of scope, decision points, newly identified details, etc. have been documented in the story.\n"
    "# Release Documentation is detailed and accurate. For large and/or significant changes, "
    "ensure Product Manager and/or SME has reviewed."
)


@dataclass
class StoryRow:
    issue_type: str = "Story"
    summary: str = ""
    description: str = ""
    acceptance_criteria: str = ""
    local_id: str = ""
    epic: str = ""
    epic_name: str = ""
    parent_link: str = ""
    priority: str = "Medium"
    steps_to_reproduce: str = ""
    client_ticket: str = ""
    complete_after: str = ""
    create: str = ""  # blank: the PM flips to Y after review — never pre-filled


def _find_header_row(ws) -> int:
    for row in range(1, min(ws.max_row, 30) + 1):
        if str(ws.cell(row=row, column=1).value or "").strip() == "Create?":
            return row
    raise ValueError(
        f"Sheet '{ws.title}' has no 'Create?' header row — template layout changed; "
        "update jira_template_writer.py against the new template version"
    )


def write_story_workbook(template_path: Path, out_path: Path, rows: list[StoryRow]) -> Path:
    """Fill a copy of the template with `rows` and save it to `out_path`.

    The template file itself is never modified. Formatting, data validation,
    the Tests sheet's banner/header, and the green sync columns are preserved
    untouched so Miquel's app sees exactly the workbook shape it expects. The
    Tests sheet's shipped EXAMPLE rows are removed — we don't author tests, so
    the tab ships blank below its header (Elizabeth/Eduardo, 2026-07-16).
    """
    wb = load_workbook(template_path)
    if STORIES_SHEET not in wb.sheetnames:
        raise ValueError(f"Template has no '{STORIES_SHEET}' sheet (found: {wb.sheetnames})")
    if TESTS_SHEET in wb.sheetnames:
        tests = wb[TESTS_SHEET]
        tests_header = _find_header_row(tests)
        if tests.max_row > tests_header:
            tests.delete_rows(tests_header + 1, tests.max_row - tests_header)
    ws = wb[STORIES_SHEET]
    header_row = _find_header_row(ws)
    columns = {
        str(ws.cell(row=header_row, column=col).value or "").strip(): col
        for col in range(1, ws.max_column + 1)
    }
    missing = [h for h in _FIELD_BY_HEADER if h not in columns]
    if missing:
        raise ValueError(f"Template is missing expected columns: {missing} — layout changed?")

    # Replace the shipped EXAMPLE rows ("Rows 5+ are EXAMPLES") with ours.
    if ws.max_row > header_row:
        ws.delete_rows(header_row + 1, ws.max_row - header_row)

    for offset, story in enumerate(rows, start=1):
        row = header_row + offset
        for header, attr in _FIELD_BY_HEADER.items():
            value = getattr(story, attr)
            ws.cell(row=row, column=columns[header], value=value or None)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    LOGGER.info("Jira story workbook written: %s (%d rows)", out_path, len(rows))
    return out_path


def _rr_footer(rr: str, url: str, initiative: str, initiative_citation: str = "", protocol_version: str = "") -> str:
    lines = ["", "", f"Recommendation Report: {rr} Recommendation Report.docx"]
    if url:
        lines.append(f"SharePoint: {url}")
    if protocol_version:
        lines.append(f"Market Protocols (Settlement User Guide) version: {protocol_version}")
    if initiative:
        # Verbatim slide wording + its file/page so the claim is checkable.
        cite = f" [{initiative_citation}]" if initiative_citation else ""
        lines.append(f"Market initiative (as named on the slide): {initiative}{cite}")
    return "\n".join(lines)


def _normalize_ac_item(item: Any) -> str:
    # Strip only a leading "# " list marker — a bare "#" may be a charge-code
    # prefix (e.g. "#SsrMnthlyDistAoAmt") and must survive.
    text = str(item).strip()
    return text[2:].strip() if text.startswith("# ") else text


def _format_ac(items: Any) -> str:
    specific = ""
    if isinstance(items, list) and items:
        specific = "\n".join(f"# {_normalize_ac_item(item)}" for item in items) + "\n"
    return specific + BOILERPLATE_AC


def _prefixed(summary: str) -> str:
    return summary if summary.startswith("[") else f"{SUMMARY_PREFIX} {summary}"


def stories_from_results(results: list[dict[str, Any]]) -> list[StoryRow]:
    """Turn settlement-pipeline results into template rows.

    NO epic row is generated and the Epic column is left blank on every story:
    per-RR workbooks with embedded epics would create duplicate epics in Jira,
    so the PM fills the Epic column with the real epic key (or local ID) during
    review. Granularity within an RR: one Story per charge entry / LLM story.
    LLM-generated stories (SETTLEMENT_CALC + PASS with --call-claude) carry
    their own description/AC; without the LLM a deterministic draft row is
    emitted so the PM still sees the change, marked as needing the full pass.
    SETTLEMENT_CALC + HARD_FAIL and SETTLEMENT_RELEVANT become single review
    Tasks; TARIFF_GOVERNANCE is out of scope and emits nothing.
    """
    story_rows: list[StoryRow] = []
    for res in results:
        d = res["report"]
        cls = d["rr_class"]
        status = d["reconciliation"]["status"]
        rr = d.get("rr_id", "?")
        url = d.get("sharepoint_url") or ""
        footer = _rr_footer(
            rr,
            url,
            d.get("market_initiative", ""),
            d.get("market_initiative_citation", ""),
            d.get("protocol_version", ""),
        )
        llm = res.get("stories") if isinstance(res.get("stories"), dict) else None
        llm_stories = (llm or {}).get("jira_stories") or []

        if cls == "SETTLEMENT_CALC" and status in ("PASS", "PASS_NUMBERING_MAPPED"):
            if llm_stories:
                for s in llm_stories:
                    story_rows.append(StoryRow(
                        summary=_prefixed(str(s.get("summary", ""))),
                        description=str(s.get("description", "")) + footer,
                        acceptance_criteria=_format_ac(s.get("acceptance_criteria")),
                    ))
            else:
                for entry in (i for i in d["charge_type_index"] if i["banner"].startswith("Market")):
                    st = "ADDED" if entry["is_new"] else "MODIFIED"
                    story_rows.append(StoryRow(
                        summary=_prefixed(f"{rr} — §{entry['section']} {entry['title']} ({st.title()})"),
                        description=(
                            f"As a user, I want the SPPIM settlements calculation updated per {rr} "
                            f"Market Protocols §{entry['section']} {entry['title']} ({st}).\n\n"
                            f"Source: {rr} Recommendation Report, p.{entry.get('page', '?')}."
                            f"{footer}\n\n"
                            "DRAFT: generated without LLM story extraction — run "
                            "`settlement-report --call-claude` for full descriptions before PM review."
                        ),
                        acceptance_criteria=_format_ac(None),
                    ))
        elif cls == "SETTLEMENT_CALC":  # HARD_FAIL: extraction couldn't be reconciled
            story_rows.append(StoryRow(
                issue_type="Task",
                summary=_prefixed(f"{rr} — MANUAL REVIEW: charge-code extraction failed reconciliation"),
                description=(
                    f"The automated extraction for {rr} failed its reconciliation gate "
                    f"(status: {status}). A settlements SME must review the RR directly; "
                    "do not trust auto-generated charge-code rows for this RR."
                    f"{footer}"
                ),
                acceptance_criteria=_format_ac(["RR reviewed by settlements SME and stories authored manually"]),
            ))
        elif cls == "SETTLEMENT_RELEVANT":
            story_rows.append(StoryRow(
                issue_type="Task",
                summary=_prefixed(f"{rr} — review settlement impact (prose change, no charge-code redlines)"),
                description=(
                    f"{rr} changes settlement-relevant Tariff/Protocol prose without charge-code "
                    "redlines. Review whether PCI settlement logic or documentation is affected."
                    f"{footer}"
                ),
                acceptance_criteria=_format_ac(["Impact assessed and documented; follow-up stories created if needed"]),
            ))
        # TARIFF_GOVERNANCE: informational only — no story (Kashmita's scope rule).

    return story_rows
