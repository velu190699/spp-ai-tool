from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
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
from src.documents.local_source import (
    SourceEdition,
    all_cuf_editions,
    all_suf_editions,
    latest_cuf_edition,
    latest_suf_edition,
    to_sharepoint_url,
)
from src.documents.pdf_parser import parse_pdf
from src.documents.rr_extractor import initiative_from_contexts, merge_mentions
from src.documents.zip_utils import extract_first_recommendation_report, extract_pdfs
from src.notifications.notifier import (
    log_slack_draft,
    send_slack_failure,
    send_slack_report_link,
    send_slack_story_drafts,
)
from src.settlement import jira_template_writer, screenshots
from src.settlement import pipeline as settlement_pipeline
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
    # A tracked document can land here when its cached file is gone (zips are
    # deleted after extraction). Compare against the recorded hash so a
    # re-published document (same name, new content) is detected as changed
    # instead of silently treated as already-processed.
    old_hash = existing.existing.get("sha256") if existing.existing else None
    content_changed = existing.is_new or (old_hash is not None and old_hash != file_hash)
    if not existing.is_new and content_changed:
        LOGGER.info("%s content changed since last run (re-published): %s", family, document.filename)
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
    return local_path, content_changed


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
        # Which initiative the CUF/SUF slide ties this RR to — VERBATIM slide
        # wording plus the file/page citation so a reviewer can check the slide.
        initiative, initiative_citation = initiative_from_contexts(
            mention_data.get("contexts", []), mention_data.get("context_sources", [])
        )
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
                "market_initiative": initiative,
                "market_initiative_citation": initiative_citation,
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
        zip_path, package_changed = get_or_download(
            family="recommendation_reports",
            document=document,
            client=client,
            state=state,
            downloads_dir=config.recommendation_reports_dir,
            dry_run=dry_run,
            warnings=warnings,
        )
        # Skip only when the docx is on disk AND the package content is
        # unchanged. SPP re-publishes RR packages under the same filename; a
        # changed hash means a revised Recommendation Report that must be
        # re-extracted and flagged as an UPDATE downstream, not skipped.
        existing_docx = config.recommendation_reports_dir / f"rr{rr['rr_number']}" / f"RR{rr['rr_number']} Recommendation Report.docx"
        if existing_docx.exists() and not package_changed and not dry_run:
            LOGGER.info("RR%s: Recommendation Report already on disk and unchanged, skipping", rr['rr_number'])
            stored_reports.append({"rr_number": rr["rr_number"], "stored": str(existing_docx), "skipped": True})
            continue
        if dry_run or zip_path is None:
            stored_reports.append({"rr_number": rr["rr_number"], "package": document_summary(document), "dry_run": True})
            continue
        target_dir = config.recommendation_reports_dir / f"rr{rr['rr_number']}"
        # Store only the first exact Recommendation Report filename. Other Word
        # files in the RR package are not substitutes for this v1 contract.
        # A re-published package NEVER overwrites the original docx: the new
        # version is stored alongside as a dated .rev-YYYYMMDD file (the team's
        # folder structure is append-only; originals stay untouched).
        is_revision = existing_docx.exists() and package_changed
        revision_name = None
        if is_revision:
            revision_name = f"{existing_docx.stem}.rev-{datetime.now().strftime('%Y%m%d')}.docx"
        report = extract_first_recommendation_report(zip_path, rr["rr_number"], target_dir, target_name=revision_name)
        if report and zip_path.exists():
            zip_path.unlink()  # delete the zip after extracting
        if not report:
            warning = f"RR{rr['rr_number']}: no exact Recommendation Report docx found in package"
            warnings.append(warning)
            LOGGER.warning(warning)
            continue
        if is_revision:
            rr["updated"] = True
            warnings.append(
                f"RR{rr['rr_number']}: SPP re-published the Recommendation Report — saved as "
                f"{report.name} next to the original (which is unchanged). Analyses should use "
                f"the newest revision (UPDATE)."
            )
        stored_reports.append(
            {
                "rr_number": rr["rr_number"],
                "package": document_summary(document),
                "stored": str(report),
                "updated": is_revision,
            }
        )
    return stored_reports


