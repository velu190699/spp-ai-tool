"""The data contract for the SPP Market Changes Summary report.

The summarization engine (Claude Code headless, or the stub) must produce a JSON
object matching this shape. `report_from_dict` validates and normalizes it into
typed objects that the HTML renderer consumes. Keeping the contract here means
the engine and the renderer never drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The five PCI areas, in display order. The engine must route every change to
# one or more of these keys; the renderer supplies the colors.
AREA_ORDER: list[tuple[str, str]] = [
    ("rto_markets", "RTO Markets"),
    ("asset_operations", "Asset Operations"),
    ("transmissions", "Transmissions"),
    ("etrm", "ETRM"),
    ("optimization", "Optimization"),
]
AREA_KEYS = [key for key, _ in AREA_ORDER]
AREA_NAMES = dict(AREA_ORDER)

# Per-area accent colors, shared by the HTML report (CSS --c-* vars) and the
# Slack briefing (attachment color bars) so the two stay visually consistent.
AREA_COLORS: dict[str, str] = {
    "rto_markets": "#1f4e8c",      # blue
    "asset_operations": "#1f7a4d",  # green
    "transmissions": "#b4630a",     # amber
    "etrm": "#6b3fa0",              # purple
    "optimization": "#0f7c86",      # teal
}


class ReportValidationError(ValueError):
    """Raised when engine output does not match the report contract."""


@dataclass(frozen=True)
class Source:
    label: str
    url: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Source":
        return cls(label=str(raw.get("label", "")).strip(), url=str(raw.get("url", "")).strip())


@dataclass(frozen=True)
class AreaItem:
    tag: str  # short provenance chip, e.g. "CUF · 6/18"
    title: str
    detail: str
    dates: list[dict[str, str]] = field(default_factory=list)  # [{label, value}]
    sources: list[Source] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AreaItem":
        return cls(
            tag=str(raw.get("tag", "")).strip(),
            title=str(raw.get("title", "")).strip(),
            detail=str(raw.get("detail", "")).strip(),
            dates=[{"label": str(d.get("label", "")), "value": str(d.get("value", ""))} for d in raw.get("dates", [])],
            sources=[Source.from_dict(s) for s in raw.get("sources", [])],
        )


@dataclass(frozen=True)
class Area:
    key: str
    name: str
    summary: str  # tight card blurb for the routing/skim view
    items: list[AreaItem] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Area":
        key = str(raw.get("key", "")).strip()
        if key not in AREA_KEYS:
            raise ReportValidationError(f"Unknown area key: {key!r}; expected one of {AREA_KEYS}")
        return cls(
            key=key,
            name=AREA_NAMES[key],
            summary=str(raw.get("summary", "")).strip(),
            items=[AreaItem.from_dict(i) for i in raw.get("items", [])],
        )


@dataclass(frozen=True)
class TimelineEntry:
    date: str
    label: str
    past: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TimelineEntry":
        return cls(
            date=str(raw.get("date", "")).strip(),
            label=str(raw.get("label", "")).strip(),
            past=bool(raw.get("past", False)),
        )


@dataclass(frozen=True)
class NarrativeSection:
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    impact: str = ""  # the one-line "Impactful: <change> → <module>" flag, or empty
    sources: list[Source] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "NarrativeSection":
        return cls(
            heading=str(raw.get("heading", "")).strip(),
            paragraphs=[str(p).strip() for p in raw.get("paragraphs", []) if str(p).strip()],
            impact=str(raw.get("impact", "")).strip(),
            sources=[Source.from_dict(s) for s in raw.get("sources", [])],
        )


@dataclass(frozen=True)
class ReportMeta:
    cuf_date: str = ""
    suf_date: str = ""
    cuf_url: str = ""  # SharePoint link to the CUF meeting folder
    suf_url: str = ""  # SharePoint link to the SUF pdf
    generated: str = ""
    sources_line: str = ""
    files_read: list[str] = field(default_factory=list)
    files_skipped: list[dict[str, str]] = field(default_factory=list)  # [{name, reason}]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ReportMeta":
        return cls(
            cuf_date=str(raw.get("cuf_date", "")).strip(),
            suf_date=str(raw.get("suf_date", "")).strip(),
            cuf_url=str(raw.get("cuf_url", "")).strip(),
            suf_url=str(raw.get("suf_url", "")).strip(),
            generated=str(raw.get("generated", "")).strip(),
            sources_line=str(raw.get("sources_line", "")).strip(),
            files_read=[str(f) for f in raw.get("files_read", [])],
            files_skipped=[{"name": str(f.get("name", "")), "reason": str(f.get("reason", ""))} for f in raw.get("files_skipped", [])],
        )


@dataclass(frozen=True)
class ReportData:
    meta: ReportMeta
    areas: list[Area]
    timeline: list[TimelineEntry]
    narrative: list[NarrativeSection]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ReportData":
        if not isinstance(raw, dict):
            raise ReportValidationError("Report payload must be a JSON object")
        try:
            areas = [Area.from_dict(a) for a in raw.get("areas", [])]
        except ReportValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface a clear contract error
            raise ReportValidationError(f"Malformed 'areas': {exc}") from exc
        return cls(
            meta=ReportMeta.from_dict(raw.get("meta", {})),
            areas=areas,
            timeline=[TimelineEntry.from_dict(t) for t in raw.get("timeline", [])],
            narrative=[NarrativeSection.from_dict(n) for n in raw.get("narrative", [])],
        )
