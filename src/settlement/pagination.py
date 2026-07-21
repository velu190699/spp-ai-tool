"""pagination.py — real page numbers for RR docx files that lack them.

Technical: rr_structure counts Word's cached page-break markers
(<w:lastRenderedPageBreak/>) to anchor each section to a page. Some RR docx
files (RR728) carry ZERO such markers — Word never saved pagination — so every
section reports page 1. This module renders the docx to PDF (Microsoft Word
via COM, headless) and locates each charge-type heading's true page by
searching the PDF text with pypdf.

Business: page-anchored citations are a hard requirement — a reviewer must be
able to open the RR and check the formula on the cited page. A story without
page numbers fails review (Elizabeth, 2026-07-15).

The rendered PDF is cached next to the report outputs (never inside the synced
RR folders — those are append-only for the team). Failure of any step degrades
gracefully: callers keep the docx-derived pages.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def render_pdf_with_word(docx_path: Path, pdf_path: Path, *, with_markup: bool = False) -> bool:
    """Render docx -> PDF with headless Microsoft Word COM. True on success.

    with_markup=True exports the tracked-changes view (insertions underlined,
    deletions struck through) — used for the story-workbook screenshots. The
    default content view is what pagination anchors cite; the two views can
    paginate differently, so never mix their page numbers.
    """
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        LOGGER.info("pywin32 not available — cannot render %s for pagination", docx_path.name)
        return False
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(docx_path), ReadOnly=True, AddToRecentFiles=False)
        try:
            if with_markup:
                # Word refuses Item=wdExportDocumentWithMarkup (bogus "directory
                # name isn't valid" error) unless the revisions view actually
                # shows the markup — force it before exporting.
                view = doc.ActiveWindow.View
                view.ShowRevisionsAndComments = True
                view.RevisionsView = 0  # wdRevisionsViewFinal: final text + markup
            # 17 = wdExportFormatPDF; Item 7 = wdExportDocumentWithMarkup, 0 = content
            doc.ExportAsFixedFormat(str(pdf_path), 17, Item=7 if with_markup else 0)
        finally:
            doc.Close(False)
        return pdf_path.exists()
    except Exception as exc:
        LOGGER.warning("Word PDF render failed for %s: %s", docx_path.name, exc)
        return False
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def page_map_from_pdf(pdf_path: Path, headings: list[str]) -> dict[str, int]:
    """Map each heading string to the 1-based PDF page where it first appears."""
    from pypdf import PdfReader

    result: dict[str, int] = {}
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as exc:
        LOGGER.warning("Could not read rendered PDF %s: %s", pdf_path, exc)
        return result
    wanted = {h: _normalize(h) for h in headings if h}
    for page_number, page in enumerate(reader.pages, start=1):
        if not wanted:
            break
        try:
            text = _normalize(page.extract_text() or "")
        except Exception:
            continue
        for original, needle in list(wanted.items()):
            if needle and needle in text:
                result[original] = page_number
                del wanted[original]
    return result


def determinant_pages(pdf_path: Path, determinants, start_page: int = 1) -> dict[str, int]:
    """Map each determinant to the first PDF page (>= start_page) it appears on.

    Keys are returned without a leading '#'. start_page skips the table of
    contents / definition lists so a determinant resolves to its formula page,
    not an earlier mention.
    """
    from pypdf import PdfReader

    result: dict[str, int] = {}
    try:
        texts = [_normalize(p.extract_text() or "") for p in PdfReader(str(pdf_path)).pages]
    except Exception as exc:
        LOGGER.warning("Could not read PDF %s for determinant pages: %s", pdf_path, exc)
        return result
    for determinant in determinants:
        key = str(determinant).lstrip("#")
        needle = _normalize(key)
        if not needle:
            continue
        for page_number in range(max(1, start_page), len(texts) + 1):
            if needle in texts[page_number - 1]:
                result[key] = page_number
                break
    return result


def repaginate(report: dict, docx_path: str, cache_dir: str) -> bool:
    """Fix a report whose page anchors are unusable (all page 1).

    Renders the docx once (cached), then rewrites the page numbers in
    charge_type_index and the rr_document citations from the real PDF pages.
    Returns True when pages were corrected.
    """
    index = report.get("charge_type_index") or []
    pages = {entry.get("page") for entry in index}
    if not index or pages - {1, None, 0}:
        return False  # docx pagination looks real — nothing to fix

    # Word COM resolves paths in its own working directory — everything must
    # be absolute or the export fails with "The directory name isn't valid".
    docx = Path(docx_path).resolve()
    pdf = (Path(cache_dir) / (docx.stem + ".pdf")).resolve()
    if not pdf.exists() and not render_pdf_with_word(docx, pdf):
        return False

    headings = [f"{e['section']} {e['title']}" for e in index]
    found = page_map_from_pdf(pdf, headings)
    if not found:
        return False
    for entry in index:
        key = f"{entry['section']} {entry['title']}"
        if key in found:
            entry["page"] = found[key]
    by_section = {e["section"]: e.get("page") for e in index}
    for cite in (report.get("citations") or {}).get("rr_document", []):
        match = re.search(r"(\d+\.\d+(?:\.\d+)*)", str(cite.get("reference", "")))
        if match and by_section.get(match.group(1)):
            cite["page"] = by_section[match.group(1)]
    report["pagination_source"] = f"rendered PDF ({pdf.name})"
    LOGGER.info("Repaginated %s from rendered PDF: %s", report.get("rr_id"), found)
    return True
