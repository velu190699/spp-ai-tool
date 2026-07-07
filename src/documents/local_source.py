"""Read the latest CUF/SUF materials from a locally synced SharePoint folder.

The report stage does not download from spp.org; it reads the copies that the
Market Systems team already keeps in a synced SharePoint library, and builds
citation URLs by mapping each local path back to its web address.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

LOGGER = logging.getLogger(__name__)

# Folder/file names embed dates as YYYYMMDD, e.g.
# "CUF Meeting Materials 20260618_20260612" (meeting date first, publish second)
# "SUF Meeting Materials 20260409_20260402.pdf"
_DATE8 = re.compile(r"(\d{8})")


@dataclass(frozen=True)
class SourceFile:
    local_path: Path
    sharepoint_url: str
    filename: str


@dataclass(frozen=True)
class SourceEdition:
    kind: str  # "CUF" or "SUF"
    label: str  # the folder/file name that identifies the edition
    meeting_date: datetime | None
    files: list[SourceFile] = field(default_factory=list)

    @property
    def meeting_date_label(self) -> str:
        return self.meeting_date.strftime("%B %d, %Y") if self.meeting_date else "unknown date"


def meeting_date_from_name(name: str) -> datetime | None:
    """The meeting date is the first YYYYMMDD token in the name, if any."""
    match = _DATE8.search(name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d")
    except ValueError:
        return None


def to_sharepoint_url(local_path: Path, sync_root: Path, base_url: str) -> str:
    """Map a local synced path to its SharePoint web URL.

    The path relative to sync_root is appended to base_url, with each segment
    URL-encoded (spaces become %20) so the link is valid and clickable.
    """
    if not base_url:
        return ""
    try:
        relative = local_path.resolve().relative_to(sync_root.resolve())
    except ValueError:
        LOGGER.warning("Path %s is not under sync_root %s; citation URL unavailable", local_path, sync_root)
        return ""
    encoded = "/".join(quote(part) for part in relative.parts)
    return f"{base_url}/{encoded}"


def _files_in(folder: Path, sync_root: Path, base_url: str) -> list[SourceFile]:
    files = [p for p in sorted(folder.rglob("*")) if p.is_file()]
    return [
        SourceFile(local_path=p, sharepoint_url=to_sharepoint_url(p, sync_root, base_url), filename=p.name)
        for p in files
    ]


def latest_cuf_edition(cuf_dir: Path, sync_root: Path, base_url: str) -> SourceEdition | None:
    """The newest CUF meeting subfolder, with all its files enumerated."""
    if not cuf_dir.exists():
        LOGGER.warning("CUF directory does not exist: %s", cuf_dir)
        return None
    subfolders = [p for p in cuf_dir.iterdir() if p.is_dir()]
    if not subfolders:
        LOGGER.warning("No CUF meeting subfolders under %s", cuf_dir)
        return None
    latest = max(subfolders, key=lambda p: (meeting_date_from_name(p.name) or datetime.min, p.name))
    return SourceEdition(
        kind="CUF",
        label=latest.name,
        meeting_date=meeting_date_from_name(latest.name),
        files=_files_in(latest, sync_root, base_url),
    )


def latest_suf_edition(suf_dir: Path, sync_root: Path, base_url: str) -> SourceEdition | None:
    """The newest SUF PDF (SUF materials sit directly in the folder as files)."""
    if not suf_dir.exists():
        LOGGER.warning("SUF directory does not exist: %s", suf_dir)
        return None
    pdfs = [p for p in suf_dir.glob("*.pdf") if p.is_file()]
    if not pdfs:
        LOGGER.warning("No SUF PDFs under %s", suf_dir)
        return None
    latest = max(pdfs, key=lambda p: (meeting_date_from_name(p.name) or datetime.min, p.name))
    return SourceEdition(
        kind="SUF",
        label=latest.name,
        meeting_date=meeting_date_from_name(latest.name),
        files=[
            SourceFile(
                local_path=latest,
                sharepoint_url=to_sharepoint_url(latest, sync_root, base_url),
                filename=latest.name,
            )
        ],
    )
