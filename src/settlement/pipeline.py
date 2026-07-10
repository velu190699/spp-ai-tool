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
import tempfile
from typing import Any

from src.settlement import rr_structure
from src.settlement.settlement_report import build
from src.summaries.report_engine import ReportEngine, build_engine

LOGGER = logging.getLogger(__name__)

HERE = pathlib.Path(__file__).parent
PROMPT_PATH = HERE / "rr_extraction_prompt.md"


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


def call_llm(engine: ReportEngine, marked: str, report: dict, url: str | None) -> dict:
    """Only for SETTLEMENT_CALC + PASS. Feeds the extraction prompt + marked text
    + charge-type index (the mandatory checklist) to the configured LLM engine."""
    instruction = PROMPT_PATH.read_text(encoding="utf-8")
    checklist = json.dumps(report["charge_type_index"], ensure_ascii=False)
    context = (f"SHAREPOINT_URL: {url}\n"
               f"CHARGE_TYPE_CHECKLIST (one story per entry): {checklist}\n\n"
               f"=== RR DOCUMENT (equations + redlines preserved) ===\n{marked}")
    try:
        return engine.generate(instruction, context)
    except Exception as exc:  # engine already raises a typed EngineError; keep the pipeline going
        LOGGER.warning("LLM story generation failed for %s: %s", report.get("rr_id"), exc)
        return {"stories": [], "warning": f"LLM call failed: {exc}"}


def process_one(docx_path: str, url: str | None, engine: ReportEngine | None) -> dict[str, Any]:
    report, marked, _hard_fail = rr_structure.extract(docx_path, rr_structure.DEFAULT_BANNERS, sharepoint_url=url)
    rr = report.get("rr_id", os.path.basename(docx_path))
    cls = report["rr_class"]
    status = report["reconciliation"]["status"]
    LOGGER.info("[%s] class=%s status=%s", rr, cls, status)
    stories = None
    if engine is not None and cls == "SETTLEMENT_CALC" and status == "PASS":
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
) -> str:
    """Run the pipeline over local files and/or SharePoint links and write the xlsx.

    `engine` is None for a classification-only pass (no LLM calls, no Jira
    stories) — used for a fast triage run or in tests via StubEngine.
    """
    jobs: list[tuple[str, str | None]] = [(f, None) for f in (files or [])]
    if links:
        token = graph_token(tenant, client_id, client_secret)
        for url in links:
            tmp = tempfile.mkdtemp()
            dest = os.path.join(tmp, "rr.docx")
            resolve_and_download(url, token, dest)
            jobs.append((dest, url))

    results = [process_one(docx, url, engine) for docx, url in jobs]
    build(results, out_path)
    LOGGER.info("Wrote %s", out_path)
    return out_path


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
