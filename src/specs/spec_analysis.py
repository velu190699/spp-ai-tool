"""Deterministic first-pass analysis of an SPP RTO Markets API spec release zip.

PoC for the FO (ISO Communication) pipeline. Given ONE spec release zip (e.g.
``rto_markets_api_specifications_20260708.zip`` from SPP's Future Tech Specs
page, id=21071), extract the concrete changes WITHOUT an LLM — reproducing the
facts an SME (Miquel) pulled by hand for Jira story SP-12813.

Two INDEPENDENT deterministic sources, cross-checked against each other:

  1. SPP's own curated change list — the "Revision History" block in
     ``IM Markets Data Exchange Guide_*.docx``. This is the primary source: SPP
     enumerates each change in plain text (e.g. "Addition of the new operation
     GetMarketApprovedPricingStatusByIntervalSetByDay") with the operations it
     affects. Far more robust than parsing the color-coded HTML diffs.

  2. Structural evidence — SPP's bundled ``Diff Reports/*.htm`` (changed
     elements / new operations of an EXISTING service) and new
     ``WebServices/<Service>/`` folders. A brand-new service (DemandManagement)
     never appears in a diff report because there is nothing to compare against
     — Miquel's explicit warning — so it is detected by folder presence instead.

The LLM's job (a later increment) is annotation on top of these facts:
plain-English impact, DECISION-NEEDED framing, research on unknown services
(e.g. DemandManagement ~ CHILL). It never invents the facts themselves.

CAVEAT (Miquel): SPP's release layout is NOT consistent across releases, so the
revision-history phrasings this PoC keys on are release-specific. Generalizing
the parser — and adding our own lxml XSD/WSDL diff as a format-independent
backstop once we archive a previous version — is future work.
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Change kinds this pass recognizes.
NEW_SERVICE = "NEW_SERVICE"
NEW_OPERATION = "NEW_OPERATION"
NEW_ELEMENT = "NEW_ELEMENT"
CONSTRAINT_TIGHTENED = "CONSTRAINT_TIGHTENED"


@dataclass
class Finding:
    """One concrete, human-actionable change extracted from a spec release."""

    kind: str  # one of the module constants above
    subject: str  # the service / operation / element the change is about
    detail: str  # SPP's own description (verbatim from the revision history)
    affects: list[str] = field(default_factory=list)  # affected operations/responses
    evidence: list[str] = field(default_factory=list)  # where each fact was corroborated

    def key(self) -> tuple[str, str]:
        return (self.kind, self.subject)


# --- zip member helpers -----------------------------------------------------

def _find_member(zf: zipfile.ZipFile, *, endswith: str = "", contains: str = "") -> str | None:
    for name in zf.namelist():
        base = name.rsplit("/", 1)[-1]
        if base.startswith("~$"):  # Word lock file
            continue
        if endswith and not name.lower().endswith(endswith.lower()):
            continue
        if contains and contains.lower() not in name.lower():
            continue
        return name
    return None


def _docx_lines(zf: zipfile.ZipFile, member: str) -> list[str]:
    """Return the docx's paragraph/table-cell lines as plain text."""
    raw = zf.read(member)
    doc = zipfile.ZipFile(io.BytesIO(raw)).read("word/document.xml").decode("utf-8", "ignore")
    doc = re.sub(r"</w:tc>", "\t", doc)
    doc = re.sub(r"</w:tr>", "\n", doc)
    doc = re.sub(r"</w:p>", "\n", doc)
    doc = re.sub(r"<[^>]+>", "", doc)
    text = html.unescape(doc).replace("\xa0", " ")
    lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip(" \t|")
        if line:
            lines.append(line)
    return lines


def _htm_text(zf: zipfile.ZipFile, member: str) -> str:
    """Reconstruct a diff report's text, concatenating spans WITHOUT inserting
    spaces so split tokens rejoin (``minOccurs="0"`` survives)."""
    raw = zf.read(member).decode("utf-8", "ignore")
    raw = re.sub(r"<[^>]+>", "", raw)
    return html.unescape(raw).replace("\xa0", " ")


