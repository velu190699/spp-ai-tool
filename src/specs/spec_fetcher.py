"""Discover and archive SPP API spec releases from the Future Tech Specs page.

Front half of the FO (ISO Communication) pipeline: the step that turns
"SPP published something" into "a zip on disk", so ``spec_analysis`` /
``story_builder`` have an input without anyone downloading by hand.

WHY WATCH A WHOLE PAGE INSTEAD OF SEARCHING BY NAME
---------------------------------------------------
The CUF "Future Web Service Update" slide is the human trigger, but it carries
NO link to the zip (Miquel's blocker). So we watch the curated Future Tech
Specs page (``?id=21071``) in full and match by FAMILY, which is stable across
releases even when the file naming is not.

THREE HAZARDS THIS MODULE EXISTS TO HANDLE (all verified live 2026-08-11)
------------------------------------------------------------------------
1. **SPP REPLACES entries — it does not accumulate them.** The page listed
   ``...20260805`` and the draft ``...20260522``; the ``20260708`` release that
   story SP-12813 was written from was ALREADY GONE. A release we never
   downloaded is unrecoverable, and with it the ability to diff against it.
   => archive every version, never overwrite, never prune.

2. **The date in the filename lies.** ``..._20260522.zip`` was published
   *June 30 2026* — five weeks later. Exactly the trap Miquel flagged. The
   two dates are kept as separate fields: ``release_tag`` (SPP's own name for
   the release, used as identity) and ``published_date`` (when it actually
   appeared, used for ordering).

3. **Draft-vs-final is only visible in the LINK TEXT.** The draft's link text
   is ``Draft_RTO_Markets_API_Specifications_20260522`` but the file it points
   at is ``RTO_Markets_API_Specifications_20260522.zip`` — no "Draft" in the
   filename at all. Both are checked, title first.

Standalone (not wired into main.py yet)::

    python -m src.specs.spec_fetcher --list
    python -m src.specs.spec_fetcher --fetch --family "RTO Markets"
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.browser.download_utils import download_to_path, sha256_file
from src.browser.spp_client import SppClient, SppDocument

LOGGER = logging.getLogger(__name__)

# SPP's curated "Future Tech Specs" page — the one Miquel works from.
FUTURE_TECH_SPECS_PAGE_ID = 21071

# Local archive root. Deliberately a module constant, not an AppConfig field:
# this module is not wired into main.py yet, so it does not touch the shared
# config dataclass. Promote it to config.yaml when `run` starts calling this.
DEFAULT_ARCHIVE_DIR = Path("data/specs_archive")

# The family we actually build stories for today. Others are listed but not
# fetched by default — Markets Plus is a different product line.
PRIMARY_FAMILY = "RTO Markets"

_DATE_TAG = re.compile(r"(20\d{6})")
_SPEC_TITLE = re.compile(r"^(.*?)\s*API\s*Specifications?\b", re.I)


def _normalize(text: str) -> str:
    """Underscores/spaces vary release to release; collapse them."""
    return re.sub(r"[\s_]+", " ", text).strip()


def classify_family(title: str) -> str | None:
    """The spec family a listing belongs to, or None if it is not an API spec.

    Derived from the title rather than a hardcoded list, so a family SPP adds
    later is picked up without a code change:

        "RTO Markets API Specifications 20260805"          -> "RTO Markets"
        "Draft_RTO_Markets_API_Specifications_20260522"    -> "RTO Markets"
        "Markets_Plus_CRT_API_Specifications_20260724"     -> "Markets Plus CRT"
        "NITS Modifications CSS XSD Reports 20161219"      -> None
    """
    name = _normalize(title)
    name = re.sub(r"^draft[\s_]*", "", name, flags=re.I)
    match = _SPEC_TITLE.match(name)
    if not match:
        return None
    family = match.group(1).strip(" _-")
    return family or None


def release_tag(title: str, filename: str) -> str:
    """SPP's own YYYYMMDD label for the release (identity, NOT a real date)."""
    for text in (title, filename):
        match = _DATE_TAG.search(text)
        if match:
            return match.group(1)
    return ""


