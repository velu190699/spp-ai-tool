# SPP RR Automation

Minimal Python automation for collecting the latest SPP regulatory materials, identifying open and relevant Revision Requests (RRs), retaining new source files once, mirroring processed outputs to a local SharePoint-like folder, and logging a Slack-oriented notification draft.

V1 is intentionally stub-first. Real SharePoint upload, PCI stakeholder routing, and real Slack delivery are pending integration decisions.

## What It Does

The automation:

1. Searches SPP Documents & Filings for the latest matching:
   - RR Master List
   - CUF Meeting Materials
   - SUF Meeting Materials
   - Integrated Marketplace Protocols Active Version
2. Downloads only the latest matching document for each family.
3. Avoids duplicate processing using SPP document ID plus filename.
4. Parses the RR Master List Excel file and keeps rows where `Status = Open`.
5. Extracts all PDFs from the latest CUF ZIP and parses all of them.
6. Parses the latest SUF PDF.
7. Extracts RR mentions and all nearby dates from CUF/SUF text.
8. Intersects mentioned RRs with open RRs from the master list.
9. Downloads the package for each relevant RR and keeps only the first exact file named `RR <number> Recommendation Report.docx`.
10. Logs a Slack-style notification draft and writes JSON run outputs.

Integrated Marketplace Protocol is handled as a source archive only in v1. Its raw ZIP is retained locally forever, and its contents are not parsed or summarized.

## Credentials and Environment Variables

No credentials are required for `run` or `report` — both read from a locally
synced SharePoint/OneDrive folder.

`.env.example` documents:

- `SHAREPOINT_TENANT_ID` / `SHAREPOINT_CLIENT_ID` / `SHAREPOINT_CLIENT_SECRET` —
  only needed for `python main.py settlement-report --links ...` (live
  Microsoft Graph download of RR `.docx` files from SharePoint share links).
  Requires an Azure app registration with the `Sites.Read.All` application
  permission. Not needed for `--files` mode.
- `SHAREPOINT_SITE_ID` / `SHAREPOINT_DRIVE_ID` — reserved for future direct
  drive addressing; unused by the current share-link resolution flow.
- `SLACK_WEBHOOK_URL` / `SLACK_BOT_TOKEN` / `SLACK_CHANNEL`

Real SharePoint upload for `run`'s own outputs remains pending in this README
because the expected Microsoft Graph auth mode for that flow has not been
selected.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Playwright is included for future visible-browser flows. The current v1 implementation uses HTTP discovery/downloads against public SPP pages.

## Run

Dry-run discovery without downloading or storing:

```bash
python main.py run --dry-run
```

Normal run:

```bash
python main.py run
```

Generate the SPP Market Changes Summary HTML report (on demand):

```bash
python main.py report
```

Generate the SPP RR → Jira Settlement Excel report (on demand):

```bash
python main.py settlement-report --call-claude
```

## Market Changes Summary Report

`python main.py report` produces a self-contained, two-tab HTML report
("Executive Overview" by PCI area + "Full Summary" narrative) from the latest
CUF/SUF materials.

- **Source**: reads the newest CUF meeting subfolder and newest SUF PDF from the
  locally synced SharePoint folders (`cuf_dir` / `suf_dir` in `config.yaml`).
  Citations link back to `mypci.sharepoint.com`, mapped from the local path via
  `sharepoint.base_url` + `sharepoint.sync_root`.
- **Summarization engine** (`report.engine` in `config.yaml`):
  - `claude_code` (default): shells out to the bundled Claude Code CLI in
    headless mode, reusing your existing login. No API key, no separate billing.
    The newest VSCode-extension build is auto-discovered; override with
    `report.claude_code_binary`. Optionally pin a model with `report.model`.
  - `stub`: returns fixed sample data — lets you build/test ingestion, the data
    contract, and HTML rendering offline with no model access.
- **Output**: `data/reports/SPP_Market_Changes_Summary-<timestamp>.html`.

The engine only ever emits structured JSON (validated against the contract in
`src/summaries/report_model.py`); all HTML layout is deterministic
(`src/summaries/html_renderer.py`), so output is consistent across runs.