def _refresh_watch_list(state: MetadataStore, relevant_rrs: list[dict[str, Any]], open_rrs: dict[str, RRRecord]) -> list[dict[str, Any]]:
    """Seed/refresh the settlement watch list and return the OPEN RRs to fetch.

    Option B: the CUF/SUF cross-reference only DISCOVERS an RR and names its
    market initiative — captured here, once. From then on the RR is watched by
    Recommendation-Report change for as long as the RR Master List shows it open,
    so a late revision to an RR that fell out of the newest materials is still
    fetched. Each watched RR's open/closed status is refreshed from the master
    list (a closed RR gets one final capture downstream, then is removed).

    Returns download descriptors for every watched, still-open RR — a superset of
    the latest relevant list — so `process_recommendation_reports` fetches them.
    """
    for rr in relevant_rrs:
        state.upsert_watched(str(rr.get("rr_number")), {
            "title": rr.get("title", ""),
            "primary_working_group": rr.get("primary_working_group", ""),
            "market_initiative": rr.get("market_initiative", ""),
            "market_initiative_citation": rr.get("market_initiative_citation", ""),
            "search_url": rr.get("search_url", ""),
            "domain": "BO",
            "status": "open",
        })
    # Refresh open/closed from the master list (open_rrs holds only OPEN RRs).
    for watched in state.list_watched():
        num = watched["rr_number"]
        state.set_watched_status(num, "open" if num in open_rrs else "closed")
    return [
        {
            "rr_number": w["rr_number"],
            "title": w.get("title", ""),
            "search_url": w.get("search_url", ""),
            "market_initiative": w.get("market_initiative", ""),
            "primary_working_group": w.get("primary_working_group", ""),
        }
        for w in state.list_watched(status="open")
    ]


def accumulate_watch_list_initiatives(state: MetadataStore, config, warnings: list[str]) -> None:
    """Fill watched RRs' market initiatives from ALL synced CUF/SUF editions.

    Option B accumulation: ``run`` parses only the LATEST edition for relevance,
    so an RR whose initiative was named in an OLDER edition (RR750) shows blank.
    This walks every synced CUF/SUF edition, parses each one ONCE (tracked in the
    store), and for each WATCHED RR it finds mentioned records a dated
    ``mentions_seen`` entry — the RR's current initiative then becomes the newest
    edition that names one. The one-time backfill needs no special path: on the
    first run nothing is marked parsed, so every older edition already synced is
    parsed once; thereafter only a brand-new edition is. Watched RRs only — an RR
    discovered solely in an old edition is NOT added to the watch list.
    """
    watched_nums = {w["rr_number"] for w in state.list_watched()}
    if not watched_nums:
        return
    editions = (
        all_cuf_editions(config.cuf_dir, config.sharepoint_sync_root, config.sharepoint_base_url)
        + all_suf_editions(config.suf_dir, config.sharepoint_sync_root, config.sharepoint_base_url)
    )
    for edition in editions:
        edition_key = f"{edition.kind}|{edition.label}"
        if state.is_edition_parsed(edition_key):
            continue
        pdfs = [f.local_path for f in edition.files if f.local_path.suffix.lower() == ".pdf"]
        mentions_all = []
        for pdf in pdfs:
            parsed = parse_pdf(pdf)
            warnings.extend(parsed.warnings)
            mentions_all.extend(parsed.rr_mentions)
        mentions = merge_mentions(mentions_all)
        meeting_date = edition.meeting_date.strftime("%Y-%m-%d") if edition.meeting_date else ""
        filled = 0
        for rr_number, data in mentions.items():
            if rr_number not in watched_nums:
                continue
            label, citation = initiative_from_contexts(
                data.get("contexts", []), data.get("context_sources", [])
            )
            state.add_watched_mention(
                rr_number,
                {
                    "edition": edition_key,
                    "kind": edition.kind,
                    "label": edition.label,
                    "meeting_date": meeting_date,
                    "initiative": label,
                    "initiative_citation": citation,
                    "source": "; ".join(data.get("sources", [])[:2]),
                },
            )
            filled += 1
        state.mark_edition_parsed(
            edition_key,
            {"kind": edition.kind, "label": edition.label, "meeting_date": meeting_date, "pdfs": len(pdfs)},
        )
        LOGGER.info(
            "Accumulated %s edition %s: %d PDF(s), %d watched RR mention(s)",
            edition.kind, edition.label, len(pdfs), filled,
        )


