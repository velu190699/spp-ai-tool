from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from config import (
    CUF_QUERY,
    PROTOCOL_QUERY,
    RR_MASTER_QUERY,
    SHAREPOINT_FOLDERS,
    SUF_QUERY,
    ensure_runtime_dirs,
    load_config,
)
from src.browser.download_utils import sha256_file
from src.browser.spp_client import SppClient, SppDocument, rr_search_query_from_url
from src.documents.excel_parser import RRRecord, read_open_rrs
from src.documents.pdf_parser import parse_pdf
from src.documents.rr_extractor import merge_mentions
from src.documents.zip_utils import extract_first_recommendation_report, extract_pdfs
from src.notifications.notifier import log_slack_draft
from src.sharepoint.sharepoint_client import LocalSharePointClient
from src.state.metadata_store import MetadataStore
from src.summaries.summarizer import build_run_summary

LOGGER = logging.getLogger(__name__)


def setup_logging(logs_dir: Path, level: str) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8")],
    )
    logging.getLogger("pypdf").setLevel(logging.ERROR)


def title_contains(*needles: str):
    lowered = [needle.lower() for needle in needles]
    return lambda doc: all(needle in doc.title.lower() for needle in lowered)


def extension_is(*extensions: str):
    lowered = tuple(ext.lower() for ext in extensions)
    return lambda doc: doc.filename.lower().endswith(lowered)


def and_match(*matchers):
    return lambda doc: all(matcher(doc) for matcher in matchers)


def document_summary(document: SppDocument | None) -> dict[str, Any] | None:
    if not document:
        return None
    return {
        "document_id": document.document_id,
        "title": document.title,
        "filename": document.filename,
        "url": document.url,
        "size": document.size_label,
    }


def get_or_download(
    *,
    family: str,
    document: SppDocument,
    client: SppClient,
    state: MetadataStore,
    downloads_dir: Path,
    dry_run: bool,
    warnings: list[str],
) -> tuple[Path | None, bool]:
    # Business duplicate identity is intentionally SPP document ID + filename.
    # A changed hash for the same identity is reported, but it is not treated as
    # a new material in v1.
    existing = state.check_document(document.document_id, document.filename)
    cached_path = state.latest_local_path(document.document_id, document.filename)
    if not existing.is_new and cached_path:
        LOGGER.info("%s already tracked: %s", family, document.filename)
        return cached_path, False
    if dry_run:
        LOGGER.info("Dry-run: would download %s", document.url)
        return None, existing.is_new

    local_path = client.download(document, downloads_dir / family)
    file_hash = sha256_file(local_path)
    post_download = state.check_document(document.document_id, document.filename, file_hash)
    if post_download.hash_changed:
        warning = f"{family}: same SPP ID/name has changed hash; keeping existing identity only: {document.filename}"
        warnings.append(warning)
        LOGGER.warning(warning)
    state.record_document(
        document.document_id,
        document.filename,
        {
            "family": family,
            "title": document.title,
            "url": document.url,
            "sha256": file_hash,
            "local_path": str(local_path),
        },
    )
    return local_path, existing.is_new


def require_document(name: str, document: SppDocument | None) -> SppDocument:
    if not document:
        raise RuntimeError(f"Required SPP document not found: {name}")
    return document


def process_pdf_family(
    *,
    family: str,
    files: list[Path],
    sharepoint: LocalSharePointClient,
    warnings: list[str],
    dry_run: bool,
) -> dict[str, Any]:
    # CUF and SUF are the only document families that feed the RR relevance
    # pipeline in v1. Protocol archives are retained separately and not parsed.
    all_mentions = []
    stored = []
    for pdf_path in files:
        parsed = parse_pdf(pdf_path)
        warnings.extend(parsed.warnings)
        all_mentions.extend(parsed.rr_mentions)
        if not dry_run:
            stored_file = sharepoint.store_file(pdf_path, SHAREPOINT_FOLDERS[family])
            stored.append(str(stored_file.destination))
    return {"stored": stored, "mentions": merge_mentions(all_mentions)}


