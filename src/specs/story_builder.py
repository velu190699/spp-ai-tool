"""Assemble the SP-12813-shaped ISO Communication story from a spec release.

FO analog of the BO settlement story writer. Given one spec release zip, build
the SAME story Miquel wrote by hand (SP-12813) — but DETERMINISTICALLY: every
fact comes from the spec zip (via ``spec_analysis``) or the CUF "Web Service
Update" slide. No LLM. The prose fields Miquel wrote in English (Use Case, the
plain-language impact wrapper, the sample XMLs) are left as explicit
``[LLM LATER]`` placeholders — this pass proves the structure and the facts.

Grain mirrors BO exactly: 1 spec release -> 1 ISOCOM story, with the individual
change items playing the role BO's per-determinant changes play (the story's
"items"). ISO Com impact is listed BY OPERATION (no operation->ISOC-task map
yet; that enrichment lands when the SME supplies spp_operation_map.yaml).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from src.specs.spec_analysis import (
    CONSTRAINT_TIGHTENED, NEW_ELEMENT, NEW_OPERATION, NEW_SERVICE,
    Finding, analyze,
)


@dataclass
class ImpactItem:
    operation: str
    change: str          # deterministic description of what changed
    evidence: str = ""   # e.g. minOccurs="0" -> "1"


@dataclass
class Story:
    summary: str
    new_services: list[str] = field(default_factory=list)
    version_changes: list[str] = field(default_factory=list)  # "Energy v22 -> v23"
    dates: dict = field(default_factory=dict)
    source_zip: str = ""
    source_url: str = "https://www.spp.org/spp-documents-filings/?id=21071"
    impact: list[ImpactItem] = field(default_factory=list)


# --- deterministic extraction from the zip ---------------------------------

def _version_changes(zf: zipfile.ZipFile) -> list[str]:
    """Read `<Service>_..._diff_vA_vB.htm` diff-report names -> version bumps."""
    bumps: dict[str, tuple[str, str]] = {}
    for name in zf.namelist():
        base = name.rsplit("/", 1)[-1]
        m = re.match(r"([A-Za-z]+)_(?:XSD|WSDL|Operations_XSD)_diff_v(\d+)_v(\d+)\.htm", base)
        if m:
            bumps[m.group(1)] = (m.group(2), m.group(3))
    return [f"{svc} v{a} -> v{b}" for svc, (a, b) in sorted(bumps.items())]


def _new_service_version(zf: zipfile.ZipFile, svc: str) -> str:
    for name in zf.namelist():
        m = re.search(rf"WebServices/{svc}[^/]*/.*_specifications_v(\d+)\.docx$", name, re.I)
        if m:
            return f"v{m.group(1)}"
    return "v1"


def _impact_items(findings: list[Finding]) -> list[ImpactItem]:
    """One row per (change, affected operation), the way SP-12813 lists them."""
    items: list[ImpactItem] = []
    for f in findings:
        if f.kind == NEW_ELEMENT and f.affects:
            ev = 'new complexType in XSD diff'
            for op in f.affects:
                items.append(ImpactItem(op, f"New element {f.subject} ({f.detail.rstrip(':')})", ev))
        elif f.kind == CONSTRAINT_TIGHTENED and f.affects:
            for op in f.affects:
                items.append(ImpactItem(op, f"{f.subject} now mandatory when MaxOfflineResponse present",
                                        'minOccurs="0" -> "1"'))
        elif f.kind == NEW_OPERATION:
            items.append(ImpactItem(f.subject, "New query operation added", "added in Market WSDL/Operations diff"))
    return items


def build_story(zip_path: str | Path, dates: dict | None = None) -> Story:
    findings = analyze(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        versions = _version_changes(zf)
        services = []
        for f in findings:
            if f.kind == NEW_SERVICE:
                services.append(f"{f.subject} {_new_service_version(zf, f.subject)}")
    return Story(
        summary="[SPPIM: ISO Communication] Add new Energy and Market services to ISO Com",
        new_services=services,
        version_changes=versions,
        dates=dates or {},
        source_zip=Path(zip_path).name,
        impact=_impact_items(findings),
    )


# --- CUF slide date block (deterministic, from the Market Releases PDF) -----

def parse_release_dates(pdf_path: str | Path) -> dict:
    import pypdf
    text = " ".join((pg.extract_text() or "") for pg in pypdf.PdfReader(str(pdf_path)).pages)
    text = re.sub(r"\s+", " ", text)

    def grab(pat: str) -> str:
        m = re.search(pat, text, re.I)
        return m.group(1).strip() if m else ""

    return {
        "member_impacting": grab(r"Member impacting\?\s*(Yes|No)"),
        "draft_published": grab(r"Draft Specifications published[^0-9]*(\d{1,2}/\d{1,2}/\d{4})"),
        "final_published": grab(r"Final Specifications published[^0-9]*(\d{1,2}/\d{1,2}/\d{4})"),
        "activation_mte": grab(r"MTE\D*(\d{1,2}/\d{1,2}/\d{4})"),
        "activation_prod": grab(r"PROD\D*(\d{1,2}/\d{1,2}/\d{4})"),
        "retirement": grab(r"Retirement date:?\s*(\d{1,2}/\d{1,2}/\d{4})"),
    }


# --- render (markdown, for review vs SP-12813) ------------------------------

def render_markdown(story: Story) -> str:
    d = story.dates
    L = ["# " + story.summary, ""]
    L += ["## Use Case / Problem Definition", "_[LLM LATER — Miquel's framing]_ "
          "Update SPP's XSDs and WSDLs in Nexus and GSMS to support the new services; "
          "update the ISO Cacher to use the new XSDs/WSDLs for EnergyNotify and MarketNotify.", ""]
    L += ["## Changes"]
    if story.new_services:
        L.append("**New services:** " + ", ".join(story.new_services) + "  _[fact: diff]_")
    for v in story.version_changes:
        L.append(f"- {v}  _[fact: diff]_")
    L.append("- Update the ISOC_XSD_Versions LOV file for all these services.  _[boilerplate]_")
    if d:
        L.append(f"- Member impacting: **{d.get('member_impacting','?')}** · "
                 f"Final specs published {d.get('final_published','?')} · "
                 f"Activation MTE {d.get('activation_mte','?')} / PROD {d.get('activation_prod','?')} · "
                 f"V22/V17 retirement {d.get('retirement','?')}.  _[fact: CUF slide]_")
    L.append("- System Version / Effective Date: _[not in the zip — from SPP release notes / SME]_")
    L += ["", "## Investigation Done / Background",
          f"Current specs: `{story.source_zip}` — Source: {story.source_url}  _[fact: fetch]_",
          "_[LLM LATER]_ Review whether newer specs were posted before starting development; "
          "services can't be tested until the activation-test date.", "",
          "**ISO Com impact** _(by operation — ISOC-task grouping pending spp_operation_map.yaml)_:"]
    for it in story.impact:
        line = f"- `{it.operation}` — {it.change}"
        if it.evidence:
            line += f"  ·  _{it.evidence}_"
        L.append(line)
        L.append(f"    - sample XML: _[LLM LATER — generate from XSD]_")
    L += ["", "## Acceptance Criteria / Definition of Done",
          "_[boilerplate]_ DST dates impact tested; all-markets regression on the affected ISOC tasks; "
          "JARs regenerated and aligned with the new interfaces."]
    return "\n".join(L)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Assemble the ISOCOM story skeleton from a spec zip (no LLM)")
    ap.add_argument("zip")
    ap.add_argument("--slide", help="path to the CUF 'Market Releases' PDF for the date block")
    args = ap.parse_args()
    dates = parse_release_dates(args.slide) if args.slide else {}
    story = build_story(args.zip, dates=dates)
    print(render_markdown(story))
    # Coverage check vs SP-12813's ISO Com operation list
    expected_ops = {
        "GetEnergyCommitmentSet", "GetEnergyCommitmentSetByDay", "PostEnergyCommitmentSet",
        "PostEnergyMCRTransitionOfferSet", "GetEnergyMCRTransitionOfferSetByDay",
        "GetEnergyMCRTransitionMitigatedParameterSetByDay",
        "GetMarketApprovedPricingStatusByIntervalSetByDay",
    }
    got = {it.operation for it in story.impact}
    missing = expected_ops - got
    print("\n" + "-" * 60)
    print(f"SP-12813 operation coverage: {len(expected_ops & got)}/{len(expected_ops)}"
          + (f"  MISSING {missing}" if missing else "  — all operations covered"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
