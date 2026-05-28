from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from config import LOW_TEXT_CHAR_THRESHOLD
from src.documents.rr_extractor import RRMention, extract_action_item_rrs, extract_rr_mentions

LOGGER = logging.getLogger(__name__)


@dataclass
class PdfParseResult:
    path: Path
    text: str
    rr_mentions: list[RRMention] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def extract_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_pdf(path: Path) -> PdfParseResult:
    warnings: list[str] = []
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        warning = f"Failed to extract text from {path.name}: {exc}"
        LOGGER.warning(warning)
        return PdfParseResult(path=path, text="", warnings=[warning])

    is_action_items = "action item" in path.name.lower()
    all_text: list[str] = []
    rr_mentions: list[RRMention] = []

    for page_num, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        all_text.append(page_text)
        rr_mentions.extend(extract_rr_mentions(page_text, source=path.name, page=page_num))
        if is_action_items:
            rr_mentions.extend(extract_action_item_rrs(page_text, source=path.name, page=page_num))

    text = "\n".join(all_text)
    if len(text.strip()) < LOW_TEXT_CHAR_THRESHOLD:
        warnings.append(f"Low or no extractable text in {path.name}")

    return PdfParseResult(path=path, text=text, rr_mentions=rr_mentions, warnings=warnings)
