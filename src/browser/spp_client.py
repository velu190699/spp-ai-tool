from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import DOCUMENT_SEARCH_PATH, SPP_BASE_URL
from src.browser.download_utils import download_to_path, sanitize_filename

LOGGER = logging.getLogger(__name__)

# Matches "June 12 2026", "Jun 12 2026", "12/06/2026", "2026-06-12", etc.
_DATE_PATTERNS = [
    re.compile(r"\b([A-Za-z]+ \d{1,2},?\s+\d{4})\b"),   # June 12 2026 / June 12, 2026
    re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b"),           # 06/12/2026
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),                # 2026-06-12
]
_DATE_FORMATS = [
    "%B %d %Y", "%B %d, %Y",   # June 12 2026
    "%b %d %Y", "%b %d, %Y",   # Jun 12 2026
    "%m/%d/%Y",                 # 06/12/2026
    "%Y-%m-%d",                 # 2026-06-12
]


def _parse_date(text: str) -> datetime | None:
    """Try to parse a date string with multiple formats."""
    text = text.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _extract_published_date(anchor) -> datetime | None:
    """Look for a publication date in the anchor's parent container."""
    # SPP renders dates as sibling text or in a nearby element like:
    # <li><a href="...">Title</a> <span>June 12 2026</span></li>
    # Try the anchor's parent and its siblings/children
    for element in [anchor.find_parent(), anchor.find_parent() and anchor.find_parent().find_parent()]:
        if not element:
            continue
        text = element.get_text(" ", strip=True)
        for pattern in _DATE_PATTERNS:
            match = pattern.search(text)
            if match:
                parsed = _parse_date(match.group(1))
                if parsed:
                    return parsed
    return None


@dataclass(frozen=True)
class SppDocument:
    document_id: str
    title: str
    filename: str
    url: str
    size_label: str = ""
    published_date: datetime | None = field(default=None, compare=False)

    @property
    def date_suffix(self) -> str:
        """Returns date as YYYYMMDD string for use in filenames, or empty string."""
        if self.published_date:
            return self.published_date.strftime("%Y%m%d")
        return ""

    def named_with_date(self, stem: str, suffix: str) -> str:
        """Build a filename like 'RR Master List_20260612.xlsx'"""
        date = self.date_suffix
        if date:
            return f"{stem}_{date}{suffix}"
        return f"{stem}{suffix}"


def _document_from_anchor(anchor) -> Optional[SppDocument]:
    href = anchor.get("href") or ""
    parsed = urlparse(href)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3 or parts[0].lower() != "documents":
        return None
    document_id = parts[1]
    filename = sanitize_filename(parts[-1])
    title = anchor.get_text(" ", strip=True)
    size_label = ""
    span = anchor.find("span")
    if span:
        size_label = span.get_text(" ", strip=True).strip("()")
        title = title.replace(span.get_text(" ", strip=True), "").strip()
    published_date = _extract_published_date(anchor)
    return SppDocument(
        document_id=document_id,
        title=title,
        filename=filename,
        url=urljoin(SPP_BASE_URL, href),
        size_label=size_label,
        published_date=published_date,
    )


class SppClient:
    def __init__(self, base_url: str = SPP_BASE_URL, timeout: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def search_documents(self, document_name: str) -> list[SppDocument]:
        url = (
            f"{self.base_url}{DOCUMENT_SEARCH_PATH}"
            f"?document_name={quote_plus(document_name)}&search_type=filtered_search"
        )
        LOGGER.info("Searching SPP documents: %s", document_name)
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        documents = []
        for anchor in soup.find_all("a", href=True):
            doc = _document_from_anchor(anchor)
            if doc:
                documents.append(doc)
        return documents

    def search_site_documents(self, query: str) -> list[SppDocument]:
        url = f"{self.base_url}/search/?q={quote_plus(query)}&t=Documents"
        LOGGER.info("Searching SPP site documents: %s", query)
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        return [doc for doc in (_document_from_anchor(a) for a in soup.find_all("a", href=True)) if doc]

    def latest_document(
        self,
        document_name: str,
        matcher: Callable[[SppDocument], bool],
        *,
        allow_site_search: bool = False,
    ) -> Optional[SppDocument]:
        sources: Iterable[list[SppDocument]]
        primary = self.search_documents(document_name)
        sources = (primary, self.search_site_documents(document_name)) if allow_site_search else (primary,)
        for documents in sources:
            for document in documents:
                if matcher(document):
                    return document
        return None

    def download(self, document: SppDocument, target_dir: Path) -> Path:
        # Use date-based naming: "{stem}_{YYYYMMDD}{ext}"
        # Falls back to original filename if no date available
        path = Path(document.filename)
        named = document.named_with_date(path.stem, path.suffix)
        target = target_dir / named
        download_to_path(document.url, target, timeout=max(self.timeout, 120), session=self.session)
        return target


class PlaywrightSppClient:
    """Reserved for visible-browser SPP flows that cannot be handled by HTTP."""

    def __init__(self) -> None:
        self._available = False

    def is_available(self) -> bool:
        try:
            import playwright  # noqa: F401
        except Exception:
            return False
        return True


def rr_search_query_from_url(url: str) -> str:
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("q", [])
    return values[0] if values else ""