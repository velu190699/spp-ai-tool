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
    SUF_QUERY,
    ensure_runtime_dirs,
    load_config,
)
from src.browser.download_utils import sha256_file
from src.browser.spp_client import SppClient, SppDocument, rr_search_query_from_url
from src.documents.excel_parser import RRRecord, read_open_rrs
from src.documents.local_source import SourceEdition, latest_cuf_edition, latest_suf_edition
from src.documents.pdf_parser import parse_pdf
from src.documents.rr_extractor import merge_mentions
from src.documents.zip_utils import extract_first_recommendation_report, extract_pdfs
from src.notifications.notifier import log_slack_draft
from src.state.metadata_store import MetadataStore
from src.summaries.html_renderer import render_report
from src.summaries.report_builder import DocumentText, build_report
from src.summaries.report_engine import build_engine
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
    redownload_on_hash_change: bool = False,
) -> tuple[Path | None, bool]:
    existing = state.check_document(document.document_id, document.filename)
    cached_path = state.latest_local_path(document.document_id, document.filename)

    if not existing.is_new and cached_path:
        if not redownload_on_hash_change:
            LOGGER.info("%s already tracked: %s", family, document.filename)
            return cached_path, False
        # For documents like RR Master List: download to a temp path,
        # compare hash, and only keep it if the content actually changed.
        if dry_run:
            LOGGER.info("Dry-run: would check hash for %s", document.url)
            return cached_path, False
        temp_path = client.download(document, downloads_dir)
        new_hash = sha256_file(temp_path)
        old_hash = existing.existing.get("sha256") if existing.existing else None
        if old_hash and new_hash == old_hash:
            temp_path.unlink()  # same content, discard
            LOGGER.info("%s content unchanged (hash match): %s", family, document.filename)
            return cached_path, False
        # Content changed — keep new file, record as updated
        LOGGER.info("%s content changed (new hash): %s", family, document.filename)
        state.record_document(
            document.document_id,
            document.filename,
            {
                "family": family,
                "title": document.title,
                "url": document.url,
                "sha256": new_hash,
                "local_path": str(temp_path),
            },
        )
        return temp_path, True  # is_new=True signals "treat as updated"

    if dry_run:
        LOGGER.info("Dry-run: would download %s", document.url)
        return None, existing.is_new

    local_path = client.download(document, downloads_dir)
    file_hash = sha256_file(local_path)
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
            stored.append(str(pdf_path))
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
            downloads_dir=config.recommendation_reports_dir,
            dry_run=dry_run,
            warnings=warnings,
        )
        # Skip if the docx already exists on disk
        existing_docx = config.recommendation_reports_dir / f"rr{rr['rr_number']}" / f"RR{rr['rr_number']} Recommendation Report.docx"
        if existing_docx.exists() and not dry_run:
            LOGGER.info("RR%s: Recommendation Report already on disk, skipping", rr['rr_number'])
            stored_reports.append({"rr_number": rr["rr_number"], "stored": str(existing_docx), "skipped": True})
            continue
        if dry_run or zip_path is None:
            stored_reports.append({"rr_number": rr["rr_number"], "package": document_summary(document), "dry_run": True})
            continue
        target_dir = config.recommendation_reports_dir / f"rr{rr['rr_number']}"
        # Store only the first exact Recommendation Report filename. Other Word
        # files in the RR package are not substitutes for this v1 contract.
        report = extract_first_recommendation_report(zip_path, rr["rr_number"], target_dir)
        if report and zip_path.exists():
            zip_path.unlink()  # delete the zip after extracting
        if not report:
            warning = f"RR{rr['rr_number']}: no exact Recommendation Report docx found in package"
            warnings.append(warning)
            LOGGER.warning(warning)
            continue
        stored_reports.append(
            {
                "rr_number": rr["rr_number"],
                "package": document_summary(document),
                "stored": str(report),
            }
        )
    return stored_reports