def _enrich_relevant_from_watch_list(state: MetadataStore, relevant_rrs: list[dict[str, Any]]) -> None:
    """Backfill a blank market initiative on the relevant list from the watch list.

    After accumulation recovers an initiative named only in an older edition
    (RR750), the current run's relevant list — built from the latest edition —
    may still show it blank. Fill those blanks so the briefing shows the
    recovered label; never overwrite an initiative the latest edition already named.
    """
    for rr in relevant_rrs:
        if rr.get("market_initiative"):
            continue
        watched = state.get_watched(str(rr.get("rr_number")))
        if watched and watched.get("market_initiative"):
            rr["market_initiative"] = watched["market_initiative"]
            rr["market_initiative_citation"] = watched.get("market_initiative_citation", "")


def run(dry_run: bool) -> int:
    config = load_config()
    ensure_runtime_dirs(config)
    setup_logging(config.logs_dir, config.logging_level)
    # legacy_path: pre-shared-state location (repo-local); migrated on first run.
    state = MetadataStore(config.state_file, legacy_path=Path("data/state/metadata.json"))
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
                LOGGER.info("No CUF mentions cache — re-parsing the LATEST CUF edition")
                # Only the newest edition: relevance is defined by the latest
                # CUF/SUF materials, not by every meeting still in the folder.
                latest = latest_cuf_edition(config.cuf_dir, config.sharepoint_sync_root, config.sharepoint_base_url)
                latest_pdfs = [f.local_path for f in latest.files if f.local_path.suffix.lower() == ".pdf"] if latest else []
                if latest_pdfs:
                    family_outputs["cuf"] = process_pdf_family(
                        family="cuf", files=latest_pdfs, warnings=warnings, dry_run=dry_run
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
                LOGGER.info("No SUF mentions cache — re-parsing the LATEST SUF edition")
                latest = latest_suf_edition(config.suf_dir, config.sharepoint_sync_root, config.sharepoint_base_url)
                latest_pdfs = [f.local_path for f in latest.files if f.local_path.suffix.lower() == ".pdf"] if latest else []
                if latest_pdfs:
                    family_outputs["suf"] = process_pdf_family(
                        family="suf", files=latest_pdfs, warnings=warnings, dry_run=dry_run
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

    # Only build relevant RRs if something changed — otherwise carry forward the
    # last known state. A no-change run must not clear the list: the materials
    # are identical to last time, so the relevant RRs are too. Writing [] here
    # would overwrite the real list and leave `report` with nothing to show.
    if any_change or dry_run:
        relevant_rrs = build_relevant_rrs(open_rrs, mentioned)
    else:
        LOGGER.info("No changes detected — reusing last known relevant RRs")
        relevant_rrs = state.load_relevant_rrs() or _load_latest_relevant_rrs(config.reports_dir)
    # Option B: fetch the Recommendation Report of every WATCHED, still-OPEN RR
    # (a superset of the latest relevant list), so a late revision to an RR that
    # dropped out of the newest CUF/SUF is still caught. dry-run keeps its
    # discovery-only view over the relevant list and never mutates the watch list.
    download_rrs = relevant_rrs if dry_run else _refresh_watch_list(state, relevant_rrs, open_rrs)
    if not dry_run:
        # Recover initiatives named only in OLDER editions (backfills on first
        # run), then fill any still-blank initiative on the relevant list from the
        # now-updated watch list so the briefing reflects the recovered label.
        accumulate_watch_list_initiatives(state, config, warnings)
        _enrich_relevant_from_watch_list(state, relevant_rrs)
    reports = [] if dry_run else process_recommendation_reports(
        relevant_rrs=download_rrs,
        client=client,
        state=state,
        config=config,
        dry_run=dry_run,
        warnings=warnings,
        skipped=skipped,
    )
    discovered["recommendation_reports"] = reports
    # Carry any UPDATE flag back onto the CUF/SUF relevant list so the briefing's
    # RR badges still reflect a re-published Recommendation Report.
    updated_nums = {str(r["rr_number"]) for r in download_rrs if r.get("updated")}
    for rr in relevant_rrs:
        if str(rr.get("rr_number")) in updated_nums:
            rr["updated"] = True

    log_slack_draft(relevant_rrs, warnings)

    # Decoupled triggers (Option B): the all-teams HTML briefing is rebuilt and
    # posted ONLY when a new CUF/SUF edition arrived — its content is
    # slide-derived, so an RR-only change never rebuilds it (RR changes travel
    # via the settlement outputs instead). dry runs never notify. (Heartbeat for
    # a truly no-change run lands with the notification rework.)
    if not dry_run and (cuf_is_new or suf_is_new):
        notify_slack_report(config, warnings, run_id, relevant_rrs)

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
        if relevant_rrs:
            # Carry the cross-reference in the shared store so `report` (and
            # runs on other machines) reuse it without walking local files.
            state.save_relevant_rrs(relevant_rrs)
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


def _latest_rr_docx_files(root: Path) -> list[str]:
    """Newest revision of each RR docx under ``root``.

    Re-published RRs are stored as append-only dated revisions
    ("RR773 Recommendation Report.rev-20260714.docx") next to the untouched
    original. Analyses must read exactly one file per RR — the newest one.
    Revision suffixes sort lexicographically (ISO dates), and any original
    without revisions is its own newest version.
    """
    latest: dict[str, Path] = {}
    for path in root.rglob("*.docx"):
        base = re.sub(r"\.rev-\d{8}$", "", path.stem)
        key = f"{path.parent}|{base}"
        current = latest.get(key)
        if current is None or path.stem > current.stem:
            latest[key] = path
    return [str(p) for p in sorted(latest.values())]


def _load_latest_relevant_rrs(reports_dir: Path) -> list[dict[str, Any]]:
    """Reuse the most recent NON-EMPTY relevant-rrs JSON to enrich the report.

    A `run` that detects no changes writes an empty list (it skips the RR cross),
    so the newest file is often `[]`. That empty file means "nothing recomputed",
    not "confirmed zero relevant RRs" — so walk newest→oldest and return the
    first file that actually has RRs, falling back to [] only if none ever did.
    """
    for candidate in sorted(reports_dir.glob("relevant-rrs-*.json"), reverse=True):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Could not read relevant RRs from %s: %s", candidate, exc)
            continue
        if data:
            return data
    return []


def build_market_changes_html(
    config,
    warnings: list[str],
    run_id: str,
    relevant_rrs: list[dict[str, Any]],
) -> tuple[Path | None, str]:
    """Build the SPP Market Changes Summary HTML and publish it.

    Reads the latest local CUF/SUF materials, renders the report, writes it to
    ``published_reports_dir`` (the synced SharePoint "Reports" library), and
    returns ``(html_path, sharepoint_url)``. Returns ``(None, "")`` when no CUF
    or SUF materials are available, appending a warning instead of raising, so
    the automated ``run`` flow can still notify without a report.
    """
    cuf = latest_cuf_edition(config.cuf_dir, config.sharepoint_sync_root, config.sharepoint_base_url)
    suf = latest_suf_edition(config.suf_dir, config.sharepoint_sync_root, config.sharepoint_base_url)
    if not cuf and not suf:
        warnings.append("No CUF or SUF materials found in the synced SharePoint folders; skipping HTML report")
        return None, ""

    documents: list[DocumentText] = []
    cuf_label = suf_label = "not found"
    cuf_url = suf_url = ""
    if cuf:
        cuf_label = f"{cuf.label} ({cuf.meeting_date_label})"
        cuf_url = cuf.url
        documents.extend(_edition_documents(cuf, warnings))
        LOGGER.info("Latest CUF edition: %s (%d files)", cuf.label, len(cuf.files))
    if suf:
        suf_label = f"{suf.label} ({suf.meeting_date_label})"
        suf_url = suf.url
        documents.extend(_edition_documents(suf, warnings))
        LOGGER.info("Latest SUF edition: %s (%d files)", suf.label, len(suf.files))

    engine = build_engine(config.report_engine, binary=config.claude_code_binary, model=config.report_model)
    report = build_report(
        engine=engine,
        cuf_label=cuf_label,
        suf_label=suf_label,
        documents=documents,
        relevant_rrs=relevant_rrs,
        generated=datetime.now().strftime("%B %d, %Y"),
        cuf_url=cuf_url,
        suf_url=suf_url,
        routing_file=config.area_routing_file,
    )
    html = render_report(report)

    html_path = config.published_reports_dir / f"SPP_Market_Changes_Summary-{run_id}.html"
    html_path.write_text(html, encoding="utf-8")
    LOGGER.info("Report written: %s", html_path)

    # The HTML lives in the synced SharePoint "Reports" library, so map its local
    # path back to a clickable web link for the Slack notification.
    report_url = to_sharepoint_url(html_path, config.sharepoint_sync_root, config.sharepoint_base_url)
    return html_path, report_url


def notify_slack_report(config, warnings: list[str], run_id: str, relevant_rrs: list[dict[str, Any]]) -> None:
    """Build+publish the HTML report and post it to Slack with the RR list.

    Report generation must never sink the surrounding command, so a build
    failure is logged and turned into a warning; the channel is still notified
    (with the RR list and no link) so a failed report doesn't go unnoticed.
    """
    report_url = ""
    note = ""
    try:
        html_path, report_url = build_market_changes_html(config, warnings, run_id, relevant_rrs)
        if html_path is None:
            # No CUF/SUF materials — build_market_changes_html already warned.
            note = "No CUF/SUF materials available; report not generated."
    except Exception as exc:  # report build must not crash the caller
        LOGGER.exception("Failed to build the HTML report for the Slack notification")
        warnings.append(f"HTML report generation failed: {exc}")
        note = "Report generation failed; see the run log for details."
    report_title = f"SPP Market Changes Summary — {datetime.now().strftime('%B %d, %Y')}"
    send_slack_report_link(
        report_title,
        report_url,
        webhook_url=config.slack_webhook_url,
        bot_token=config.slack_bot_token,
        channel=config.slack_channel,
        relevant_rrs=relevant_rrs,
        note=note,
    )


def generate_report() -> int:
    """Produce the SPP Market Changes Summary HTML from the latest local CUF/SUF."""
    config = load_config()
    ensure_runtime_dirs(config)
    setup_logging(config.logs_dir, config.logging_level)
    warnings: list[str] = []

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    # Prefer the shared store (works across machines); fall back to local files.
    state = MetadataStore(config.state_file, legacy_path=Path("data/state/metadata.json"))
    relevant_rrs = state.load_relevant_rrs() or _load_latest_relevant_rrs(config.reports_dir)
    html_path, report_url = build_market_changes_html(config, warnings, run_id, relevant_rrs)
    if html_path is None:
        raise RuntimeError("No CUF or SUF materials found in the synced SharePoint folders")

    # Announce the published report in Slack, including the relevant RR list.
    report_title = f"SPP Market Changes Summary — {datetime.now().strftime('%B %d, %Y')}"
    send_slack_report_link(
        report_title,
        report_url,
        webhook_url=config.slack_webhook_url,
        bot_token=config.slack_bot_token,
        channel=config.slack_channel,
        relevant_rrs=relevant_rrs,
    )

    for warning in warnings:
        LOGGER.warning(warning)
    return 0


def _rr_number_of_path(path: str) -> str:
    """RR digits from a cached docx path (rr728/RR728 Recommendation Report...)."""
    match = re.search(r"rr\s?0*(\d{2,5})", Path(path).parent.name, re.IGNORECASE) or \
        re.search(r"RR\s?0*(\d{2,5})", Path(path).name, re.IGNORECASE)
    return match.group(1) if match else ""


def generate_settlement_report(
    *, files: list[str] | None, links: str | None, out: str | None, call_claude: bool,
    process_all: bool = False, write_stories: bool = False,
) -> int:
    """Produce SPP_RR_Report_Summary.xlsx: RR docx -> charge-type stories for settlement devs.

    Distinct from generate_report() above (the PCI-wide HTML briefing) — this is
    a Jira-intake artifact for the settlement development team, scoped to RRs
    that change a charge code. See src/settlement/pipeline.py for the full flow.
    """
    config = load_config()
    ensure_runtime_dirs(config)
    setup_logging(config.logs_dir, config.logging_level)

    state = MetadataStore(config.state_file, legacy_path=Path("data/state/metadata.json"))
    relevant = state.load_relevant_rrs() or _load_latest_relevant_rrs(config.reports_dir)

    # No --files/--links given: process the WATCH LIST (Option B). Every RR that
    # CUF/SUF ever surfaced and the master list still shows open is tracked; we
    # (re)process one only when its Recommendation Report changed since the
    # ledger last saw it. An RR that has flipped to closed gets one final pass
    # this run, then is pruned from the watch list. --all overrides both filters
    # (full re-run over the cache, ignoring the watch list and the ledger).
    analysis_records: list[tuple[str, str]] = []  # (rr_key, input_hash) to record on success
    closed_to_prune: list[str] = []               # watched RRs now closed -> drop after this run
    if not files and not links:
        candidates = _latest_rr_docx_files(config.recommendation_reports_dir)
        if not candidates:
            raise RuntimeError(
                f"No RR .docx files in {config.recommendation_reports_dir} and no "
                "--files/--links given. Run `python main.py run` first, or pass one explicitly."
            )
        watched = {w["rr_number"]: w for w in state.list_watched()}
        files = []
        for path in candidates:
            rr_num = _rr_number_of_path(path)
            entry = watched.get(rr_num)
            if not process_all and entry is None:
                LOGGER.info("RR%s: not on the settlement watch list — skipped (use --all to include)", rr_num or "?")
                continue
            if entry and entry.get("status") == "closed":
                closed_to_prune.append(rr_num)  # final pass this run, then unwatch
            input_hash = sha256_file(Path(path))
            ledger = state.check_analysis("settlement_report", f"RR{rr_num}", input_hash)
            if not process_all and ledger == "unchanged":
                LOGGER.info("RR%s: Recommendation Report unchanged since last processing — skipped", rr_num)
                continue
            if ledger == "updated":
                LOGGER.info("RR%s: Recommendation Report changed since last processing — re-analyzing (UPDATE)", rr_num)
            files.append(path)
            analysis_records.append((f"RR{rr_num}", input_hash))
        if not files:
            for rr_num in closed_to_prune:
                state.remove_watched(rr_num)
            if closed_to_prune:
                state.save()
                LOGGER.info("Pruned closed RR(s) from the watch list: %s", ", ".join(closed_to_prune))
            else:
                LOGGER.info("Nothing new to process — all watched RRs are current in the ledger. Use --all to regenerate.")
            return 0
        LOGGER.info("Processing %d new/updated RR docx file(s)", len(files))

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = out or str(config.settlement_reports_dir / f"SPP_RR_Report_Summary-{run_id}.xlsx")

    # RR -> market initiative: from the WATCH LIST, where each RR's initiative was
    # captured once when CUF/SUF first named it — so an RR no longer in the latest
    # materials keeps its initiative. Falls back to the relevant list for a manual
    # --files run on an RR not yet watched.
    initiatives = {
        w["rr_number"]: {"label": w.get("market_initiative", ""), "citation": w.get("market_initiative_citation", "")}
        for w in state.list_watched() if w.get("market_initiative")
    }
    for rr in relevant:
        num = str(rr.get("rr_number"))
        if num not in initiatives and rr.get("market_initiative"):
            initiatives[num] = {
                "label": rr.get("market_initiative", ""),
                "citation": rr.get("market_initiative_citation", ""),
            }

    engine = build_engine(config.report_engine, binary=config.claude_code_binary, model=config.report_model) if call_claude else None
    _, results = settlement_pipeline.run(
        files=files,
        links=settlement_pipeline.read_links_file(links) if links else None,
        out_path=out_path,
        engine=engine,
        tenant=config.sharepoint_tenant_id,
        client_id=config.sharepoint_client_id,
        client_secret=config.sharepoint_client_secret,
        initiatives=initiatives,
        # Stories cross-link the RR to the synced Protocols/SUG copy.
        protocols_url=to_sharepoint_url(config.protocols_dir, config.sharepoint_sync_root, config.sharepoint_base_url, is_folder=True),
        # For resolving the RR and CUF/SUF citation links into the report.
        sync_root=config.sharepoint_sync_root,
        base_url=config.sharepoint_base_url,
        cuf_dirs=(config.cuf_dir, config.suf_dir),
    )
    LOGGER.info("Settlement report written: %s", out_path)

    # Publish the finished xlsx to the synced SharePoint folder (the working
    # artifacts — stories JSON, images, rendered PDFs — stay in the local
    # settlement_reports_dir; the team only sees the report itself).
    published_path = out_path
    if config.published_settlement_reports_dir.resolve() != Path(out_path).parent.resolve():
        published_path = str(config.published_settlement_reports_dir / Path(out_path).name)
        shutil.copy2(out_path, published_path)
        LOGGER.info("Settlement report published: %s", published_path)

    # Every published report notifies the channel, not just the HTML briefing
    # (Eduardo, 2026-07-17).
    rr_ids = [str(res["report"].get("rr_id", "?")) for res in results]
    report_url = to_sharepoint_url(Path(published_path), config.sharepoint_sync_root, config.sharepoint_base_url)
    send_slack_report_link(
        f"SPPIM settlement RR report — {', '.join(rr_ids)} ({datetime.now().strftime('%B %d, %Y')})",
        report_url,
        webhook_url=config.slack_webhook_url,
        bot_token=config.slack_bot_token,
        channel=config.slack_channel,
        note="" if report_url else "Report written locally; no SharePoint link available.",
    )

    # Record what was processed at which content version, so the next run
    # skips these RRs until SPP re-publishes them (UPDATE detection).
    for rr_key, input_hash in analysis_records:
        state.record_analysis("settlement_report", rr_key, input_hash, {"report": published_path})
    # Prune RRs that closed: their final pass is done, stop watching them.
    for rr_num in closed_to_prune:
        state.remove_watched(rr_num)
    if closed_to_prune:
        LOGGER.info("Pruned closed RR(s) from the watch list after final capture: %s", ", ".join(closed_to_prune))
    if analysis_records or closed_to_prune:
        state.save()

    # Story workbooks are PAUSED by default (Elizabeth, 2026-07-15) until the
    # RR728 story quality passes review — one combined report is the output.
    # --stories re-enables per-RR workbook generation.
    if write_stories:
        written = 0
        rr_links: list[tuple[str, str]] = []  # (rr_id, workbook SharePoint url) for Slack
        for res in results:
            rr_id = str(res["report"].get("rr_id", "RR")).replace(" ", "")
            # Screenshot tab (Miquel's guide): one cropped redline image per
            # numbered item (markup view), on a sheet named after the Local ID.
            # Run this BEFORE stories_from_results so each item's screenshot count
            # (`parts`) is stamped on the mirror items and the workbook
            # description can list its a/b codes.
            shots: dict[str, list] = {}
            if res.get("docx_path"):
                rr_digits = "".join(ch for ch in rr_id if ch.isdigit())
                images = screenshots.item_screenshots(
                    res["docx_path"], res["report"], res.get("stories"),
                    config.settlement_reports_dir / "screenshots" / f"rr{rr_digits}",
                    config.settlement_reports_dir / "rendered",
                )
                if images:
                    shots[rr_id] = images
            rows = jira_template_writer.stories_from_results([res])
            if not rows:
                continue  # TARIFF_GOVERNANCE etc. — no story content for this RR
            if shots.get(rr_id):
                rows[0].local_id = rr_id  # Local ID only when screenshots exist (guide)
            jira_out = config.jira_stories_dir / f"{rr_id}_Jira_Stories-{run_id}.xlsx"
            jira_template_writer.write_story_workbook(config.jira_template_file, jira_out, rows, screenshots=shots)
            written += 1
            rr_links.append((rr_id, to_sharepoint_url(jira_out, config.sharepoint_sync_root, config.sharepoint_base_url)))
            LOGGER.info("Story workbook written for %s: %s (%d screenshot pages)", rr_id, jira_out.name, len(shots.get(rr_id, [])))
        if written:
            # One descriptive message: report link on top, then a link to each
            # RR's story template (Eduardo, 2026-07-20).
            send_slack_story_drafts(
                f"SPPIM settlement Jira story drafts — {', '.join(rr for rr, _ in rr_links)} "
                f"— PM review needed ({datetime.now().strftime('%B %d, %Y')})",
                report_url,
                rr_links,
                webhook_url=config.slack_webhook_url,
                bot_token=config.slack_bot_token,
                channel=config.slack_channel,
            )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SPP RR automation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run the automation")
    run_parser.add_argument("--dry-run", action="store_true", help="Discover documents without downloading or storing files")
    subparsers.add_parser("report", help="Generate the SPP Market Changes Summary HTML from the latest local CUF/SUF")

    settlement_parser = subparsers.add_parser(
        "settlement-report", help="Generate the SPP RR -> Jira Settlement Excel report"
    )
    settlement_parser.add_argument(
        "--files", nargs="*", help="Local RR .docx paths (default: everything in recommendation_reports_dir)"
    )
    settlement_parser.add_argument("--links", help="Path to a text file of SharePoint share URLs, one per line")
    settlement_parser.add_argument("--out", help="Output .xlsx path (default: settlement_reports_dir/SPP_RR_Report_Summary-<timestamp>.xlsx)")
    settlement_parser.add_argument(
        "--call-claude", action="store_true",
        help="Invoke the LLM to generate Jira stories for SETTLEMENT_CALC + PASS RRs (omit for a classification-only triage pass)",
    )
    settlement_parser.add_argument(
        "--all", action="store_true", dest="process_all",
        help="Process every cached RR docx, ignoring the relevant list and the already-processed ledger",
    )
    settlement_parser.add_argument(
        "--stories", action="store_true", dest="write_stories",
        help="Also write per-RR Jira story workbooks (paused by default pending story-quality review)",
    )
    return parser.parse_args()


def _notify_failure(step: str, exc: BaseException) -> None:
    """Post a failure alert to Slack; never let the alert itself raise.

    Scheduled tasks fail silently otherwise — the scheduler logs an exit code
    nobody reads, and the team only notices when reports stop arriving.
    """
    try:
        config = load_config()
        send_slack_failure(
            step,
            f"{type(exc).__name__}: {exc}",
            webhook_url=config.slack_webhook_url,
            bot_token=config.slack_bot_token,
            channel=config.slack_channel,
        )
    except Exception:  # config itself may be what's broken
        LOGGER.exception("Could not send the Slack failure notification")


def main() -> int:
    args = parse_args()
    try:
        if args.command == "run":
            return run(dry_run=args.dry_run)
        if args.command == "report":
            return generate_report()
        if args.command == "settlement-report":
            return generate_settlement_report(
                files=args.files, links=args.links, out=args.out, call_claude=args.call_claude,
                process_all=args.process_all, write_stories=args.write_stories,
            )
    except Exception as exc:
        LOGGER.exception("Command '%s' failed", args.command)
        _notify_failure(args.command, exc)
        raise
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())