Runtime configuration lives in `config.yaml` for local paths and logging. SPP search terms and matching rules are hardcoded in `config.py` and `main.py` by design for v1.

## SPP RR → Jira Settlement Report

`python main.py settlement-report` produces `SPP_RR_Report_Summary-<timestamp>.xlsx`,
a Jira-intake artifact for the **settlement development team** — a different
audience from the Market Changes Summary above, which briefs all PCI teams.
Each RR is triaged, and only RRs that actually change a settlement charge code
get development stories; everything else is routed to a human reviewer instead
of being silently dropped.

- **Source**: by default, every `.docx` already downloaded into
  `recommendation_reports_dir` by `python main.py run`. Pass `--files a.docx b.docx`
  to target specific local files, or `--links links.txt` (one SharePoint share
  URL per line) to download directly via Microsoft Graph — see
  [Credentials and Environment Variables](#credentials-and-environment-variables).
- **Extraction** (`src/settlement/rr_structure.py`): reads `word/document.xml`
  directly (not flattened text) so headings, tracked-change redlines
  (`{{INS}}`/`{{DEL}}`), and equations survive. Classifies each RR as
  `SETTLEMENT_CALC` (has charge-code determinants — extract stories),
  `SETTLEMENT_RELEVANT` (settlement impact stated only in Tariff prose — needs
  a human to author the story), or `TARIFF_GOVERNANCE` (out of scope). A
  **hard-fail reconciliation gate** compares the RR's own "Impacted SPP
  Documents" checklist against what was actually found in the body; any gap
  stops that RR for manual review rather than silently under-reporting.
- **Story generation** (`--call-claude`): for `SETTLEMENT_CALC` + `PASS` RRs
  only, reuses the same LLM engine as the Market Changes Summary
  (`report.engine`/`claude_code_binary`/`model` in `config.yaml`) with a
  dedicated prompt (`src/settlement/rr_extraction_prompt.md`) that emits one
  Jira story per charge code, each with a page-anchored citation. Omit the
  flag for a fast classification-only triage pass.
- **Output**: `data/reports/settlement/SPP_RR_Report_Summary-<timestamp>.xlsx`
  (`settlement_reports_dir` in `config.yaml`), with an "RR Summary" sheet (one
  row per RR) and a "Settlement Stories" sheet (one row per charge type).

To validate extraction on a new RR before trusting it:

```bash
python -m src.settlement.rr_structure --file "RR900 Recommendation Report.docx" --out-json rr900.json
```

Check `rr_class` and `reconciliation.status` in the output: `PASS` means trust
the charge-type index; `HARD_FAIL` means open the RR and compare "Impacted
Documents" against the sections found — usually a formatting quirk in the
detector, or a genuinely missing redline.

## Duplicate Detection

V1 treats a document as duplicate when the SPP document ID and filename have already been tracked in `data/state/metadata.json`.

If the same SPP document ID and filename later produce a different SHA-256 hash, the automation logs a warning but does not store a new copy. Raw downloads are retained forever in `data/downloads/`.

## SharePoint Storage

V1 does not upload to SharePoint. It uses a local filesystem mirror under `data/sharepoint_mirror/` with the same document-type layout intended for a future SharePoint library:

- `rr-master-list/`
- `cuf-meeting-materials/`
- `suf-meeting-materials/`
- `recommendation-reports/`

Protocol ZIPs are retained only as raw local downloads in v1.

## Summaries and Slack Notifications

V1 summary generation is structured extraction only:

- mentioned RRs
- relevant open RRs after master-list intersection
- dates found near RR mentions
- warnings and skipped items

No LLM prose summary, PCI division/market mapping, or stakeholder routing is attempted in v1.

The notification module formats and logs a Slack-oriented draft. Real Slack sending is pending and should be added after stakeholder routing and channel/webhook ownership are defined.

## Outputs

Normal runs write:

- `data/reports/run-<timestamp>.json`
- `data/reports/relevant-rrs-<timestamp>.json`
- `logs/run-<timestamp>.log`

Dry runs log the run summary but do not write report/state files.

## Tests

```bash
pytest
```

Normal tests are deterministic and do not require external services. Live SPP checks can be added later behind an explicit opt-in marker.
