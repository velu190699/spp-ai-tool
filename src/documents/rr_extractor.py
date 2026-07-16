from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


RR_PATTERN = re.compile(r"\bRR\s*-?\s*0*(\d{1,5})\b", re.IGNORECASE)
ACTION_ITEM_ROW_PATTERN = re.compile(r"(?m)^(\d{3,5})\s+\d{1,2}/\d{1,2}/\d{2,4}")
DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{8}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)


@dataclass
class RRMention:
    rr_number: str
    context: str
    dates: list[str] = field(default_factory=list)
    source: str = ""
    page: int = 0


def normalize_rr_number(value: object) -> str:
    # Normalize variants such as RR782, RR 782, RR-0782, and Excel value 0782
    # to the same numeric key so PDF mentions intersect cleanly with the master list.
    text = str(value or "").strip()
    match = re.search(r"(\d{1,5})", text)
    if not match:
        return ""
    return str(int(match.group(1)))


def display_rr(rr_number: str) -> str:
    return f"RR{normalize_rr_number(rr_number)}"


def extract_dates(text: str) -> list[str]:
    seen = set()
    dates: list[str] = []
    for match in DATE_PATTERN.finditer(text):
        value = match.group(0)
        if value not in seen:
            seen.add(value)
            dates.append(value)
    return dates


def extract_rr_mentions(text: str, *, source: str = "", page: int = 0, context_chars: int = 240) -> list[RRMention]:
    # Dates are associated by local context, not by global document date. This
    # keeps unrelated meeting dates from being attached to every RR in the PDF.
    mentions: list[RRMention] = []
    seen = set()
    for match in RR_PATTERN.finditer(text):
        rr_number = normalize_rr_number(match.group(1))
        start = max(0, match.start() - context_chars)
        end = min(len(text), match.end() + context_chars)
        context = " ".join(text[start:end].split())
        key = (rr_number, context, source)
        if key in seen:
            continue
        seen.add(key)
        mentions.append(RRMention(rr_number=rr_number, context=context, dates=extract_dates(context), source=source, page=page))
    return mentions


def extract_action_item_rrs(text: str, *, source: str = "", page: int = 0, context_chars: int = 240) -> list[RRMention]:
    mentions: list[RRMention] = []
    seen: set[tuple[str, str]] = set()
    for match in ACTION_ITEM_ROW_PATTERN.finditer(text):
        rr_number = normalize_rr_number(match.group(1))
        start = max(0, match.start() - context_chars)
        end = min(len(text), match.end() + context_chars)
        context = " ".join(text[start:end].split())
        key = (rr_number, source)
        if key in seen:
            continue
        seen.add(key)
        mentions.append(RRMention(rr_number=rr_number, context=context, dates=extract_dates(context), source=source, page=page))
    return mentions


# How SPP actually names an initiative near an RR mention (observed in real
# CUF/SUF decks, July 2026): "2026 Settlements Fall Bundle", "Integrated
# Marketplace release in Fall 2026", "HITT M2 effort" — plus PCI's own
# "Fall 2026 Market Initiative" form in case a deck uses it. Season+year (or a
# HITT code) is required: a bare "release" identifies nothing.
_INITIATIVE_PATTERNS = [
    re.compile(r"\b(Spring|Summer|Fall|Winter)\s+(20\d{2})\s+(?:SPP\s+)?Market\s+Initiative\b", re.IGNORECASE),
    re.compile(r"\b(Spring|Summer|Fall|Winter)\s+(?:SPP\s+)?Market\s+Initiative\s+(20\d{2})\b", re.IGNORECASE),
    re.compile(r"\b(20\d{2})\s+(Spring|Summer|Fall|Winter)\s+(?:SPP\s+)?Market\s+Initiative\b", re.IGNORECASE),
]
# Seasonal release/bundle phrasing, e.g. "2026 Settlements Fall Bundle",
# "release in Fall 2026", "Fall 2026 release".
_RELEASE_PATTERNS = [
    re.compile(r"\b(20\d{2})\s+(?:\w+\s+)?(Spring|Summer|Fall|Winter)\s+Bundle\b", re.IGNORECASE),
    re.compile(r"\brelease\s+in\s+(Spring|Summer|Fall|Winter)\s+(20\d{2})\b", re.IGNORECASE),
    re.compile(r"\b(Spring|Summer|Fall|Winter)\s+(20\d{2})\s+release\b", re.IGNORECASE),
]
# SPP HITT effort codes, e.g. "HITT C1", "HITT M2".
_HITT_PATTERN = re.compile(r"\bHITT\s+([A-Z]\d+)\b")