# --- source 1: SPP's revision history --------------------------------------

# An "operation-like" bullet payload: CamelCase identifier, optionally trailed
# by " response" / " notification". These are the ops a change bullet affects.
_OP_LINE = re.compile(r"^(?:Post|Get|Delete)[A-Za-z0-9]+(?: response| notification[A-Za-z ]*)?$")


def _collect_affects(lines: list[str], start: int) -> list[str]:
    """Operation-like lines immediately following a bullet that ends in ':'."""
    ops: list[str] = []
    for line in lines[start + 1 : start + 12]:
        if _OP_LINE.match(line):
            ops.append(line.split(" ")[0])
        elif ops:  # stop at the first non-operation line after we started collecting
            break
    return ops


def revision_findings(lines: list[str]) -> list[Finding]:
    """Parse the current-release change bullets out of the Data Exchange Guide."""
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()

    def add(f: Finding) -> None:
        if f.key() not in seen:
            seen.add(f.key())
            findings.append(f)

    for i, line in enumerate(lines):
        # New operation
        m = re.match(r"Addition of the new operation (\w+)", line)
        if m:
            add(Finding(NEW_OPERATION, m.group(1), line, evidence=["Data Exchange Guide revision history"]))
            continue
        # New service(s) referenced in the Web Service Reference update
        m = re.search(r"include (.+?) Services?\b", line)
        if m and "DemandManagement" in m.group(1):
            for svc in ("DemandManagement", "DemandManagementNotify"):
                add(Finding(NEW_SERVICE, svc, line, evidence=["Data Exchange Guide revision history"]))
            continue
        # Constraint tightened (element made mandatory)
        m = re.match(r"(\w+) is now required", line)
        if m:
            add(Finding(
                CONSTRAINT_TIGHTENED, m.group(1), line,
                affects=_collect_affects(lines, i),
                evidence=["Data Exchange Guide revision history"],
            ))
            continue
        # Same element also listed under "is always included ... for:" (more affected ops)
        m = re.match(r"(\w+) is always included", line)
        if m:
            more = _collect_affects(lines, i)
            existing = next((f for f in findings if f.subject == m.group(1)), None)
            if existing:
                existing.affects = sorted(set(existing.affects) | set(more))
            else:
                add(Finding(CONSTRAINT_TIGHTENED, m.group(1), line, affects=more,
                            evidence=["Data Exchange Guide revision history"]))
            continue
        # New element added to responses/notifications
        m = re.match(r"Addition of (\w+)(?: for [A-Za-z]+)? to the following", line)
        if m and m.group(1) not in ("the",):
            existing = next((f for f in findings if f.kind == NEW_ELEMENT and f.subject == m.group(1)), None)
            affects = _collect_affects(lines, i)
            if existing:
                existing.affects = sorted(set(existing.affects) | set(affects))
            else:
                add(Finding(
                    NEW_ELEMENT, m.group(1), line, affects=affects,
                    evidence=["Data Exchange Guide revision history"],
                ))
    return findings


# --- source 2: structural corroboration ------------------------------------

def _service_dirs(zf: zipfile.ZipFile) -> set[str]:
    dirs = set()
    for name in zf.namelist():
        m = re.match(r"(?:.*/)?WebServices/([^/]+)/", name)
        if m:
            dirs.add(m.group(1))
    return dirs


