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
import time
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# COM HRESULTs that mean "the Word automation server is busy / not up yet",
# not "the render is impossible". Word intermittently rejects the very first
# automation call on a cold start with RPC_E_CALL_REJECTED; a short backoff and
# a fresh instance clears it. Without a retry, a single transient hiccup makes
# an unattended run silently skip the screenshot tab (item_screenshots treats a
# False return as "no markup PDF" and moves on), so a scheduled run can publish
# a workbook with no redline images and only a warning nobody reads.
_TRANSIENT_COM_HRESULTS = frozenset({
    -2147418111,  # 0x80010001 RPC_E_CALL_REJECTED    ("Call was rejected by callee")
    -2147417846,  # 0x8001010A RPC_E_SERVERCALL_RETRYLATER
    -2146959355,  # 0x80080005 CO_E_SERVER_EXEC_FAILURE (Word failed to launch)
})
_RENDER_MAX_ATTEMPTS = 3
_RENDER_BACKOFF_SECONDS = 3.0
# Post-Open calls (ActiveWindow.View, ExportAsFixedFormat) are rejected while
# Word is still laying out the just-opened document — larger RRs (RR748) hit
# this reliably, small ones (RR728) happen to be ready in time. Restarting the
# whole render doesn't help (a fresh instance is busy at the same point), so
# these calls get their own short in-place retry that just waits for Word to
# finish, rather than relaunching. Empirically one 1.5s wait clears it.
_COM_CALL_ATTEMPTS = 6
_COM_CALL_BACKOFF_SECONDS = 1.5


def _is_transient_com_error(exc: BaseException) -> bool:
    """True for COM errors a retry can plausibly clear (server busy / not up yet).

    pythoncom.com_error exposes the HRESULT both as ``.hresult`` and as the
    first positional arg, so check both — the exact attribute set varies by
    pywin32 version and by whether the error came from Dispatch or a later call.
    """
    hresult = getattr(exc, "hresult", None)
    if hresult in _TRANSIENT_COM_HRESULTS:
        return True
    args = getattr(exc, "args", ())
    return bool(args and isinstance(args[0], int) and args[0] in _TRANSIENT_COM_HRESULTS)


def _com_call(fn, *, attempts: int = _COM_CALL_ATTEMPTS, backoff_seconds: float = _COM_CALL_BACKOFF_SECONDS):
    """Invoke a single COM call, retrying transient "server busy" rejections.

    Unlike the whole-render retry, this reuses the same Word instance and just
    waits — the document is open but Word hasn't finished laying it out, so the
    next call to ActiveWindow/Export is rejected until it settles.
    """
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if _is_transient_com_error(exc) and attempt < attempts:
                time.sleep(backoff_seconds * attempt)
                continue
            raise


def _render_pdf_once(docx_path: Path, pdf_path: Path, with_markup: bool) -> bool:
    """One Word COM render attempt. Raises on COM error; returns PDF existence.

    Uses a fresh DispatchEx instance and CoUninitialize so each retry starts
    from a clean COM state rather than reusing a server that just rejected us.
    Post-Open calls are wrapped in ``_com_call`` so a document that Word is still
    paginating doesn't fail the whole render on a transient rejection.
    """
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = _com_call(lambda: word.Documents.Open(str(docx_path), ReadOnly=True, AddToRecentFiles=False))
        try:
            if with_markup:
                # Word refuses Item=wdExportDocumentWithMarkup (bogus "directory
                # name isn't valid" error) unless the revisions view actually
                # shows the markup — force it before exporting. ActiveWindow is
                # unavailable until Word finishes laying out the doc, hence _com_call.
                def _show_markup():
                    view = doc.ActiveWindow.View
                    view.ShowRevisionsAndComments = True
                    view.RevisionsView = 0  # wdRevisionsViewFinal: final text + markup
                _com_call(_show_markup)
            # 17 = wdExportFormatPDF; Item 7 = wdExportDocumentWithMarkup, 0 = content
            _com_call(lambda: doc.ExportAsFixedFormat(str(pdf_path), 17, Item=7 if with_markup else 0))
        finally:
            doc.Close(False)
        return pdf_path.exists()
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def render_pdf_with_word(
    docx_path: Path,
    pdf_path: Path,
    *,
    with_markup: bool = False,
    max_attempts: int = _RENDER_MAX_ATTEMPTS,
    backoff_seconds: float = _RENDER_BACKOFF_SECONDS,
) -> bool:
    """Render docx -> PDF with headless Microsoft Word COM. True on success.

    with_markup=True exports the tracked-changes view (insertions underlined,
    deletions struck through) — used for the story-workbook screenshots. The
    default content view is what pagination anchors cite; the two views can
    paginate differently, so never mix their page numbers.

    Transient COM failures (a cold-start "Call was rejected by callee", server
    busy, or a failed launch) are retried up to ``max_attempts`` times with a
    linear backoff, since these clear on a second try; a non-transient error
    fails immediately. Callers degrade gracefully on a False return.
    """
    try:
        import pythoncom  # noqa: F401  (import-guard: pywin32 present?)
        import win32com.client  # noqa: F401
    except ImportError:
        LOGGER.info("pywin32 not available — cannot render %s for pagination", docx_path.name)
        return False
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            if _render_pdf_once(docx_path, pdf_path, with_markup):
                if attempt > 1:
                    LOGGER.info("Word PDF render of %s succeeded on attempt %d/%d", docx_path.name, attempt, max_attempts)
                return True
            last_error = "no PDF produced"
        except Exception as exc:  # COM errors surface as pythoncom.com_error
            last_error = str(exc)
            if not _is_transient_com_error(exc):
                LOGGER.warning("Word PDF render failed for %s: %s", docx_path.name, exc)
                return False
        # Transient failure (or an empty result): back off and try a fresh instance.
        if attempt < max_attempts:
            delay = backoff_seconds * attempt
            LOGGER.warning(
                "Word PDF render of %s hit a transient issue (attempt %d/%d): %s — retrying in %.0fs",
                docx_path.name, attempt, max_attempts, last_error, delay,
            )
            if delay > 0:
                time.sleep(delay)
    LOGGER.warning("Word PDF render failed for %s after %d attempts: %s", docx_path.name, max_attempts, last_error)
    return False


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