# For "2026 Settlements Fall Bundle"-style phrasing, widen the verbatim label
# to the whole capitalized phrase around the season, not just "2026 ... Bundle".
_BUNDLE_VERBATIM = re.compile(
    r"\b(20\d{2}\s+(?:[A-Z][A-Za-z]+\s+)?(?:Spring|Summer|Fall|Winter)\s+Bundle)\b"
)


def initiative_from_contexts(
    contexts: list[object] | None,
    sources: list[object] | None = None,
) -> tuple[str, str]:
    """Name the market initiative an RR belongs to, VERBATIM, with its citation.

    The initiative is announced on the CUF/SUF slide near the RR mention, not
    inside the RR document itself — so this reads the captured context windows.
    Returns ``(label, citation)`` where ``label`` is the slide's own wording
    (e.g. "2026 Settlements Fall Bundle", "release in Fall 2026", "HITT C1" —
    no normalization, so it can be checked against the slide directly) and
    ``citation`` is the source file/page of the mention(s) that named it, when
    ``sources`` (parallel to ``contexts``) is provided. Preference order:
    explicit "<Season> <Year> Market Initiative" > seasonal release/bundle
    phrasing > HITT effort code. ``("", "")`` when nothing identifiable.
    """
    # label -> (rank, count, citations); lower rank wins, then higher count.
    found: dict[str, list[Any]] = {}

    def _hit(label: str, rank: int, source: str) -> None:
        entry = found.setdefault(label, [rank, 0, []])
        entry[1] += 1
        if source and source not in entry[2]:
            entry[2].append(source)

    source_list = [str(s) for s in (sources or [])]
    for pos, text in enumerate(contexts or []):
        text = str(text)
        source = source_list[pos] if pos < len(source_list) else ""
        for pattern in _INITIATIVE_PATTERNS:
            for match in pattern.finditer(text):
                _hit(match.group(0).strip(), 0, source)
        for pattern in _RELEASE_PATTERNS:
            for match in pattern.finditer(text):
                wide = _BUNDLE_VERBATIM.search(text)
                _hit((wide.group(1) if wide else match.group(0)).strip(), 1, source)
        for match in _HITT_PATTERN.finditer(text):
            _hit(match.group(0).strip(), 2, source)

    if not found:
        return "", ""
    label = min(found, key=lambda k: (found[k][0], -found[k][1]))
    citations = found[label][2]
    return label, "; ".join(citations[:2])


def merge_mentions(mentions: list[RRMention]) -> dict[str, dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for mention in mentions:
        entry = merged.setdefault(
            mention.rr_number,
            {"rr_number": mention.rr_number, "dates": [], "sources": [], "contexts": []},
        )
        for date in mention.dates:
            if date not in entry["dates"]:
                entry["dates"].append(date)
        source_label = f"{mention.source}:p{mention.page}" if mention.source and mention.page else mention.source
        if source_label and source_label not in entry["sources"]:
            entry["sources"].append(source_label)
        if mention.context and mention.context not in entry["contexts"]:
            entry["contexts"].append(mention.context)
            # Parallel to "contexts": which file/page each context came from,
            # so downstream facts (e.g. the initiative label) stay citable.
            entry.setdefault("context_sources", []).append(source_label)
    return merged
