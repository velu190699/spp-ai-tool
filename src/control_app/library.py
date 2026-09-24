"""What the tool has published, and what it downloaded to produce it.

Two listings the app needs and nobody had: everything published into the synced
SharePoint library (dashboards, briefings, settlement summaries, story
workbooks), and the source materials behind them (CUF/SUF editions,
Recommendation Reports, protocols, the RR master list).

Both are read straight off the synced folder rather than from state, because the
folder is the thing a person actually opens — and because state records only what
this tool wrote, while the library also holds what SPP published.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.documents.local_source import to_sharepoint_url


@dataclass(frozen=True)
class Item:
    name: str
    kind: str
    path: Path
    modified: datetime
    size_kb: int
    url: str

    @property
    def when(self) -> str:
        return self.modified.strftime("%Y-%m-%d %H:%M")


def _item(path: Path, kind: str, config) -> Item:
    stat = path.stat()
    return Item(
        name=path.name,
        kind=kind,
        path=path,
        modified=datetime.fromtimestamp(stat.st_mtime),
        size_kb=max(1, stat.st_size // 1024),
        url=to_sharepoint_url(path, config.sharepoint_sync_root, config.sharepoint_base_url),
    )


def _scan(directory: Path, patterns: tuple[str, ...], kind: str, config) -> list[Item]:
    if not directory.exists():
        return []
    found: list[Item] = []
    for pattern in patterns:
        for path in directory.glob(pattern):
            if path.is_file():
                found.append(_item(path, kind, config))
    return found


def published(config) -> list[Item]:
    """Everything this tool has published, newest first.

    ``RR_Control.html`` (the fixed-name copy) is excluded: it is a duplicate of
    the newest dated dashboard, and listing it as its own entry in a history
    makes the history lie.
    """
    items: list[Item] = []
    items += [
        i for i in _scan(config.published_control_dir, ("RR_Control-*.html",), "Control dashboard", config)
    ]
    items += _scan(config.published_reports_dir, ("SPP_Market_Changes_Summary-*.html",), "Full report", config)
    items += _scan(config.published_settlement_reports_dir, ("*.xlsx",), "Settlement summary", config)
    items += _scan(config.jira_stories_dir, ("RR*_Jira_Stories-*.xlsx",), "Story workbook", config)
    return sorted(items, key=lambda i: i.modified, reverse=True)


def materials(config) -> list[Item]:
    """The source documents the tool downloaded from SPP, newest first."""
    items: list[Item] = []
    items += _scan(config.cuf_dir, ("*.pdf", "*/*.pdf"), "CUF", config)
    items += _scan(config.suf_dir, ("*.pdf", "*/*.pdf"), "SUF", config)
    items += _scan(config.recommendation_reports_dir, ("*/*.docx",), "Recommendation Report", config)
    items += _scan(config.protocols_dir, ("*.pdf", "*/*.pdf", "*.docx", "*/*.docx"), "Protocol", config)
    items += _scan(config.rr_master_list_dir, ("*.xlsx",), "RR Master List", config)
    return sorted(items, key=lambda i: i.modified, reverse=True)


def group_by_kind(items: list[Item]) -> dict[str, list[Item]]:
    grouped: dict[str, list[Item]] = {}
    for item in items:
        grouped.setdefault(item.kind, []).append(item)
    return grouped
