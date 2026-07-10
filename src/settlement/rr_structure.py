#!/usr/bin/env python3
"""
rr_structure.py — structure-aware extractor for SPP Revision Request (RR) .docx files.

Technical: unlike flattened-text extraction (which drops headings and equations,
causing misses like RR623 section 4.5.18), this walks word/document.xml directly
and produces:

  1. impacted_checklist : sections named in the RR's "Impacted SPP Documents" block
  2. charge_type_index  : every governing-doc heading (banner -> section -> title,
                          with is_new from <w:ins>) found in the RR body
  3. reconciliation     : impacted vs body. Any listed section missing a body
                          heading (or vice-versa) is a HARD FAIL.
  4. marked_text        : body text with {{INS}}/{{DEL}} and [[EQ]] preserved, for
                          the downstream Claude prompt (rr_extraction_prompt.md)

Business: an SPP Revision Request changes the settlement calculations PCI's
software has to replicate. "Market Protocols" and the "Settlement User Guide"
are the two governing documents that define those calculations (SPP treats them
as one banner class here — same governing document, different names). Every RR
declares up front which sections it touches ("Impacted SPP Documents"); the
reconciliation step below exists because a missed section is not a cosmetic
gap — it is a charge code PCI's settlement system will compute incorrectly in
production. Validated on 6 real RRs: RR623, RR748, RR750, RR773, RR665, RR786.

USAGE (standalone, for validating a new RR before wiring it into the pipeline)
    python -m src.settlement.rr_structure --file RR623.docx --out-json rr623.json --out-text rr623.txt
    python -m src.settlement.rr_structure --file RR623.docx --banners "MARKET PROTOCOLS,SETTLEMENT USER GUIDE,TARIFF,OPERATING CRITERIA"
    # exit code 2 => hard-fail reconciliation (do not trust; route to manual review)
"""

import argparse, zipfile, re, json, sys
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NS = {"w": W, "m": M}

DEFAULT_BANNERS = ["MARKET PROTOCOLS", "SETTLEMENT USER GUIDE", "TARIFF", "OPERATING CRITERIA"]
SAME_DOC = {"MARKET PROTOCOLS", "SETTLEMENT USER GUIDE"}  # normalized to one class


def para_text(p):
    return "".join((t.text or "") for t in p.iter()
                   if etree.QName(t).localname in ("t", "delText"))


def heading_is_new(p):
    """True if any run in the heading sits inside a <w:ins> (tracked insertion)."""
    for t in p.iter():
        if etree.QName(t).localname == "t":
            anc = t
            while anc is not None:
                if etree.QName(anc).localname == "ins":
                    return True
                anc = anc.getparent()
    return False


def norm_banner(text):
    u = text.upper().strip()
    if u in SAME_DOC:
        return "Market Protocols / Settlement User Guide"
    return u.title()


def omml_linear(elem):
    q = etree.QName(elem).localname
    kids = lambda e: "".join(omml_linear(c) for c in e)
    if q == "t":   return elem.text or ""
    if q == "r":   return kids(elem)
    if q == "f":
        n = elem.find("m:num", NS); d = elem.find("m:den", NS)
        return f"( {omml_linear(n) if n is not None else ''} )/( {omml_linear(d) if d is not None else ''} )"
    if q in ("sSub", "sSup", "sSubSup"):
        base = elem.find("m:e", NS); sub = elem.find("m:sub", NS); sup = elem.find("m:sup", NS)
        s = omml_linear(base) if base is not None else ""
        if sub is not None: s += f"_{{{omml_linear(sub)}}}"
        if sup is not None: s += f"^{{{omml_linear(sup)}}}"
        return s
    if q == "nary":
        op = "SUM"; chr_ = elem.find(".//m:chr", NS)
        if chr_ is not None:
            op = {"∑": "SUM", "∏": "PROD"}.get(chr_.get(f"{{{M}}}val"), "SUM")
        sub = elem.find("m:sub", NS); e = elem.find("m:e", NS)
        return f"{op}_{{{omml_linear(sub) if sub is not None else ''}}} ( {omml_linear(e) if e is not None else ''} )"
    if q == "d":   return "( " + kids(elem) + " )"
    return kids(elem)


