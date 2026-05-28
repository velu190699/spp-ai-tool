from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import DOCUMENT_SEARCH_PATH, SPP_BASE_URL
from src.browser.download_utils import download_to_path, sanitize_filename

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SppDocument:
    document_id: str
    title: str
    filename: str
    url: str
    size_label: str = ""


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
    return SppDocument(
        document_id=document_id,
        title=title,
        filename=filename,
        url=urljoin(SPP_BASE_URL, href),
        size_label=size_label,
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
        # "Latest" means first exact matching result in SPP Documents & Filings.
        # Site-wide search is only a fallback for RR package lookups where the
        # master-list link points to /search/?q=rr<number>.
        sources: Iterable[list[SppDocument]]
        primary = self.search_documents(document_name)
        sources = (primary, self.search_site_documents(document_name)) if allow_site_search else (primary,)
        for documents in sources:
            for document in documents:
                if matcher(document):
                    return document
        return None

    def download(self, document: SppDocument, target_dir: Path) -> Path:
        target = target_dir / f"{document.document_id}_{document.filename}"
        download_to_path(document.url, target, timeout=max(self.timeout, 120))
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