def build_relevant_rrs(open_rrs: dict[str, RRRecord], mentioned: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    # Relevant RRs are the intersection of RRs mentioned in CUF/SUF materials
    # and RRs currently marked Open in the RR Master List.
    relevant = []
    for rr_number, mention_data in sorted(mentioned.items(), key=lambda item: int(item[0])):
        record = open_rrs.get(rr_number)
        if not record:
            continue
        relevant.append(
            {
                "rr_number": rr_number,
                "title": record.title,
                "status": record.status,
                "primary_working_group": record.primary_working_group,
                "impacted_documents": record.impacted_documents,
                "dates": mention_data.get("dates", []),
                "sources": mention_data.get("sources", []),
                "search_url": record.search_url,
            }
        )
    return relevant


def process_recommendation_reports(
    *,
    relevant_rrs: list[dict[str, Any]],
    client: SppClient,
    state: MetadataStore,
    config,
    sharepoint: LocalSharePointClient,
    dry_run: bool,
    warnings: list[str],
    skipped: list[str],
) -> list[dict[str, Any]]:
    stored_reports = []
    for rr in relevant_rrs:
        # The RR Master List hyperlink is a search URL such as ?q=rr782. Use it
        # first, then fall back to a normalized rr<number> query.
        query = rr_search_query_from_url(rr.get("search_url", "")) or f"rr{rr['rr_number']}"
        document = client.latest_document(
            query,
            and_match(title_contains(f"RR{rr['rr_number']}"), extension_is(".zip")),
            allow_site_search=True,
        )
        if not document:
            skipped.append(f"RR{rr['rr_number']}: no RR package found")
            continue
        zip_path, _ = get_or_download(
            family="recommendation_reports",
            document=document,
            client=client,
            state=state,
            downloads_dir=config.downloads_dir,
            dry_run=dry_run,
            warnings=warnings,
        )
        if dry_run or zip_path is None:
            stored_reports.append({"rr_number": rr["rr_number"], "package": document_summary(document), "dry_run": True})
            continue
        target_dir = config.extracted_dir / "recommendation_reports" / f"rr{rr['rr_number']}"
        # Store only the first exact Recommendation Report filename. Other Word
        # files in the RR package are not substitutes for this v1 contract.
        report = extract_first_recommendation_report(zip_path, rr["rr_number"], target_dir)
        if not report:
            warning = f"RR{rr['rr_number']}: no exact Recommendation Report docx found in package"
            warnings.append(warning)
            LOGGER.warning(warning)
            continue
        stored_file = sharepoint.store_file(report, SHAREPOINT_FOLDERS["recommendation_reports"])
        stored_reports.append(
            {
                "rr_number": rr["rr_number"],
                "package": document_summary(document),
                "stored": str(stored_file.destination),
            }
        )
    return stored_reports


def run(dry_run: bool) -> int:
    config = load_config()
    ensure_runtime_dirs(config)
    setup_logging(config.logs_dir, config.logging_level)
    state = MetadataStore(config.state_file)
    client = SppClient()
    sharepoint = LocalSharePointClient(config.sharepoint_mirror_dir)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    warnings: list[str] = []
    skipped: list[str] = []
    discovered: dict[str, Any] = {}

    rr_master_doc = require_document(
        "RR Master List",
        client.latest_document(RR_MASTER_QUERY, and_match(title_contains("RR Master List"), extension_is(".xlsx"))),
    )
    cuf_doc = require_document(
        "CUF Meeting Materials",
        client.latest_document(CUF_QUERY, and_match(title_contains("CUF Meeting Materials"), extension_is(".zip"))),
    )
    suf_doc = require_document(
        "SUF Meeting Materials",
        client.latest_document(SUF_QUERY, and_match(title_contains("SUF Meeting Materials"), extension_is(".pdf"))),
    )
    protocol_doc = client.latest_document(
        PROTOCOL_QUERY,
        and_match(title_contains("Integrated Marketplace Protocols", "Active Version"), extension_is(".zip")),
    )

    discovered.update(
        {
            "rr_master_list": document_summary(rr_master_doc),
            "cuf": document_summary(cuf_doc),
            "suf": document_summary(suf_doc),
            "protocol": document_summary(protocol_doc),
        }
    )

    rr_master_path, _ = get_or_download(
        family="rr_master_list",
        document=rr_master_doc,
        client=client,
        state=state,
        downloads_dir=config.downloads_dir,
        dry_run=dry_run,
        warnings=warnings,
    )
    if dry_run:
        open_rrs = {}
    else:
        if rr_master_path is None:
            raise RuntimeError("RR Master List path unavailable")
        open_rrs = read_open_rrs(rr_master_path)
        sharepoint.store_file(rr_master_path, SHAREPOINT_FOLDERS["rr_master_list"])

    cuf_path, cuf_is_new = get_or_download(
        family="cuf",
        document=cuf_doc,
        client=client,
        state=state,
        downloads_dir=config.downloads_dir,
        dry_run=dry_run,
        warnings=warnings,
    )
    suf_path, suf_is_new = get_or_download(
        family="suf",
        document=suf_doc,
        client=client,
        state=state,
        downloads_dir=config.downloads_dir,
        dry_run=dry_run,
        warnings=warnings,
    )

    if protocol_doc:
        # Protocol ZIPs are source archives only in v1: retain the raw ZIP, do
        # not extract content, and do not include it in summaries.
        get_or_download(
            family="protocol",
            document=protocol_doc,
            client=client,
            state=state,
            downloads_dir=config.downloads_dir,
            dry_run=dry_run,
            warnings=warnings,
        )
    else:
        warnings.append("Integrated Marketplace Protocol Active Version not found; continuing")

    mentioned: dict[str, dict[str, Any]] = {}
    family_outputs: dict[str, Any] = {}
    if not dry_run:
        if cuf_path and cuf_is_new:
            # CUF is published as a ZIP; every PDF inside it is parsed because
            # RR mentions may appear in any agenda/material attachment.
            cuf_pdfs = extract_pdfs(cuf_path, config.extracted_dir / "cuf" / cuf_doc.document_id)
            family_outputs["cuf"] = process_pdf_family(
                family="cuf", files=cuf_pdfs, sharepoint=sharepoint, warnings=warnings, dry_run=dry_run
            )
        elif cuf_path:
            skipped.append(f"CUF already processed: {cuf_doc.filename}")
        if suf_path and suf_is_new:
            family_outputs["suf"] = process_pdf_family(
                family="suf", files=[suf_path], sharepoint=sharepoint, warnings=warnings, dry_run=dry_run
            )
        elif suf_path:
            skipped.append(f"SUF already processed: {suf_doc.filename}")

        for output in family_outputs.values():
            for rr_number, data in output.get("mentions", {}).items():
                entry = mentioned.setdefault(rr_number, {"rr_number": rr_number, "dates": [], "sources": [], "contexts": []})
                for key in ("dates", "sources", "contexts"):
                    for item in data.get(key, []):
                        if item not in entry[key]:
                            entry[key].append(item)

    relevant_rrs = build_relevant_rrs(open_rrs, mentioned)
    reports = [] if dry_run else process_recommendation_reports(
        relevant_rrs=relevant_rrs,
        client=client,
        state=state,
        config=config,
        sharepoint=sharepoint,
        dry_run=dry_run,
        warnings=warnings,
        skipped=skipped,
    )
    discovered["recommendation_reports"] = reports

    log_slack_draft(relevant_rrs, warnings)
    run_summary = build_run_summary(
        run_id=run_id,
        dry_run=dry_run,
        discovered=discovered,
        relevant_rrs=relevant_rrs,
        warnings=warnings,
        skipped=skipped,
    )

    report_path = config.reports_dir / f"run-{run_id}.json"
    relevant_path = config.reports_dir / f"relevant-rrs-{run_id}.json"
    if not dry_run:
        report_path.write_text(json.dumps(run_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        relevant_path.write_text(json.dumps(relevant_rrs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        state.append_run({"run_id": run_id, "report_path": str(report_path), "relevant_count": len(relevant_rrs)})
        state.save()
    else:
        LOGGER.info("Dry-run summary:\n%s", json.dumps(run_summary, indent=2, sort_keys=True))

    LOGGER.info("Run complete: %s relevant RRs", len(relevant_rrs))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SPP RR automation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run the automation")
    run_parser.add_argument("--dry-run", action="store_true", help="Discover documents without downloading or storing files")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "run":
        return run(dry_run=args.dry_run)
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
