#!/usr/bin/env python3
"""
pipeline.py — end-to-end SPP RR settlement pipeline.

Technical: for each RR (SharePoint share link OR local .docx):
  1. resolve link -> download .docx via Microsoft Graph (skipped if a local file
     was given instead)
  2. rr_structure.extract() -> structured report (charge-type index, citations,
     page numbers, class, reconciliation) + marked text (equations + redlines
     preserved) — called in-process, not shelled out, since both modules now
     live in the same package.
  3. gate on class/status:
        SETTLEMENT_CALC + PASS      -> call the LLM with rr_extraction_prompt.md
        SETTLEMENT_CALC + HARD_FAIL -> mark manual-review, skip the LLM call
        SETTLEMENT_RELEVANT         -> mark review (prose change), skip the LLM call
        TARIFF_GOVERNANCE           -> out of scope, skip
  4. merge everything -> SPP_RR_Report_Summary.xlsx (+ Settlement Stories sheet)

The LLM call reuses src/summaries/report_engine.py's ReportEngine interface
(same ClaudeCodeEngine/StubEngine, same report.engine/claude_code_binary/model
config as the Market Changes Summary report) instead of a second ad hoc
subprocess convention.

Business: an RR does not become a development task just because SPP published
it — most of the value here is triage. SETTLEMENT_CALC RRs are the ones that
change a charge code PCI's software computes; those get Jira-ready stories.
SETTLEMENT_RELEVANT and TARIFF_GOVERNANCE RRs are routed to a human instead of
silently dropped, because a wrong "out of scope" call is the same production
risk as a missed charge code.

USAGE
  # local files (fastest to validate):
  python -m src.settlement.pipeline --files RR623.docx RR748.docx --out report.xlsx --call-claude
  # from SharePoint links (needs SHAREPOINT_TENANT_ID / _CLIENT_ID / _CLIENT_SECRET):
  python -m src.settlement.pipeline --links links.txt --out report.xlsx --call-claude
Omit --call-claude for a fast classification + citation triage pass without story generation.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import pathlib
import re
import tempfile
from typing import Any

from src.settlement import pagination, rr_structure
from src.settlement.settlement_report import build
from src.summaries.report_engine import ReportEngine, build_engine

LOGGER = logging.getLogger(__name__)

HERE = pathlib.Path(__file__).parent
PROMPT_PATH = HERE / "rr_extraction_prompt.md"
# SME-maintained PCI vocabulary (determinant->calc-class terms, team
# conventions like "shadow calculation"); injected into the prompt when filled.
VOCAB_PATH = HERE.parent.parent / "config" / "pci_vocabulary.yaml"


def graph_token(tenant: str, client_id: str, client_secret: str) -> str:
    import msal
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant}",
        client_credential=client_secret)
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"Graph auth failed: {result.get('error_description', result)}")
    return result["access_token"]


def resolve_and_download(url: str, token: str, dest: str) -> str:
    import requests
    enc = "u!" + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    meta = requests.get(f"https://graph.microsoft.com/v1.0/shares/{enc}/driveItem",
                        headers={"Authorization": f"Bearer {token}"}).json()
    drive, item = meta["parentReference"]["driveId"], meta["id"]
    content = requests.get(
        f"https://graph.microsoft.com/v1.0/drives/{drive}/items/{item}/content",
        headers={"Authorization": f"Bearer {token}"}, allow_redirects=True).content
    open(dest, "wb").write(content)
    return meta.get("name", "")


def _vocabulary_block() -> str:
    """SME-maintained PCI vocabulary, or "" when the file is absent/empty."""
    try:
        text = VOCAB_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    # Skip when the file is only comments/blank — nothing to inject yet.
    meaningful = [l for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    return text if meaningful else ""


def call_llm(engine: ReportEngine, marked: str, report: dict, url: str | None) -> dict:
    """Only for SETTLEMENT_CALC + PASS. Feeds the extraction prompt + marked text
    + charge-type index (the mandatory checklist) to the configured LLM engine."""
    instruction = PROMPT_PATH.read_text(encoding="utf-8")
    version_match = re.match(r"PROMPT_VERSION:\s*(\S+)", instruction)
    prompt_version = version_match.group(1) if version_match else "unversioned"
    # Stories are scoped to the Market Protocols / Settlement User Guide
    # sections ONLY (the ones with formulas + determinants) — Tariff and other
    # documents are context, never story items (Elizabeth, 2026-07-15).
    mp_index = [i for i in report["charge_type_index"] if i["banner"].startswith("Market")]
    checklist = json.dumps(mp_index, ensure_ascii=False)
    citations = json.dumps(report.get("citations", {}).get("rr_document", []), ensure_ascii=False)
    initiative = report.get("market_initiative", "")
    initiative_cite = report.get("market_initiative_citation", "")
    initiative_line = f"{initiative} [{initiative_cite}]" if initiative and initiative_cite else (initiative or "not stated")
    images = sorted(report.get("formula_images", {}))
    vocab = _vocabulary_block()
    context = (f"SHAREPOINT_URL: {url}\n"
               f"MARKET_INITIATIVE (verbatim from the CUF/SUF slide, with its source): {initiative_line}\n"
               f"MARKET_PROTOCOLS_VERSION (Settlement User Guide version from the Impacted-Documents block): "
               f"{report.get('protocol_version') or 'not stated'}\n"
               f"PROTOCOLS_FOLDER (synced SharePoint copy of the Marketplace Protocols / Settlement User "
               f"Guide for cross-linking): {report.get('protocols_folder_url') or 'not available'}\n"
               f"FORMULA_IMAGES (extracted PNGs referenced by [[EQ-IMG: ...]] markers; in SPP RRs these "
               f"are usually a lone summation operator whose operands are the surrounding text): "
               f"{', '.join(images) or 'none'}\n"
               f"CITATIONS (page-anchored references into the RR — use these page numbers verbatim): {citations}\n"
               + (f"\nPCI VOCABULARY (SME-maintained; use these terms/conventions in stories):\n{vocab}\n" if vocab else "")
               + f"CHARGE_TYPE_CHECKLIST (one story per entry; Market Protocols/SUG only): {checklist}\n\n"
               f"=== RR DOCUMENT (equations + redlines preserved) ===\n{marked}")
    try:
        stories = engine.generate(instruction, context)
    except Exception as exc:  # engine already raises a typed EngineError; keep the pipeline going
        LOGGER.warning("LLM story generation failed for %s: %s", report.get("rr_id"), exc)
        return {"stories": [], "warning": f"LLM call failed: {exc}"}
    # Reproducibility: every persisted story set records which prompt produced it.
    if isinstance(stories, dict):
        stories["prompt_version"] = prompt_version
        n_stories = len(stories.get("jira_stories") or [])
        if n_stories > 1:  # ONE STORY PER RR is a prompt hard rule (Eduardo, 2026-07-16)
            LOGGER.warning("[%s] prompt contract violated: %d stories returned, expected 1",
                           report.get("rr_id"), n_stories)
    return stories


def process_one(
    docx_path: str,
    url: str | None,
    engine: ReportEngine | None,
    initiatives: dict[str, str] | None = None,
    images_root: str | None = None,
    protocols_url: str = "",
) -> dict[str, Any]:
    report, marked, _hard_fail = rr_structure.extract(docx_path, rr_structure.DEFAULT_BANNERS, sharepoint_url=url)
    rr = report.get("rr_id", os.path.basename(docx_path))
    cls = report["rr_class"]
    status = report["reconciliation"]["status"]
    # Link the RR to its market initiative (named on the CUF/SUF slide, not in
    # the RR document itself). Verbatim slide wording + file/page citation so
    # every initiative claim in the outputs is checkable against the slide.
    rr_digits = "".join(ch for ch in str(rr) if ch.isdigit())
    entry = (initiatives or {}).get(rr_digits) or {}
    report["market_initiative"] = entry.get("label", "")
    report["market_initiative_citation"] = entry.get("citation", "")
    report["protocols_folder_url"] = protocols_url
    LOGGER.info("[%s] class=%s status=%s initiative=%s", rr, cls, status, report["market_initiative"] or "-")

    # Legacy MathType equations render as images; extract them as PNGs so the
    # [[EQ-IMG: imageN.wmf]] markers in the text have something to point at.
    report["formula_images"] = {}
    if images_root and cls == "SETTLEMENT_CALC" and "[[EQ-IMG:" in marked:
        img_dir = os.path.join(images_root, rr_digits and f"rr{rr_digits}" or "rr")
        report["formula_images"] = rr_structure.extract_formula_images(docx_path, img_dir)
        LOGGER.info("[%s] extracted %d formula images -> %s", rr, len(report["formula_images"]), img_dir)

    # Some RR docx files carry no saved pagination (every section reports page
    # 1). Page-anchored citations are a hard requirement, so render the docx
    # to PDF via headless Word and take the true page numbers from there.
    if images_root and cls == "SETTLEMENT_CALC":
        try:
            pagination.repaginate(report, docx_path, os.path.join(images_root, "..", "rendered"))
        except Exception as exc:  # pagination must never sink the pipeline
            LOGGER.warning("[%s] repagination failed: %s", rr, exc)

    stories = None
    if engine is not None and cls == "SETTLEMENT_CALC" and status in ("PASS", "PASS_NUMBERING_MAPPED"):
        stories = call_llm(engine, marked, report, url)
    return {"report": report, "stories": stories}


def run(
    *,
    files: list[str] | None = None,
    links: list[str] | None = None,
    out_path: str,
    engine: ReportEngine | None = None,
    tenant: str = "",
    client_id: str = "",
    client_secret: str = "",
    initiatives: dict[str, str] | None = None,
    protocols_url: str = "",
) -> tuple[str, list[dict[str, Any]]]:
    """Run the pipeline over local files and/or SharePoint links and write the xlsx.

    Returns ``(out_path, results)`` so callers can feed the per-RR results into
    further outputs (e.g. the Jira story workbook) without re-parsing.

    `engine` is None for a classification-only pass (no LLM calls, no Jira
    stories) — used for a fast triage run or in tests via StubEngine.
    `initiatives` maps RR digits ("728") to the market initiative named on the
    CUF/SUF slide that mentioned it (from the run pipeline's cross-reference).
    """
    jobs: list[tuple[str, str | None]] = [(f, None) for f in (files or [])]
    if links:
        token = graph_token(tenant, client_id, client_secret)
        for url in links:
            tmp = tempfile.mkdtemp()
            dest = os.path.join(tmp, "rr.docx")
            resolve_and_download(url, token, dest)
            jobs.append((dest, url))

    images_root = os.path.join(os.path.dirname(os.path.abspath(out_path)), "images")
    results = [process_one(docx, url, engine, initiatives, images_root, protocols_url) for docx, url in jobs]
    build(results, out_path)
    LOGGER.info("Wrote %s", out_path)

    # Persist every LLM-generated story set as JSON next to the report — the
    # stories must survive the run even when workbook generation is paused,
    # both for review and so a later workbook pass can reuse them without a
    # second (expensive) LLM call.
    stories_dir = pathlib.Path(out_path).parent / "stories"
    for res in results:
        if res.get("stories"):
            stories_dir.mkdir(parents=True, exist_ok=True)
            rr = str(res["report"].get("rr_id", "RR")).replace(" ", "")
            path = stories_dir / f"{rr}-{pathlib.Path(out_path).stem}.json"
            path.write_text(json.dumps(res["stories"], indent=2, ensure_ascii=False), encoding="utf-8")
            LOGGER.info("[%s] stories JSON written: %s", rr, path)
    return out_path, results


def read_links_file(path: str) -> list[str]:
    with open(path, encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip() and not line.startswith("#")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", help="local .docx paths")
    ap.add_argument("--links", help="text file of SharePoint share URLs")
    ap.add_argument("--out", default="SPP_RR_Report_Summary.xlsx")
    ap.add_argument("--call-claude", action="store_true",
                    help="actually invoke the LLM engine for SETTLEMENT_CALC + PASS RRs")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    engine = build_engine("claude_code") if args.call_claude else None
    run(
        files=args.files,
        links=read_links_file(args.links) if args.links else None,
        out_path=args.out,
        engine=engine,
        tenant=os.getenv("SHAREPOINT_TENANT_ID", ""),
        client_id=os.getenv("SHAREPOINT_CLIENT_ID", ""),
        client_secret=os.getenv("SHAREPOINT_CLIENT_SECRET", ""),
    )


if __name__ == "__main__":
    main()
