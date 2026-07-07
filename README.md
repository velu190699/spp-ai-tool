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

No credentials are required for v1.

`.env.example` documents pending future variables:

- `SHAREPOINT_TENANT_ID`
- `SHAREPOINT_CLIENT_ID`
- `SHAREPOINT_CLIENT_SECRET`
- `SHAREPOINT_SITE_ID`
- `SHAREPOINT_DRIVE_ID`
- `SLACK_WEBHOOK_URL`
- `SLACK_CHANNEL`

Real SharePoint auth remains pending in this README because the expected Microsoft Graph auth mode has not been selected.

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
