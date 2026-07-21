"""screenshots.py — per-item redline crops for the Jira story workbooks.

Technical: renders the RR docx to a MARKUP-view PDF (tracked changes visible:
insertions underlined, deletions struck through) via pagination's headless Word
COM render, then for each numbered story item crops the FULL formula block for
that item's determinant with pypdfium2. "Full block" = from the determinant's
definition line (e.g. "(a) RtDevHrlyQty a,s,h = ...") down to the next
determinant definition; when that block crosses a page break it is emitted as
TWO images for the same item so the formula is never cut mid-way. One or two
PNGs per item, keyed by a stable code (RR<id>-<NN>) that also goes in the
caption so Miquel's app can place each image where that code appears.

Business: old-vs-new formulas read poorly as text (Eduardo, 2026-07-17);
reviewers prefer SPP's own tracked-changes formula per item, complete, like
Kashmita's SP-12814. Miquel's guide: the story row carries a short Local ID and
a sheet with that exact name holds the images; his app attaches them to Jira.

Fragility (accepted): block detection keys off definition lines found as text.
A determinant whose formula is a picture (no searchable text) can't be located
and that item is skipped; an item that names no determinant is skipped. These
are logged, never guessed.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from src.settlement.pagination import render_pdf_with_word, page_map_from_pdf

LOGGER = logging.getLogger(__name__)

_RENDER_SCALE = 2.0    # 144 DPI — readable formulas without bloating the xlsx
_MARGIN_PTS = 6        # headroom above/below a block edge
_MAX_BLOCK_PAGES = 2   # a single formula spans at most this many pages (safety cap)
_FOOTER_BAND_PTS = 65  # ignore the page-number footer when bounding a block
_HEADER_BAND_PTS = 45  # ignore any running header at the top of the page
_EQ_IMG_PAD = 14       # extra headroom for a line carrying a Σ (OLE) image glyph
_PROSE_MIN_WORDS = 3   # >= this many lowercase words on a non-operator line = prose

# A "definition line" opens a determinant's formula: an optional dotted label
# ("(a)", "(b.2.3)"), an optional '#', the CamelCase determinant name, then
# (subscripts and) an '='. The dotted label matters: sub-determinants are written
# "(b.2.3) RtMwpBaaDistHrlyQty = …", and if that isn't recognised as a def the
# crop of the determinant above it runs straight through into it.
_DEF_LINE = re.compile(r"^\s*(?:\([a-z0-9.]+\)\s*){0,2}#?([A-Z][A-Za-z0-9]+)\b[^=]{0,40}=")
# The formula ends where the variable glossary begins ("Where," / "And where," /
# "The above variables…"). A determinant's own formula NEVER crosses a Where —
# what follows is a different determinant's definition (Eduardo, 2026-07-17).
_GLOSSARY = re.compile(
    r"(?i)^\s*(and\s+)?where\b"
    r"|^\s*(the above variables|variable\s+(unit|definition))")

# Formula-shape signals used to bound a block: an operator/keyword opener, or a
# CamelCase determinant token. Prose (footnotes, "(a.1) Based on…") has neither.
_LOWER_WORD = re.compile(r"\b[a-z]{2,}\b")
_FORMULA_OPENER = re.compile(r"(?i)^(IF|THEN|ELSE|END|SUM|MIN|MAX|ABS|LOG|EXP)\b")
_CAMEL = re.compile(r"[A-Z][a-z]+[A-Z]")
_PAGE_NUMBER = re.compile(r"^\d{1,4}$")
_HEADER_MAX_LINES = 14        # look-back cap when collecting an IF … THEN header
_TRAILING_BOOL = re.compile(r"(?i)\b(and|or)\s*$")  # a boolean condition, not a def
_IF_TOKEN = re.compile(r"(?i)\bIF\b")               # IF anywhere (e.g. "(b.2.1) IF …")
_THEN_LINE = re.compile(r"(?i)^\s*THEN\b")
_IF_LINE = re.compile(r"(?i)^\s*(?:\([a-z0-9.]+\)\s*)*IF\b")  # a line that OPENS with IF


def _def_name(text):
    """The determinant a line defines, or None if the line is not a definition.

    A definition is "<Name> <subscripts> = <formula>". Excluded: keyword openers
    (IF/THEN/…) and boolean CONDITIONS inside an IF — a comparison (`<=`, `<>`,
    `Flg = "1"`) or a line trailing in AND/OR reads as "<Name> … =" but is a test,
    not an assignment; treating it as a def would break the IF/THEN header crop.
    """
    match = _DEF_LINE.match(text)
    if not match:
        return None
    name = match.group(1)
    if _FORMULA_OPENER.match(name):
        return None
    prefix = match.group(0).rstrip()          # "<Name> … ="
    if len(prefix) >= 2 and prefix[-2] in "<>!":  # "<=", ">=", "<>", "!=" -> comparison
        return None
    if _TRAILING_BOOL.search(text):           # "… = \"1\" AND" -> condition continuation
        return None
    return name


def _lines_of_page(textpage):
    """Group a page's characters into text lines with geometry.

    Returns [{'top','bottom','left','text'}] sorted top-of-page first. Lines are
    formed by vertical overlap of character boxes (PDF points, origin bottom-left).
    """
    lines: list[dict] = []
    for i in range(textpage.count_chars()):
        left, bottom, right, top = textpage.get_charbox(i)
        char = textpage.get_text_range(i, 1)
        center = (bottom + top) / 2
        placed = False
        for ln in lines:
            if ln["bottom"] <= center <= ln["top"]:
                ln["left"] = min(ln["left"], left)
                ln["bottom"] = min(ln["bottom"], bottom)
                ln["top"] = max(ln["top"], top)
                ln["chars"].append((left, char))
                placed = True
                break
        if not placed:
            lines.append({"left": left, "bottom": bottom, "top": top, "chars": [(left, char)]})
    for ln in lines:
        ln["chars"].sort()
        ln["text"] = "".join(c for _, c in ln["chars"])
    lines.sort(key=lambda x: -x["top"])
    return lines


def _all_lines(doc, start_page):
    """Every text line from start_page onward, in document order.

    Each entry: {'page','top','text','def'} where 'def' is the determinant name
    if the line opens a definition, else None. One pass; used both to locate each
    item's definition and to find where its formula ends.
    """
    out = []
    for page_index in range(start_page - 1, len(doc)):
        width_pts, height_pts = doc[page_index].get_size()
        textpage = doc[page_index].get_textpage()
        try:
            for ln in _lines_of_page(textpage):
                # Word revision annotations ("Field Code Changed", "Formatted…")
                # sit in the right margin; ignore them so a blank continuation
                # isn't kept alive by a margin note, and they never match a def.
                if ln["left"] > 0.68 * width_pts:
                    continue
                # The page-number footer / running header would otherwise extend
                # a block down to the page bottom — ignore both margin bands.
                if ln["top"] < _FOOTER_BAND_PTS or ln["top"] > height_pts - _HEADER_BAND_PTS:
                    continue
                name = _def_name(ln["text"])
                out.append({"page": page_index, "top": ln["top"], "bottom": ln["bottom"],
                            "text": ln["text"], "def": name})
        finally:
            textpage.close()
    return out


def _is_prose(text):
    """True for a natural-language line (footnote, "(a.1) Based on…" paragraph).

    A formula continuation opens with an operator or an IF/THEN/ELSE/Min/Max
    keyword (checked first, so a formula line that happens to carry lowercase
    words like "dir"/"rsg" is never mistaken for prose). Anything else with
    several lowercase words reads as prose.
    """
    t = text.strip()
    if not t or t[0] in "+-*/=":
        return False
    if _FORMULA_OPENER.match(t):
        return False
    return len(_LOWER_WORD.findall(t)) >= _PROSE_MIN_WORDS


def _looks_like_formula(text):
    """True when the line carries formula content (used to resume past a footnote).

    An operator/keyword opener, a CamelCase determinant token, or an '=' all
    qualify. '(' and '[' are NOT openers on their own — prose such as "(a.1)
    Based on…" opens with a paren too, so paren lines qualify only via CamelCase.
    """
    t = text.strip()
    if not t:
        return False
    if t[0] in "+-*/=":
        return True
    if _FORMULA_OPENER.match(t):
        return True
    if _CAMEL.search(t):
        return True
    return "=" in t


def _det_matches(defname, key):
    """A definition line's determinant matches `key` (lower-case, no '#').

    Startswith (bounded to +2 chars) absorbs a subscript letter glued onto the
    name by text extraction — e.g. def "rtslposdev5minfcta" for key
    "rtslposdev5minfct".
    """
    d = (defname or "").lower()
    return d == key or (d.startswith(key) and len(d) - len(key) <= 2)


def _text_defines(line, key):
    """True if `line` opens `key`'s DEFINITION by text (not just mentions it).

    The determinant must sit at the head of the line and be followed by an '='
    (assignment) or a Σ (OLE) image glyph — a Σ-image definition has no '=' on
    the text line. A bare USAGE ("… RtMwpCpAmt a,s,b,c * RtLrMwpFct") or a
    glossary-table row is NOT a definition, so it must not be matched (else the
    crop shows an unrelated fragment instead of skipping a determinant this RR
    only references).
    """
    low = line["text"].lower()
    pos = low.find(key)
    if pos < 0 or pos > 40:
        return False
    tail = line["text"][pos + len(key):]
    return "=" in tail or "￼" in tail  # assignment, or a sigma (OLE) image after the name


def _find_start(lines, key, cursor):
    """Index where determinant `key`'s formula opens; None if not present.

    Prefers a real definition line at/after the cursor (document order), then a
    definition anywhere (a determinant may be defined earlier than the running
    cursor), then a text definition (Σ-image formulas have no parsable '=' on the
    definition line, so `_DEF_LINE` misses them). A determinant that only appears
    as a usage or in the glossary returns None — there is no formula to crop.
    """
    for rng in (range(cursor, len(lines)), range(len(lines))):
        sp = next((k for k in rng if _det_matches(lines[k]["def"], key)), None)
        if sp is not None:
            return sp
    for rng in (range(cursor, len(lines)), range(len(lines))):
        sp = next((k for k in rng if _text_defines(lines[k], key)), None)
        if sp is not None:
            return sp
    return None


def _resume_after_prose(lines, k, page_cap, det_key):
    """Skip an interleaved prose run (a footnote at a page foot); resume the formula.

    Returns the index of the next formula line, or None when the prose is
    terminal — i.e. the glossary, a different determinant's definition, or the
    page cap comes first. This is what lets a formula that continues on the next
    page survive a footnote sitting between its two halves.
    """
    j = k
    while j < len(lines):
        ln = lines[j]
        if ln["page"] > page_cap or _GLOSSARY.match(ln["text"]):
            return None
        if ln["def"] and not _det_matches(ln["def"], det_key):
            return None
        if _looks_like_formula(ln["text"]):
            return j
        j += 1
    return None


def _formula_header(lines, def_pos):
    """Indices of an "IF … THEN" header sitting ABOVE the definition line.

    Formulas are often written "IF <cond> THEN <det> = … ELSE …", so the def
    line is the THEN body and the condition sits above it (Eduardo, 2026-07-17 —
    the crop started at "<det> =" and dropped the IF). Anchored on the THEN or IF
    line directly above the def: from there, collect upward until a line opening
    with the IF keyword (labels like "(b.2.1) IF …", a bare "IF …" directly above
    the def with no THEN, and multi-line/page-crossing conditions all count).
    Definition classification is ignored inside the header because condition
    lines ("Flg = \"1\" AND") look like defs. No THEN/IF above -> nothing added.
    """
    k = def_pos - 1
    while k >= 0:                                   # first real line above the def
        text = lines[k]["text"].strip()
        if text and not _PAGE_NUMBER.match(text):
            break
        k -= 1
    if k < 0 or not (_THEN_LINE.match(lines[k]["text"]) or _IF_LINE.match(lines[k]["text"])):
        return []  # the line above is a THEN, or the IF itself (no separate THEN)
    header = []
    steps = 0
    while k >= 0 and steps < _HEADER_MAX_LINES:
        ln = lines[k]
        text = ln["text"].strip()
        if not text or _PAGE_NUMBER.match(text):
            k -= 1
            continue
        if _GLOSSARY.match(ln["text"]) or _is_prose(ln["text"]):
            return []                               # ran past the top without an IF
        header.append(k)
        if _IF_TOKEN.search(text):
            return sorted(header)                   # IF found — header is complete
        k -= 1
        steps += 1
    return []


def _starts_next_header(lines, k, det_key, page_cap):
    """True if line ``k`` begins the IF/THEN header of a LATER, different determinant.

    A sub-determinant is often written "(b.2.1) IF <cond> / THEN / <otherdet> = …"
    directly below the previous determinant's (complete) one-line formula. That
    labeled IF is NOT a new definition and DOES look like a formula (CamelCase),
    so the walk-down would otherwise swallow it — and, if a page break falls
    between the IF and THEN, emit a useless lone-"THEN" crop (RR728 item 27).

    The IF/THEN is the NEXT determinant's header exactly when the same
    ``_formula_header`` that builds that determinant's crop reaches back to line
    ``k``. Reusing it keeps this in lockstep with the header-prepend logic and
    never fires for an IF/THEN/ELSE that belongs to the current determinant (its
    value lines sit between the IF and any later def, so the header walk stops
    before reaching ``k``).
    """
    if not (_IF_LINE.match(lines[k]["text"]) or _THEN_LINE.match(lines[k]["text"])):
        return False
    for j in range(k + 1, min(len(lines), k + 1 + _HEADER_MAX_LINES)):
        ln = lines[j]
        if ln["page"] > page_cap or _GLOSSARY.match(ln["text"]):
            return False
        if ln["def"]:
            # A def for the SAME determinant is a continuation, not a boundary.
            return not _det_matches(ln["def"], det_key) and k in _formula_header(lines, j)
    return False


def _block_lines(lines, start_pos, det_key):
    """Indices of the lines that make up determinant `det_key`'s formula.

    Prepends an "IF … THEN" header when the formula is a conditional, then walks
    DOWN from the definition keeping formula lines (including IF/THEN/ELSE
    branches and a repeated "<det> = 0" ELSE value for the SAME determinant).
    Stops at the glossary ("Where"), a DIFFERENT determinant's definition, the
    IF/THEN header of the NEXT determinant, or the page cap; drops blank lines,
    page numbers, and OLE fragments; and jumps over a footnote when the formula
    resumes after it.
    """
    page_cap = lines[start_pos]["page"] + _MAX_BLOCK_PAGES - 1
    kept = _formula_header(lines, start_pos) + [start_pos]
    k = start_pos + 1
    while k < len(lines):
        ln = lines[k]
        if ln["page"] > page_cap or _GLOSSARY.match(ln["text"]):
            break
        if ln["def"] and not _det_matches(ln["def"], det_key):
            break
        if _starts_next_header(lines, k, det_key, page_cap):
            break  # the next sub-determinant's "(b.2.1) IF … THEN" header starts here
        if not ln["text"].strip() or _PAGE_NUMBER.match(ln["text"].strip()):
            k += 1
            continue
        if _is_prose(ln["text"]):
            resume = _resume_after_prose(lines, k, page_cap, det_key)
            if resume is None:
                break
            k = resume
            continue
        if _looks_like_formula(ln["text"]):
            kept.append(k)
            k += 1
            continue
        k += 1  # neither formula nor prose = an OLE/footnote fragment — skip
    return kept


def _render_kept(doc, lines, kept):
    """Crop the kept lines, one image per page they span; [(image, page_no), …].

    Each page's crop runs from the top of its highest kept line to the bottom of
    its lowest, so interleaved footnotes/prose (which are not kept) fall outside
    the crop. A page whose kept lines carry a Σ (OLE) image glyph gets extra
    headroom so the summation symbol is not clipped.
    """
    by_page: dict[int, tuple] = {}
    for idx in kept:
        ln = lines[idx]
        top, bottom, has_eq = by_page.get(ln["page"], (-1e9, 1e9, False))
        by_page[ln["page"]] = (max(top, ln["top"]), min(bottom, ln["bottom"]),
                               has_eq or ("￼" in ln["text"]))
    out = []
    for page_index in sorted(by_page):
        top, bottom, has_eq = by_page[page_index]
        page = doc[page_index]
        _width, height_pts = page.get_size()
        pad = _EQ_IMG_PAD if has_eq else 0
        top = min(height_pts, top + _MARGIN_PTS + pad)
        bottom = max(0, bottom - _MARGIN_PTS - pad)
        if top - bottom < 12:
            continue
        pil = page.render(scale=_RENDER_SCALE).to_pil()
        px_top = int((height_pts - top) * _RENDER_SCALE)
        px_bottom = int((height_pts - bottom) * _RENDER_SCALE)
        out.append((pil.crop((0, px_top, pil.width, px_bottom)), page_index + 1))
    return out


def _part_suffix(part_index, total):
    """'' for a lone image; 'a'/'b'/… when an item's formula spans >1 image.

    The suffix goes in both the PNG name and the caption code, and the workbook
    description lists all of an item's codes (…-02a, …-02b) so a reviewer sees at
    a glance that one item has two screenshots (Eduardo, 2026-07-17).
    """
    if total == 1:
        return ""
    return chr(ord("a") + part_index) if part_index < 26 else str(part_index + 1)


def item_screenshots(docx_path, report: dict, stories: dict | None,
                     out_dir, pdf_cache_dir) -> list[tuple[Path, str]]:
    """Crop the full redline formula per numbered item; returns [(png, caption)].

    Renders a markup-view PDF (cached as <stem>.markup.pdf). Each item yields one
    or more images (two when its formula crosses a page break), named/captioned
    with a stable code RR<id>-<NN> plus an 'a'/'b' suffix on a split. Each mirror
    item is stamped with `parts` (image count) so the workbook description can
    list its codes. Any failure returns what was produced so far — screenshots
    are enrichment and must never sink the workbook write.
    """
    from src.settlement.settlement_report import story_items, _item_determinant

    jira_stories = (stories or {}).get("jira_stories") or []
    items = []
    for story in jira_stories:
        items += story_items(story.get("description", ""))
    if not items:
        return []
    # Mirror items (formula-free), keyed by number, so we can stamp `parts`.
    mirror = {int(it.get("n", 0)): it for story in jira_stories for it in (story.get("items") or [])}

    docx = Path(docx_path).resolve()
    pdf = (Path(pdf_cache_dir) / (docx.stem + ".markup.pdf")).resolve()
    if not pdf.exists() and not render_pdf_with_word(docx, pdf, with_markup=True):
        LOGGER.warning("No markup PDF for %s — screenshot tab skipped", docx.name)
        return []
    try:
        import pypdfium2
    except ImportError:
        LOGGER.warning("pypdfium2 not installed — screenshot tab skipped (pip install pypdfium2)")
        return []

    rr_id = str(report.get("rr_id", "RR")).replace(" ", "")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    images: list[tuple[Path, str]] = []
    doc = pypdfium2.PdfDocument(str(pdf))
    try:
        headings = [f"{e['section']} {e['title']}" for e in report.get("charge_type_index") or []
                    if str(e.get("banner", "")).startswith("Market")]
        heading_pages = page_map_from_pdf(pdf, headings)
        start = min(heading_pages.values()) if heading_pages else 1
        lines = _all_lines(doc, start)

        cursor = 0  # advance in document order so each item's block is distinct
        missed = []
        for number, text in items:
            determinant = _item_determinant(text).lstrip("#")
            if not determinant:
                continue
            code = f"{rr_id}-{number:02d}"
            key = determinant.lower()
            start_pos = _find_start(lines, key, cursor)
            crop = _render_kept(doc, lines, _block_lines(lines, start_pos, key)) if start_pos is not None else []
            if start_pos is not None and start_pos >= cursor:
                cursor = start_pos + 1  # only move forward (a global match may be earlier)

            if number in mirror:
                mirror[number]["parts"] = len(crop)
            if not crop:
                missed.append(f"{number}:{determinant}")
                continue
            total = len(crop)
            for part, (image, page_number) in enumerate(crop):
                full_code = f"{code}{_part_suffix(part, total)}"
                png = out / f"{full_code}.png"
                image.save(png)
                images.append((png, f"[{full_code}] {determinant} (redline p.{page_number})"))
        if missed:
            LOGGER.info("%s: no crop for %d item(s) (image-only or unmatched): %s",
                        rr_id, len(missed), ", ".join(missed))
    finally:
        doc.close()
    return images
