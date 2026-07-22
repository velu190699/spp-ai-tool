"""Assemble the summarization prompt, call the engine, validate the result.

Ingestion (local_source) and rendering (html_renderer) surround this module.
Here we turn extracted document text + relevant RRs into the instruction and
context strings the engine consumes, then normalize its JSON into `ReportData`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.summaries.report_engine import ReportEngine
from src.summaries.report_model import AREA_ORDER, ReportData

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentText:
    kind: str  # "CUF" or "SUF"
    filename: str
    sharepoint_url: str
    text: str
    readable: bool = True


_AREA_LIST = "\n".join(f"- {name} (key: {key})" for key, name in AREA_ORDER)

# Fallback hints if the routing YAML is missing/unreadable. The YAML
# (config/area_routing.yaml) is authoritative — it carries the SME-corrected
# topic lists; this fallback keeps the report running, nothing more.
_FALLBACK_HINTS = """
Area routing hints:
- RTO Markets: FO (bilateral settlements, services, ISO Communication tasks), BO (settlements, charge codes, billing determinants), bidding, Markets+, RTOE.
- Asset Operations: CROW, resource adequacy, generation, outage management.
- Transmissions: transmission scheduling, WebCheckout, OASIS, TPO, e-tag, EDAM/M+ BA.
- ETRM: e-tag/transmission data, deal calcs, bilateral settlements (data, no ISO Communication tasks).
- Optimization: DART Trader, GenTrader, battery, forecasting."""


def build_area_guide(routing_file: Path | None = None) -> str:
    """Compose the area list + routing hints for the summarization prompt.

    Hints come from the SME-editable routing YAML so corrections (e.g. "WEIS
    wind-down is settlements, not ETRM") land without touching code. Any
    problem reading the file degrades to the static fallback with a warning —
    a bad edit to the YAML must not take the weekly report down.
    """
    if routing_file and routing_file.exists():
        try:
            raw = yaml.safe_load(routing_file.read_text(encoding="utf-8")) or {}
            lines = ["", "Area routing hints:"]
            for key, name in AREA_ORDER:
                area = (raw.get("areas") or {}).get(key) or {}
                topics = "; ".join(str(t) for t in area.get("topics", []))
                if topics:
                    lines.append(f"- {area.get('name', name)}: {topics}.")
            rules = [str(r) for r in raw.get("rules", [])]
            if rules:
                lines.append("")
                lines.append("Routing rules (override the hints above):")
                lines.extend(f"- {rule}" for rule in rules)
            return _AREA_LIST + "\n" + "\n".join(lines)
        except (yaml.YAMLError, OSError) as exc:
            LOGGER.warning("Could not read area routing file %s (%s); using fallback hints", routing_file, exc)
    return _AREA_LIST + _FALLBACK_HINTS


_SCHEMA = """{
  "meta": {
    "cuf_date": "e.g. June 18, 2026",
    "suf_date": "e.g. April 9, 2026",
    "sources_line": "short line, e.g. 'CUF Jun 18, 2026 · SUF Apr 9, 2026'",
    "files_read": ["file name", ...],
    "files_skipped": [{"name": "file name", "reason": "why it was not read"}]
  },
  "areas": [
    {
      "key": "one of: rto_markets | asset_operations | transmissions | etrm | optimization",
      "summary": "tight card blurb for the skim view (1-2 sentences, NO impact flags)",
      "items": [
        {
          "tag": "short chip, e.g. 'CUF · 6/18' or 'SUF · 4/9'",
          "title": "item title",
          "detail": "1-3 sentence description",
          "dates": [{"label": "e.g. Production", "value": "e.g. 7/28/2026"}],
          "sources": [{"label": "Document name, p.XX", "url": "SharePoint URL for that document"}]
        }
      ]
    }
  ],
  "timeline": [{"date": "e.g. Jul 28, 2026", "label": "what happens", "past": true_or_false}],
  "narrative": [
    {
      "heading": "section heading",
      "paragraphs": ["paragraph text", ...],
      "impact": "ONLY for near-term concrete PCI action: 'Impactful: <change> -> <PCI module>'. Empty string otherwise.",
      "sources": [{"label": "Document name, p.XX", "url": "SharePoint URL"}]
    }
  ]
}"""


def build_instruction(area_guide: str | None = None) -> str:
    guide = area_guide if area_guide is not None else build_area_guide()
    return f"""You are producing the "SPP Market Changes Summary" report for PCI Energy Solutions
from the CUF and SUF meeting materials provided in the piped input.

Do NOT use any tools. Do NOT read files. Use ONLY the document text provided in the
input. Respond with a SINGLE JSON object and nothing else — no prose, no markdown fences.

The five PCI areas (route every change to one or more; show all five even if empty):
{guide}

The JSON must match this exact schema:
{_SCHEMA}

Rules:
- "areas" powers a by-area routing/skim view (Tab 1). Keep summaries and item details
  tight. Do NOT put "Impactful: ... -> module" flags here.
- "narrative" powers a full top-to-bottom briefing (Tab 2). Include EVERYTHING reported
  this cycle across CUF + SUF, ordered as a briefing reads (RTOE/headline first, then by
  theme) — NOT grouped by area. Only set "impact" for items needing concrete, near-term
  PCI action; leave multi-year/directional items with an empty impact. Do not flag almost
  everything — the flag must mean something.
- "timeline" is a single chronological list, past vs upcoming, with NO area labels.
- Citations: every source label is "Document name, p.XX" and its url is the SharePoint URL
  given for that document in the input. If an item appears in both CUF and SUF, cite both.
- Never invent content for a document you were not given text for. List every file you used
  in meta.files_read and every file you could not read in meta.files_skipped with a reason.
- Do not decode calculations or charge codes; name and cite the RRs in play. Do not include
  SUF dispute/inquiry metrics."""


def build_context(
    *,
    cuf_label: str,
    suf_label: str,
    documents: list[DocumentText],
    relevant_rrs: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append(f"LATEST CUF EDITION: {cuf_label}")
    lines.append(f"LATEST SUF EDITION: {suf_label}")
    lines.append("")

    if relevant_rrs:
        lines.append("RELEVANT OPEN RRs (mentioned in CUF/SUF and Open in the RR Master List):")
        for rr in relevant_rrs:
            dates = ", ".join(rr.get("dates", [])) or "n/a"
            lines.append(
                f"- RR{rr['rr_number']}: {rr.get('title', '')} "
                f"[{rr.get('status', '')}; group: {rr.get('primary_working_group', '')}] "
                f"dates: {dates} | link: {rr.get('search_url', '')}"
            )
        lines.append("")

    unreadable = [d for d in documents if not d.readable or not d.text.strip()]
    if unreadable:
        lines.append("FILES PRESENT BUT NOT READABLE (no text layer) — do NOT invent their content:")
        for doc in unreadable:
            lines.append(f"- [{doc.kind}] {doc.filename}")
        lines.append("")

    lines.append("=== DOCUMENT TEXT ===")
    for doc in documents:
        if not doc.readable or not doc.text.strip():
            continue
        lines.append("")
        lines.append(f"----- [{doc.kind}] {doc.filename} -----")
        lines.append(f"SharePoint URL: {doc.sharepoint_url}")
        lines.append(doc.text)
    return "\n".join(lines)


def build_report(
    *,
    engine: ReportEngine,
    cuf_label: str,
    suf_label: str,
    documents: list[DocumentText],
    relevant_rrs: list[dict[str, Any]],
    generated: str,
    cuf_url: str = "",
    suf_url: str = "",
    routing_file: Path | None = None,
) -> ReportData:
    instruction = build_instruction(build_area_guide(routing_file))
    context = build_context(
        cuf_label=cuf_label,
        suf_label=suf_label,
        documents=documents,
        relevant_rrs=relevant_rrs,
    )
    LOGGER.info("Summarizing %d documents (context %d chars)", len(documents), len(context))
    raw = engine.generate(instruction, context)
    if not isinstance(raw, dict):
        raise TypeError(f"Engine returned {type(raw).__name__}, expected dict")
    # Stamp the generated time from the caller (engines don't set it).
    meta = raw.setdefault("meta", {})
    if not meta.get("generated"):
        meta["generated"] = generated
    if not meta.get("cuf_date"):
        meta["cuf_date"] = cuf_label
    if not meta.get("suf_date"):
        meta["suf_date"] = suf_label
    # Edition links are resolved deterministically from the local files, not the
    # engine — always authoritative, so overwrite any engine-supplied value.
    meta["cuf_url"] = cuf_url
    meta["suf_url"] = suf_url
    LOGGER.debug("Engine payload: %s", json.dumps(raw)[:2000])
    return ReportData.from_dict(raw)
