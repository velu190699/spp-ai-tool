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
from urllib.parse import quote, urlsplit

LOGGER = logging.getLogger(__name__)

# SharePoint short-link type letters, keyed by file extension. These pick the
# right in-browser viewer; "b" (PDF/generic) is a safe default for anything else.
_LINK_TYPE_BY_EXT = {
    ".pdf": "b",
    ".doc": "w", ".docx": "w",
    ".xls": "x", ".xlsx": "x", ".xlsm": "x", ".csv": "x",
    ".ppt": "p", ".pptx": "p",
}

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
    url: str = ""  # SharePoint URL for the edition itself (CUF folder / SUF pdf)
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


def to_sharepoint_url(local_path: Path, sync_root: Path, base_url: str, *, is_folder: bool = False) -> str:
    """Map a local synced path to a clickable SharePoint web URL.

    Raw library paths (base_url + relative path) do not reliably resolve — folders
    in particular 404. SharePoint navigates via a short redirect link off the tenant
    root instead: ``https://<host>/:<type>:/r/<server-relative path>?csf=1&web=1``,
    where <type> is ``f`` for a folder or a viewer letter for a file (``b`` PDF,
    ``w`` Word, ``x`` Excel, ``p`` PowerPoint). base_url supplies the host and the
    server-relative base (its path), to which the path relative to sync_root is
    appended. Each segment is URL-encoded (spaces -> %20); slashes stay literal.
    """
    if not base_url:
        return ""
    try:
        relative = local_path.resolve().relative_to(sync_root.resolve())
    except ValueError:
        LOGGER.warning("Path %s is not under sync_root %s; citation URL unavailable", local_path, sync_root)
        return ""
    parsed = urlsplit(base_url)
    host = f"{parsed.scheme}://{parsed.netloc}"
    base_segments = [seg for seg in parsed.path.split("/") if seg]
    segments = base_segments + list(relative.parts)
    server_relative = "/".join(quote(seg) for seg in segments)
    link_type = "f" if is_folder else _LINK_TYPE_BY_EXT.get(local_path.suffix.lower(), "b")
    return f"{host}/:{link_type}:/r/{server_relative}?csf=1&web=1"


def _files_in(folder: Path, sync_root: Path, base_url: str) -> list[SourceFile]:
    files = [p for p in sorted(folder.rglob("*")) if p.is_file()]
    return [
        SourceFile(local_path=p, sharepoint_url=to_sharepoint_url(p, sync_root, base_url), filename=p.name)
        for p in files
    ]


def _cuf_edition(folder: Path, sync_root: Path, base_url: str) -> SourceEdition:
    return SourceEdition(
        kind="CUF",
        label=folder.name,
        meeting_date=meeting_date_from_name(folder.name),
        url=to_sharepoint_url(folder, sync_root, base_url, is_folder=True),
        files=_files_in(folder, sync_root, base_url),
    )


def _suf_edition(pdf: Path, sync_root: Path, base_url: str) -> SourceEdition:
    suf_url = to_sharepoint_url(pdf, sync_root, base_url)
    return SourceEdition(
        kind="SUF",
        label=pdf.name,
        meeting_date=meeting_date_from_name(pdf.name),
        url=suf_url,
        files=[SourceFile(local_path=pdf, sharepoint_url=suf_url, filename=pdf.name)],
    )


def all_cuf_editions(cuf_dir: Path, sync_root: Path, base_url: str) -> list[SourceEdition]:
    """Every CUF meeting subfolder as an edition, sorted oldest -> newest."""
    if not cuf_dir.exists():
        LOGGER.warning("CUF directory does not exist: %s", cuf_dir)
        return []
    editions = [_cuf_edition(p, sync_root, base_url) for p in cuf_dir.iterdir() if p.is_dir()]
    return sorted(editions, key=lambda e: (e.meeting_date or datetime.min, e.label))


def all_suf_editions(suf_dir: Path, sync_root: Path, base_url: str) -> list[SourceEdition]:
    """Every SUF PDF as an edition, sorted oldest -> newest."""
    if not suf_dir.exists():
        LOGGER.warning("SUF directory does not exist: %s", suf_dir)
        return []
    editions = [_suf_edition(p, sync_root, base_url) for p in suf_dir.glob("*.pdf") if p.is_file()]
    return sorted(editions, key=lambda e: (e.meeting_date or datetime.min, e.label))


def latest_cuf_edition(cuf_dir: Path, sync_root: Path, base_url: str) -> SourceEdition | None:
    """The newest CUF meeting subfolder, with all its files enumerated."""
    editions = all_cuf_editions(cuf_dir, sync_root, base_url)
    if not editions:
        LOGGER.warning("No CUF meeting subfolders under %s", cuf_dir)
        return None
    return editions[-1]


def latest_suf_edition(suf_dir: Path, sync_root: Path, base_url: str) -> SourceEdition | None:
    """The newest SUF PDF (SUF materials sit directly in the folder as files)."""
    editions = all_suf_editions(suf_dir, sync_root, base_url)
    if not editions:
        LOGGER.warning("No SUF PDFs under %s", suf_dir)
        return None
    return editions[-1]