def is_draft(title: str, filename: str) -> bool:
    """Draft releases are marked in the link TEXT only — see module docstring."""
    return bool(re.search(r"\bdraft\b", _normalize(title), re.I)) or bool(
        re.search(r"\bdraft\b", _normalize(filename), re.I)
    )


def family_slug(family: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", family.lower()).strip("_")


@dataclass(frozen=True)
class SpecRelease:
    """One spec-release zip listed on the Future Tech Specs page."""

    document: SppDocument
    family: str
    release_tag: str
    draft: bool

    @property
    def published_date(self) -> datetime | None:
        return self.document.published_date

    @property
    def filename(self) -> str:
        return self.document.filename

    @property
    def label(self) -> str:
        kind = "draft" if self.draft else "final"
        published = self.published_date.strftime("%Y-%m-%d") if self.published_date else "?"
        return f"{self.family} {self.release_tag or '?'} ({kind}, published {published})"

    def archive_path(self, archive_dir: Path = DEFAULT_ARCHIVE_DIR) -> Path:
        """Where this release is kept. Filenames already carry the release tag,
        so versions sit side by side inside the family folder."""
        return Path(archive_dir) / family_slug(self.family) / self.filename


def list_releases(
    client: SppClient | None = None,
    *,
    page_id: int | str = FUTURE_TECH_SPECS_PAGE_ID,
) -> list[SpecRelease]:
    """Every API-spec release currently listed, newest published first."""
    client = client or SppClient()
    releases: list[SpecRelease] = []
    for document in client.list_page_documents(page_id):
        if not document.filename.lower().endswith(".zip"):
            continue
        family = classify_family(document.title)
        if not family:
            LOGGER.debug("Not an API spec listing, skipping: %s", document.title)
            continue
        releases.append(
            SpecRelease(
                document=document,
                family=family,
                release_tag=release_tag(document.title, document.filename),
                draft=is_draft(document.title, document.filename),
            )
        )
    releases.sort(key=lambda r: (r.published_date or datetime.min), reverse=True)
    return releases


def newest_per_family(
    releases: list[SpecRelease], *, finals_only: bool = True
) -> dict[str, SpecRelease]:
    """The release to build a story from, per family.

    Ordered by PUBLISHED date, never by the filename tag (hazard 2). With
    ``finals_only`` a family that has only a draft yields nothing — the CUF
    slide's "Final Specifications published" date is the real go signal, and
    building against a draft is how you develop the wrong thing.
    """
    newest: dict[str, SpecRelease] = {}
    for release in releases:
        if finals_only and release.draft:
            continue
        current = newest.get(release.family)
        if current is None or (release.published_date or datetime.min) > (
            current.published_date or datetime.min
        ):
            newest[release.family] = release
    return newest


def archived_releases(
    family: str, *, archive_dir: Path = DEFAULT_ARCHIVE_DIR
) -> list[Path]:
    """Every archived zip for a family, oldest release tag first.

    This is what makes a real old-vs-new diff possible later: once two
    releases are archived we no longer depend on SPP bundling its own diff
    reports, nor on the revision-history phrasings staying stable.
    """
    folder = Path(archive_dir) / family_slug(family)
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.zip"), key=lambda p: (release_tag("", p.name), p.name))


def previous_release(
    family: str, current: Path, *, archive_dir: Path = DEFAULT_ARCHIVE_DIR
) -> Path | None:
    """The archived release immediately before ``current`` — the diff baseline."""
    current_tag = release_tag("", Path(current).name)
    earlier = [
        path
        for path in archived_releases(family, archive_dir=archive_dir)
        if release_tag("", path.name) < current_tag
    ]
    return earlier[-1] if earlier else None


def fetch_release(
    release: SpecRelease,
    *,
    client: SppClient | None = None,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
    state=None,
    dry_run: bool = False,
) -> tuple[Path | None, bool]:
    """Download one release into the archive. Returns ``(path, is_new)``.

    Never overwrites: an existing archived file is returned as-is (hazard 1 —
    an archived release is the only copy that still exists once SPP replaces
    the listing). ``state`` is an optional MetadataStore; when given, the
    release is recorded in the same ledger the RR flow uses.
    """
    target = release.archive_path(archive_dir)
    if target.exists():
        LOGGER.info("Already archived: %s", target.name)
        return target, False

    if dry_run:
        LOGGER.info("Dry-run: would download %s -> %s", release.document.url, target)
        return None, True

    client = client or SppClient()
    LOGGER.info("Downloading %s", release.label)
    download_to_path(release.document.url, target, timeout=300, session=client.session)

    if state is not None:
        state.record_document(
            release.document.document_id,
            release.filename,
            {
                "family": f"spec:{release.family}",
                "title": release.document.title,
                "url": release.document.url,
                "sha256": sha256_file(target),
                "local_path": str(target),
                "release_tag": release.release_tag,
                "draft": release.draft,
                "published_date": release.published_date.isoformat()
                if release.published_date
                else None,
            },
        )
    return target, True


def fetch_new_releases(
    *,
    client: SppClient | None = None,
    families: list[str] | None = None,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
    state=None,
    finals_only: bool = True,
    dry_run: bool = False,
) -> list[tuple[SpecRelease, Path | None, bool]]:
    """Archive the newest final release of each watched family.

    Defaults to ``[PRIMARY_FAMILY]``; pass ``families=[]`` to take every family
    on the page.
    """
    client = client or SppClient()
    wanted = [PRIMARY_FAMILY] if families is None else families
    newest = newest_per_family(list_releases(client), finals_only=finals_only)

    results = []
    for family, release in sorted(newest.items()):
        if wanted and family not in wanted:
            continue
        path, is_new = fetch_release(
            release, client=client, archive_dir=archive_dir, state=state, dry_run=dry_run
        )
        results.append((release, path, is_new))
    return results


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Discover/archive SPP API spec releases (FO)")
    ap.add_argument("--list", action="store_true", help="list what SPP publishes right now")
    ap.add_argument("--fetch", action="store_true", help="archive the newest final release")
    ap.add_argument("--family", action="append", help="family to fetch (repeatable); default RTO Markets")
    ap.add_argument("--all-families", action="store_true", help="fetch every family on the page")
    ap.add_argument("--include-drafts", action="store_true", help="allow drafts to win")
    ap.add_argument("--archive-dir", default=str(DEFAULT_ARCHIVE_DIR))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    archive_dir = Path(args.archive_dir)
    client = SppClient()

    if not args.list and not args.fetch:
        args.list = True

    releases = list_releases(client)

    if args.list:
        print(f"\nFuture Tech Specs (id={FUTURE_TECH_SPECS_PAGE_ID}) — {len(releases)} spec releases")
        print("=" * 88)
        for release in releases:
            archived = "archived" if release.archive_path(archive_dir).exists() else "NOT archived"
            print(f"  {release.label:<58} {archived}")
        print("\nNewest FINAL per family (what a story would be built from):")
        for family, release in sorted(newest_per_family(releases).items()):
            print(f"  {family:<28} -> {release.filename}")

    if args.fetch:
        families = [] if args.all_families else args.family
        print()
        results = fetch_new_releases(
            client=client,
            families=families,
            archive_dir=archive_dir,
            finals_only=not args.include_drafts,
            dry_run=args.dry_run,
        )
        if not results:
            print("No matching family on the page.")
        for release, path, is_new in results:
            status = "NEW" if is_new else "already archived"
            print(f"  [{status}] {release.label}")
            if path:
                print(f"      -> {path}")
                baseline = previous_release(release.family, path, archive_dir=archive_dir)
                print(f"      diff baseline: {baseline.name if baseline else 'NONE YET (first archived release)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