def para_marked(p):
    """Serialize a paragraph preserving ins/del + inline equations."""
    out = []
    for node in p.iter():
        q = etree.QName(node).localname; ns = etree.QName(node).namespace
        if ns == M and q == "oMath":
            out.append(" [[EQ: " + omml_linear(node).strip() + " ]] ")
            for c in node.iter(): c.text = None
            continue
        if ns == W and q in ("t", "delText"):
            text = node.text or ""
            anc = node; status = None
            while anc is not None:
                aq = etree.QName(anc).localname
                if aq == "ins": status = "INS"; break
                if aq == "del": status = "DEL"; break
                anc = anc.getparent()
            if q == "delText": status = "DEL"
            out.append("{{INS:" + text + "}}" if status == "INS"
                       else "{{DEL:" + text + "}}" if status == "DEL" else text)
    return "".join(out)


def extract(docx_path, banners, sharepoint_url=None, cuf_suf_refs=None):
    banners_up = [b.upper() for b in banners]
    z = zipfile.ZipFile(docx_path)
    root = etree.fromstring(z.read("word/document.xml"))
    body = root.find("w:body", NS)

    def pstyle(p):
        pPr = p.find("w:pPr", NS)
        if pPr is None: return None
        st = pPr.find("w:pStyle", NS)
        return st.get(f"{{{W}}}val") if st is not None else None

    def is_bold(p):
        # A heading if ALL non-empty text runs are bold (charge-type headings in
        # SPP docs are bold but carry no Heading style).
        runs = p.findall(".//w:r", NS)
        any_text = False
        for r in runs:
            t = r.find("w:t", NS)
            if t is None or not (t.text or "").strip():
                continue
            any_text = True
            rpr = r.find("w:rPr", NS)
            if rpr is None or rpr.find("w:b", NS) is None:
                return False
        return any_text

    def is_heading_style(p):
        s = (pstyle(p) or "").lower()
        return "heading" in s or "title" in s

    def is_heading(p):
        return is_heading_style(p) or is_bold(p)

    # Compute a page number for each paragraph by counting rendered page breaks
    # that occur at or before it. Word emits <w:lastRenderedPageBreak/> and
    # <w:br w:type="page"/> at page boundaries.
    paras_raw = body.findall(".//w:p", NS)
    paras = []
    page = 1
    for p in paras_raw:
        # count page breaks that appear inside this paragraph
        breaks_here = 0
        for node in p.iter():
            ln = etree.QName(node).localname
            if ln == "lastRenderedPageBreak":
                breaks_here += 1
            elif ln == "br" and node.get(f"{{{W}}}type") == "page":
                breaks_here += 1
        paras.append((p, para_text(p).strip(), page))
        page += breaks_here

    # A banner is a heading-styled paragraph whose text matches a known banner,
    # OR an "Attachment XX ..." heading (Tariff attachments carry charge types too).
    def banner_of(txt):
        u = txt.upper()
        for b in banners_up:
            if u == b or u.startswith(b + " "):
                return norm_banner(txt.split()[0] if u.startswith("TARIFF") else txt)
        if u.startswith("ATTACHMENT ") or "ATTACHMENT AE" in u:
            return "Tariff (" + txt.title() + ")"
        return None

    # 1) impacted checklist ----------------------------------------------------
    impacted = []
    for p, txt, pg in paras:
        if "Market Protocols" in txt and "Section:" in txt:
            seg = re.split(r'Version', txt.split("Section:", 1)[1])[0]
            for m in re.finditer(r'(\(New\)\s*)?(\d+\.\d+(?:\.\d+)*)', seg):
                impacted.append({"document": "Market Protocols / Settlement User Guide",
                                 "section": m.group(2), "is_new": bool(m.group(1))})
        if txt.strip().startswith("☒") and "Tariff" in txt and "Attachment AE" in txt:
            for m in re.finditer(r'Attachment AE.*?(\d+\.\d+)', txt):
                impacted.append({"document": "Tariff (Attachment AE)",
                                 "section": m.group(1), "is_new": "(New)" in txt})

    # 2) body charge-type index — banner-scoped, heading-styled only -----------
    index = []
    cur_banner = None
    for p, txt, pg in paras:
        if not txt:
            continue
        b = banner_of(txt)
        if b and is_heading(p):
            cur_banner = b
            continue
        # A charge-type heading under a known banner. The RELIABLE signal is the
        # leading section number (N.N[.N...]) followed by a Title — NOT bold/style,
        # which varies across RRs (RR623 headings are bold; RR750's are plain).
        # Separator may be a space, a lost tab, or nothing ("4.5.12Revenue...").
        # Guard against prose: heading lines are short and have no sentence period.
        m = re.match(r'^(\d+\.\d+(?:\.\d+)*)\s*([A-Za-z“"\'(].*)', txt)
        is_short = len(txt) <= 90 and txt.count(". ") == 0 and not txt.endswith(".")
        looks_like_heading = is_heading(p) or is_short
        if m and cur_banner and looks_like_heading:
            index.append({"banner": cur_banner, "section": m.group(1),
                          "title": m.group(2).strip(), "is_new": heading_is_new(p),
                          "page": pg})

    # RR classification: does this RR touch settlement charge codes at all?
    all_text = " ".join(t for _, t, _ in paras)
    determinants = sorted(set(re.findall(r'#[A-Z][A-Za-z0-9]{3,}', all_text)))
    checked_boxes = []
    for _, t, _ in paras:
        if t.startswith("☒"):
            for kw in ("Tariff", "Market Protocols", "Operating Criteria"):
                if kw in t[:40]:
                    checked_boxes.append(kw)
    checked_boxes = sorted(set(checked_boxes))

    mp_checked = "Market Protocols" in checked_boxes
    has_determinants = len(determinants) > 0

    # Is the RR *about* settlement behavior even without a # determinant?
    # Judge from the HEADER (title + essential points), where the RR states its
    # core subject — not incidental mentions deep in the body. Core terms are the
    # settlement mechanics an RR would be built around.
    header_paras = [t for _, t, _ in paras[:40] if t]
    header = " ".join(header_paras).lower()
    CORE_TERMS = ["calibration", "uninstructed resource deviation", " urd",
                  "make whole", "make-whole", "billing determinant",
                  "revenue neutrality", "settlement charge"]
    core_hits = sum(header.count(term) for term in CORE_TERMS)
    touches_ae = "attachment ae" in all_text.lower()

    if has_determinants or mp_checked:
        rr_class = "SETTLEMENT_CALC"          # formulas/determinants to extract
    elif core_hits >= 2 and touches_ae:
        rr_class = "SETTLEMENT_RELEVANT"      # settlement impact via Tariff prose (review!)
    else:
        rr_class = "TARIFF_GOVERNANCE"        # definitions / rate schedules / prose only

    # 3) reconciliation --------------------------------------------------------
    # Keep only real charge-type headings: those under Market Protocols/SUG, OR
    # whose section body contains a '#'-determinant (settlement formula). This
    # drops legal-appendix sections (SSR Agreement terms, etc.) that are bold-
    # numbered but carry no settlement charge type.
    def section_has_determinant(sec):
        capture = False
        for p, txt, pg in paras:
            m = re.match(r'^(\d+\.\d+(?:\.\d+)*)\s', txt)
            if m and m.group(1) == sec:
                capture = True; continue
            if capture:
                if m:  # next numbered heading -> stop
                    break
                if re.search(r'#[A-Z][A-Za-z0-9]+', txt) or "[[EQ" in para_marked(p):
                    return True
        return False

    filtered = []
    for i in index:
        is_mp = i["banner"].startswith("Market Protocols")
        if is_mp or section_has_determinant(i["section"]):
            filtered.append(i)
    index = filtered
    body_secs = {i["section"] for i in index}
    listed_secs = {i["section"] for i in impacted if i["document"].startswith("Market")}
    missing_from_body = sorted(listed_secs - body_secs)
    found_not_listed = sorted(
        {i["section"] for i in index if i["section"].startswith("4.5")} - listed_secs
    )

    # Class-aware status:
    #  - SETTLEMENT_CALC + missing sections      -> HARD_FAIL (stop, manual review)
    #  - SETTLEMENT_CALC + all listed found      -> PASS
    #  - SETTLEMENT_CALC but nothing found at all -> HARD_FAIL (suspicious: MP checked
    #                                                but no charge type parsed)
    #  - TARIFF_GOVERNANCE (no # determinants)   -> NO_CHARGE_CODES (correct, not an error;
    #                                                route to non-settlement story track)
    if rr_class == "TARIFF_GOVERNANCE":
        status = "NO_CHARGE_CODES"
        hard_fail = False
    elif rr_class == "SETTLEMENT_RELEVANT":
        status = "REVIEW_SETTLEMENT_PROSE"   # settlement impact but no # determinant
        hard_fail = False
    elif missing_from_body:
        status = "HARD_FAIL"
        hard_fail = True
    elif mp_checked and not index:
        status = "HARD_FAIL"   # MP was checked but we parsed zero charge types
        hard_fail = True
    else:
        status = "PASS"
        hard_fail = False

    # 4) marked text -----------------------------------------------------------
    lines = []
    for p, txt, pg in paras:
        if not txt:
            continue
        mk = para_marked(p).strip()
        if txt.upper() in banners_up:
            lines.append(f"\n===== {norm_banner(txt)} =====")
        elif re.match(r'^\d+\.\d+', txt):
            lines.append(f"\n## {mk}")
        else:
            lines.append(mk)
    marked = "\n".join(lines)

    # RR id/title from the first heading-ish line
    rr_id = None; rr_title = None
    for _, t, _ in paras[:8]:
        m = re.match(r'^(RR\s?\d+)\b', t.replace("–", "-"))
        if m:
            rr_id = m.group(1).replace(" ", "")
            rr_title = t
            break
    total_pages = max((pg for _, _, pg in paras), default=1)

    # Citations: RR-internal (reliable, page-anchored) + CUF/SUF (passed in)
    rr_citations = []
    for i in index:
        rr_citations.append({
            "document": f"{rr_id or 'RR'} Recommendation Report",
            "reference": f"§{i['section']} {i['title']}",
            "page": i.get("page"),
            "sharepoint_url": sharepoint_url,
            "source": "RR docx (page-anchored)",
        })
    # CUF/SUF refs are supplied by the caller (from meeting decks); we pass them
    # through verbatim and label them so they are never mistaken for auto-extracted.
    meeting_citations = cuf_suf_refs or []

    report = {
        "source_file": docx_path,
        "rr_id": rr_id,
        "rr_title": rr_title,
        "sharepoint_url": sharepoint_url,
        "total_pages": total_pages,
        "rr_class": rr_class,
        "checked_impacted_boxes": checked_boxes,
        "determinants_found": determinants,
        "impacted_checklist": impacted,
        "charge_type_index": index,
        "citations": {
            "rr_document": rr_citations,
            "cuf_suf_meetings": meeting_citations,
        },
        "reconciliation": {
            "listed_market_protocol_sections": sorted(listed_secs),
            "body_heading_sections": sorted(body_secs),
            "missing_from_body": missing_from_body,
            "found_not_listed": found_not_listed,
            "status": status,
        },
        "flags": {
            "has_ins": "{{INS:" in marked,
            "has_del": "{{DEL:" in marked,
            "has_eq":  "[[EQ:" in marked,
        },
    }
    return report, marked, hard_fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--out-json")
    ap.add_argument("--out-text")
    ap.add_argument("--banners", default=",".join(DEFAULT_BANNERS),
                    help="comma-separated banner list (override auto-detect)")
    ap.add_argument("--sharepoint-url", default=None,
                    help="SharePoint URL for this RR (echoed into citations)")
    ap.add_argument("--cuf-suf-json", default=None,
                    help="path to a JSON file of CUF/SUF meeting citations to attach verbatim")
    a = ap.parse_args()

    banners = [b.strip() for b in a.banners.split(",") if b.strip()]
    cuf_suf = None
    if a.cuf_suf_json:
        cuf_suf = json.load(open(a.cuf_suf_json))
    report, marked, hard_fail = extract(a.file, banners,
                                        sharepoint_url=a.sharepoint_url,
                                        cuf_suf_refs=cuf_suf)

    if a.out_json:
        open(a.out_json, "w").write(json.dumps(report, indent=2, ensure_ascii=False))
    if a.out_text:
        open(a.out_text, "w", encoding="utf-8").write(marked)

    # Human-readable stderr summary
    r = report["reconciliation"]
    print(f"[reconcile] status={r['status']}", file=sys.stderr)
    print(f"  listed : {r['listed_market_protocol_sections']}", file=sys.stderr)
    print(f"  body   : {r['body_heading_sections']}", file=sys.stderr)
    if r["missing_from_body"]:
        print(f"  MISSING FROM BODY (hard-fail): {r['missing_from_body']}", file=sys.stderr)
    if r["found_not_listed"]:
        print(f"  found-not-listed (review): {r['found_not_listed']}", file=sys.stderr)

    # Hard-fail => non-zero exit so a standalone CLI run STOPS this RR for manual
    # review. When extract() is called in-process from pipeline.py, callers read
    # the returned `hard_fail` boolean instead of a process exit code.
    sys.exit(2 if hard_fail else 0)


if __name__ == "__main__":
    main()