def run(dry_run: bool) -> int:
    config = load_config()
    ensure_runtime_dirs(config)
    setup_logging(config.logs_dir, config.logging_level)
    state = MetadataStore(config.state_file)
    client = SppClient()
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
        and_match(title_contains("Integrated Marketplace Protocols"), extension_is(".zip"), lambda doc: "active ver" in doc.title.lower()),
    )

    discovered.update(
        {
            "rr_master_list": document_summary(rr_master_doc),
            "cuf": document_summary(cuf_doc),
            "suf": document_summary(suf_doc),
            "protocol": document_summary(protocol_doc),
        }
    )

    rr_master_path, rr_master_is_new = get_or_download(
        family="rr_master_list",
        document=rr_master_doc,
        client=client,
        state=state,
        downloads_dir=config.rr_master_list_dir,
        dry_run=dry_run,
        warnings=warnings,
        redownload_on_hash_change=True,
    )
    if dry_run:
        open_rrs = {}
    else:
        if rr_master_path is None:
            raise RuntimeError("RR Master List path unavailable")
        open_rrs = read_open_rrs(rr_master_path)

    cuf_path, cuf_is_new = get_or_download(
        family="cuf",
        document=cuf_doc,
        client=client,
        state=state,
        downloads_dir=config.cuf_dir,
        dry_run=dry_run,
        warnings=warnings,
    )
    suf_path, suf_is_new = get_or_download(
        family="suf",
        document=suf_doc,
        client=client,
        state=state,
        downloads_dir=config.suf_dir,
        dry_run=dry_run,
        warnings=warnings,
    )

    if protocol_doc:
        # Protocol ZIPs are source archives only in v1: retain the raw ZIP, do
        # not extract content, and do not include it in summaries.
        protocol_path, _ = get_or_download(
            family="protocol",
            document=protocol_doc,
            client=client,
            state=state,
            downloads_dir=config.protocols_dir,
            dry_run=dry_run,
            warnings=warnings,
        )
        if protocol_path and protocol_path.exists():
            from src.documents.zip_utils import extract_matching
            protocol_folder = config.protocols_dir / protocol_path.stem
            extract_matching(protocol_path, protocol_folder, (".pdf", ".docx", ".xlsx"))
            protocol_path.unlink()  # delete the zip after extracting
    else:
        warnings.append("Integrated Marketplace Protocol Active Version not found; continuing")

    mentioned: dict[str, dict[str, Any]] = {}
    family_outputs: dict[str, Any] = {}

    # Determine if a full re-cross is needed.
    # Any change in CUF, SUF, or RR Master List triggers a new cross.
    any_change = cuf_is_new or suf_is_new or rr_master_is_new

    if not dry_run:
        if cuf_path and cuf_is_new:
            cuf_folder = config.cuf_dir / cuf_path.stem
            cuf_pdfs = extract_pdfs(cuf_path, cuf_folder)
            cuf_path.unlink()  # delete the zip after extracting
            family_outputs["cuf"] = process_pdf_family(
                family="cuf", files=cuf_pdfs, warnings=warnings, dry_run=dry_run
            )
            state.save_mentions("cuf", family_outputs["cuf"]["mentions"])
        elif cuf_path and any_change:
            cached = state.load_mentions("cuf")
            if cached is not None:
                LOGGER.info("Using cached CUF mentions (document unchanged)")
                family_outputs["cuf"] = {"stored": [], "mentions": cached}
            else:
                LOGGER.info("No CUF mentions cache — re-parsing existing PDFs")
                existing_cuf_pdfs = list(config.cuf_dir.rglob("*.pdf"))
                if existing_cuf_pdfs:
                    family_outputs["cuf"] = process_pdf_family(
                        family="cuf", files=existing_cuf_pdfs, warnings=warnings, dry_run=dry_run
                    )
                    state.save_mentions("cuf", family_outputs["cuf"]["mentions"])
        elif cuf_path:
            skipped.append(f"CUF unchanged, no re-cross needed: {cuf_doc.filename}")

        if suf_path and suf_is_new:
            family_outputs["suf"] = process_pdf_family(
                family="suf", files=[suf_path], warnings=warnings, dry_run=dry_run
            )
            state.save_mentions("suf", family_outputs["suf"]["mentions"])
        elif suf_path and any_change:
            cached = state.load_mentions("suf")
            if cached is not None:
                LOGGER.info("Using cached SUF mentions (document unchanged)")
                family_outputs["suf"] = {"stored": [], "mentions": cached}
            else:
                LOGGER.info("No SUF mentions cache — re-parsing existing PDFs")
                existing_suf_pdfs = list(config.suf_dir.rglob("*.pdf"))
                if existing_suf_pdfs:
                    family_outputs["suf"] = process_pdf_family(
                        family="suf", files=existing_suf_pdfs, warnings=warnings, dry_run=dry_run
                    )
                    state.save_mentions("suf", family_outputs["suf"]["mentions"])
        elif suf_path:
            skipped.append(f"SUF unchanged, no re-cross needed: {suf_doc.filename}")

        for output in family_outputs.values():
            for rr_number, data in output.get("mentions", {}).items():
                entry = mentioned.setdefault(rr_number, {"rr_number": rr_number, "dates": [], "sources": [], "contexts": []})
                for key in ("dates", "sources", "contexts"):
                    for item in data.get(key, []):
                        if item not in entry[key]:
                            entry[key].append(item)

    # Only build relevant RRs if something changed — otherwise use last known state
    if any_change or dry_run:
        relevant_rrs = build_relevant_rrs(open_rrs, mentioned)
    else:
        LOGGER.info("No changes detected — skipping RR cross and report download")
        relevant_rrs = []
    reports = [] if dry_run else process_recommendation_reports(
        relevant_rrs=relevant_rrs,
        client=client,
        state=state,
        config=config,
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


def _edition_documents(edition: SourceEdition, warnings: list[str]) -> list[DocumentText]:
    """Extract text from every file in an edition, marking unreadable ones."""
    documents: list[DocumentText] = []
    for source_file in edition.files:
        path = source_file.local_path
        if path.suffix.lower() != ".pdf":
            documents.append(
                DocumentText(
                    kind=edition.kind,
                    filename=source_file.filename,
                    sharepoint_url=source_file.sharepoint_url,
                    text="",
                    readable=False,
                )
            )
            continue
        parsed = parse_pdf(path)
        warnings.extend(parsed.warnings)
        readable = bool(parsed.text.strip())
        documents.append(
            DocumentText(
                kind=edition.kind,
                filename=source_file.filename,
                sharepoint_url=source_file.sharepoint_url,
                text=parsed.text,
                readable=readable,
            )
        )
    return documents


def _load_latest_relevant_rrs(reports_dir: Path) -> list[dict[str, Any]]:
    """Best-effort: reuse the most recent relevant-rrs JSON to enrich the report."""
    candidates = sorted(reports_dir.glob("relevant-rrs-*.json"))
    if not candidates:
        return []
    try:
        return json.loads(candidates[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Could not read relevant RRs from %s: %s", candidates[-1], exc)
        return []


def generate_report() -> int:
    """Produce the SPP Market Changes Summary HTML from the latest local CUF/SUF."""
    config = load_config()
    ensure_runtime_dirs(config)
    setup_logging(config.logs_dir, config.logging_level)
    warnings: list[str] = []

    cuf = latest_cuf_edition(config.cuf_dir, config.sharepoint_sync_root, config.sharepoint_base_url)
    suf = latest_suf_edition(config.suf_dir, config.sharepoint_sync_root, config.sharepoint_base_url)
    if not cuf and not suf:
        raise RuntimeError("No CUF or SUF materials found in the synced SharePoint folders")

    documents: list[DocumentText] = []
    cuf_label = suf_label = "not found"
    if cuf:
        cuf_label = f"{cuf.label} ({cuf.meeting_date_label})"
        documents.extend(_edition_documents(cuf, warnings))
        LOGGER.info("Latest CUF edition: %s (%d files)", cuf.label, len(cuf.files))
    if suf:
        suf_label = f"{suf.label} ({suf.meeting_date_label})"
        documents.extend(_edition_documents(suf, warnings))
        LOGGER.info("Latest SUF edition: %s (%d files)", suf.label, len(suf.files))

    engine = build_engine(config.report_engine, binary=config.claude_code_binary, model=config.report_model)
    report = build_report(
        engine=engine,
        cuf_label=cuf_label,
        suf_label=suf_label,
        documents=documents,
        relevant_rrs=_load_latest_relevant_rrs(config.reports_dir),
        generated=datetime.now().strftime("%B %d, %Y"),
    )
    html = render_report(report)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    html_path = config.reports_dir / f"SPP_Market_Changes_Summary-{run_id}.html"
    html_path.write_text(html, encoding="utf-8")
    LOGGER.info("Report written: %s", html_path)
    for warning in warnings:
        LOGGER.warning(warning)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SPP RR automation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run the automation")
    run_parser.add_argument("--dry-run", action="store_true", help="Discover documents without downloading or storing files")
    subparsers.add_parser("report", help="Generate the SPP Market Changes Summary HTML from the latest local CUF/SUF")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "run":
        return run(dry_run=args.dry_run)
    if args.command == "report":
        return generate_report()
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())