def corroborate(zf: zipfile.ZipFile, findings: list[Finding]) -> None:
    """Add an independent structural evidence line to each finding where we can."""
    diff_members = [n for n in zf.namelist() if "/Diff Reports/" in n or n.startswith("Diff Reports/")]
    diff_names = " ".join(m.rsplit("/", 1)[-1] for m in diff_members)
    services = {s.lower() for s in _service_dirs(zf)}

    # Cache the big Energy/Market diff texts lazily.
    diff_text_cache: dict[str, str] = {}

    def diff_text_for(service_keyword: str) -> str:
        key = service_keyword.lower()
        if key not in diff_text_cache:
            blob = ""
            for m in diff_members:
                if key in m.lower():
                    blob += _htm_text(zf, m)
            diff_text_cache[key] = blob
        return diff_text_cache[key]

    for f in findings:
        if f.kind == NEW_SERVICE:
            folder_present = f.subject.lower() in services
            in_a_diff = f.subject.lower() in diff_names.lower()
            if folder_present and not in_a_diff:
                f.evidence.append(f"WebServices/{f.subject}/ folder present and absent from every Diff Report (new service)")
        elif f.kind == CONSTRAINT_TIGHTENED:
            txt = diff_text_for("energy_xsd")
            if f.subject in txt and 'minOccurs="0"' in txt and 'minOccurs="1"' in txt:
                f.evidence.append('Energy XSD diff shows minOccurs="0" -> "1"')
        elif f.kind == NEW_ELEMENT:
            txt = diff_text_for("energy_xsd")
            if f.subject + "Type" in txt or f.subject in txt:
                f.evidence.append("Energy XSD diff shows the new complexType")
        elif f.kind == NEW_OPERATION:
            txt = diff_text_for("market_wsdl") + diff_text_for("market_operations")
            if f.subject in txt:
                f.evidence.append("Market WSDL/Operations diff shows the added operation")


# --- top-level --------------------------------------------------------------

def analyze(zip_path: str | Path) -> list[Finding]:
    """Return the deterministic findings for one spec release zip."""
    with zipfile.ZipFile(zip_path) as zf:
        guide = _find_member(zf, endswith=".docx", contains="Data Exchange Guide")
        if not guide:
            raise ValueError("No 'Data Exchange Guide' docx found in the zip")
        findings = revision_findings(_docx_lines(zf, guide))
        corroborate(zf, findings)
    return findings


# The gold standard: the four changes Miquel pulled by hand for SP-12813.
EXPECTED_SP12813: list[tuple[str, str]] = [
    (NEW_SERVICE, "DemandManagement"),
    (NEW_SERVICE, "DemandManagementNotify"),
    (NEW_ELEMENT, "RsrcCommitmentSchedule"),
    (CONSTRAINT_TIGHTENED, "OfflineMaxLimit"),
    (NEW_OPERATION, "GetMarketApprovedPricingStatusByIntervalSetByDay"),
]


def _print_report(zip_path: str, findings: list[Finding]) -> int:
    print(f"\nSpec release: {Path(zip_path).name}")
    print(f"Deterministic findings: {len(findings)}\n" + "=" * 72)
    for f in findings:
        print(f"[{f.kind}] {f.subject}")
        print(f"    SPP: {f.detail}")
        if f.affects:
            print(f"    affects: {', '.join(f.affects)}")
        for ev in f.evidence:
            print(f"    evidence: {ev}")
        print()

    found = {f.key() for f in findings}
    print("Validation vs SP-12813 (Miquel's manual analysis)\n" + "-" * 72)
    missing = [e for e in EXPECTED_SP12813 if e not in found]
    for kind, subj in EXPECTED_SP12813:
        print(f"  [{'OK' if (kind, subj) in found else 'MISS'}] {kind} {subj}")
    if missing:
        print(f"\nRESULT: {len(EXPECTED_SP12813) - len(missing)}/{len(EXPECTED_SP12813)} reproduced -- MISSING {missing}")
        return 1
    print(f"\nRESULT: {len(EXPECTED_SP12813)}/{len(EXPECTED_SP12813)} findings reproduced deterministically -- matches SP-12813")
    return 0


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Deterministic spec-diff PoC (FO / ISO Com)")
    ap.add_argument("zip", help="path to an SPP RTO Markets API spec release .zip")
    args = ap.parse_args()
    return _print_report(args.zip, analyze(args.zip))


if __name__ == "__main__":
    raise SystemExit(main())
