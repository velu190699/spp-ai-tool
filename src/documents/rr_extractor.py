from __future__ import annotations

import re
from dataclasses import dataclass, field


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
    return merged
