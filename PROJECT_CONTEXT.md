# SPP Market Intelligence Agent — Full Project Context

> **Historical snapshot.** This document was written early in the project (translated from the original Spanish, `CONTEXTO_COMPLETO_PROYECTO.md`) as a handoff/onboarding brief. Several items it lists as "missing" or "pending" have since been implemented — the Claude summarizer, real Slack delivery, and the RR settlement pipeline all now exist. Kept for historical context; see `README.md` for current behavior.

## 📋 EXECUTIVE SUMMARY

We are building an **automated software agent** that monitors regulatory changes in the SPP/SPPIM market (energy trading). The agent downloads documents, identifies relevant changes using AI (Claude), and automatically notifies stakeholders.

**Goal:** Eliminate the manual work of reviewing SPP.org documents every month and generating reports.

---

## 🏗️ PROJECT ARCHITECTURE

### Phase 1: GATHERING (Information Collection) ← WE ARE HERE

**Input:** Documents from SPP.org
**Output:** Executive summary with relevant RRs (Revision Requests)

**Pipeline (5 stages):**

1. **TRIGGER** → Windows Task Scheduler runs `run_agent.bat` (monthly/quarterly execution)
2. **WEB SCRAPING** → Downloads 4 documents from SPP.org in parallel:
   - RR Master List (Excel)
   - CUF Meeting Materials (ZIP → PDFs)
   - SUF Meeting Materials (PDF)
   - Integrated Marketplace Protocol (ZIP)
3. **DATA PROCESSING** → Processes data:
   - Parses Excel: filters RRs with Status='Open'
   - Extracts text from PDFs
   - **Cross-reference:** intersects RRs mentioned in CUF/SUF ∩ open RRs = list of relevant ones
4. **AI/LLM** → Claude API generates:
   - Content summary: changes, area, timeline
   - Executive summary: highlights of what matters most
5. **OUTPUT** → Distributes:
   - Email to PCI Organization
   - Email to Stakeholders
   - Slack notification
   - SharePoint (historical archive)

### Phase 2: ANALYSIS (Settlement Protocol Comparison)
Compare protocol versions v118 vs v117, detect undocumented changes.

### Phase 3: STORY CREATION (Jira Integration)
Automatically generate Jira stories based on detected changes.

---

## 💾 CODE STATUS (AT TIME OF WRITING)

Your teammate has implemented **steps 1-3 of the pipeline** (Trigger → Scraping → Processing).
What's **MISSING** to implement:
- ❌ **Claude API Summarizer** (`summarizer.py` is empty)
- ❌ **Real email** (SMTP/MS Graph Mail) — IT blocker
- ⚠️ **Real Slack** (log draft only)
- ⚠️ **Real SharePoint** (currently LocalSharePointClient, a local mock)

---

## 🎯 NEXT MILESTONE: Implement Claude Integration

**What we're going to do:**
1. Take the text extracted from the CUF/SUF PDFs
2. Send it to the Claude API with a structured prompt
3. Receive a JSON with an executive summary
4. Save it and prepare it for email/Slack

**Inputs to Claude:**
- Raw text extracted from the CUF/SUF PDF
- List of relevant RRs (IDs + metadata)
- Context: what changes are coming, when, which documents are impacted

**Expected outputs from Claude:**
```json
{
  "summary": "2-3 paragraph summary of what's changing",
  "key_rrs": [
    {
      "rr_number": "782",
      "title": "RTO Expansion...",
      "impact": "High",
      "timeline": "Fall 2026",
      "description": "Changes to market rules..."
    }
  ],
  "dates": ["Fall 2026", "Q4 2026"],
  "highlights": [
    "Critical change to settlement calculations",
    "New rules for generator participation"
  ]
}
```

---

## 🔧 TECH STACK

### Core
- **Python 3.11+** — main language
- **Flask** — local dashboard (optional)
- **Windows Task Scheduler** — trigger (not in code, it's OS config)

### Web Scraping & Downloads
- **requests** — HTTP downloads
- **BeautifulSoup4** — HTML parsing for SPP.org
- **Playwright** — browser automation (reserved for complex flows)

### Data Processing
- **pandas** 🔄 ← **WE'LL USE THIS NOW** (improvement over current code)
- **openpyxl** — Excel reading
- **pypdf** — text extraction from PDFs
- **PyMuPDF/pdfplumber** — more robust alternatives for PDFs with tables

### AI/LLM
- **Anthropic Claude API** — model `claude-sonnet-4-20250514`
- Features: structured output, vision (if we need to process document images)

### Cloud & Storage
- **MS Graph API** — SharePoint access (when ready)
- **azure-identity** / **azure-storage** — authentication and storage

### Notifications
- **SMTP (PCI server)** — email sending (current blocker: no credentials)
- **MS Graph Mail API** — alternative for email via Outlook
- **slack-sdk** — sending to Slack

### Config & Security
- **PyYAML** — configuration files
- **python-dotenv** — environment variables
- **keyring** — secure credential storage

### Testing & Logging
- **pytest** — unit tests
- **logging** — structured logging with timestamps

---

## 📁 PROJECT STRUCTURE (AT TIME OF WRITING)

```
spp-rr-automation/
├── main.py                              # Main orchestrator
├── config.py                            # Configuration (not included in upload)
├── requirements.txt                     # Python dependencies
├── run_agent.bat                        # Script that launches main.py (Windows)
│
├── src/
│   ├── browser/
│   │   ├── __init__.py
│   │   ├── spp_client.py               # Client for scraping SPP.org
│   │   └── download_utils.py           # Utilities: sanitize, hash, download
│   │
│   ├── documents/
│   │   ├── __init__.py
│   │   ├── excel_parser.py             # Reads RR Master List (openpyxl)
│   │   ├── pdf_parser.py               # Extracts text from PDFs (pypdf)
│   │   ├── rr_extractor.py             # Regex for RR mentions
│   │   └── zip_utils.py                # Extracts files from ZIPs (safe)
│   │
│   ├── notifications/
│   │   ├── __init__.py
│   │   └── notifier.py                 # Slack draft (not sending yet)
│   │
│   ├── sharepoint/
│   │   ├── __init__.py
│   │   └── sharepoint_client.py        # LocalSharePointClient (mock)
│   │
│   ├── state/
│   │   ├── __init__.py
│   │   └── metadata_store.py           # State: hashes, downloaded documents
│   │
│   └── summaries/
│       ├── __init__.py
│       └── summarizer.py               # ❌ EMPTY — Claude integration goes here
│
├── logs/
│   └── run-YYYYMMDD-HHMMSS.log        # Logs per execution
│
├── downloads/                           # Temporary downloads
│   ├── rr_master_list/
│   ├── cuf/
│   ├── suf/
│   ├── protocol/
│   └── recommendation_reports/
│
├── extracted/                           # Files extracted from ZIPs
│   ├── cuf/
│   ├── suf/
│   └── recommendation_reports/
│
├── reports/                             # JSON reports per execution
│   ├── run-YYYYMMDD-HHMMSS.json
│   └── relevant-rrs-YYYYMMDD-HHMMSS.json
│
└── sharepoint_mirror/                   # Local SharePoint mock (testing)
```

---

## 🔑 KEY CONCEPTS

### RR (Revision Request)
A proposed change to the SPP market protocol/rules. It has:
- Unique number (e.g., RR782, RR623)
- Status: Open, Approved, Rejected, etc.
- Title and description
- Impacted documents: market rules, calculations, GUI, extracts
- Primary Working Group proposing it
- Release dates (Fall 2026, etc.)

### CUF (Congestion Users Forum)
**Monthly** meetings where upcoming changes are discussed. Published documents contain:
- Agenda and meeting materials
- Mentions of upcoming RRs
- Upcoming releases

### SUF (Settlement Users Forum)
**Quarterly** meetings about settlement. Documents contain:
- Release notes (e.g., "Fall 2026 Release")
- RRs that will affect settlement
- Impact on calculations and processes

### Cross-Reference
The critical step where we intersect:
- RRs mentioned in CUF/SUF PDFs
- With RRs that are "Open" in the Master List
- The **intersection** = relevant RRs to monitor

---

## 📊 EXECUTION FLOW (DETAILED)

```
1. Windows Task Scheduler launches run_agent.bat
   ↓
2. run_agent.bat runs: python main.py run [--dry-run]
   ↓
3. main.py orchestrates:
   ├─ Loads config (config.py)
   ├─ Initializes logging (logs_dir/)
   ├─ Loads previous state (metadata_store.json) to avoid reprocessing
   │
   ├─ Creates SppClient (SPP.org scraper)
   │
   ├─ Searches for 4 documents on SPP.org:
   │   ├─ RR Master List (latest .xlsx)
   │   ├─ CUF Meeting Materials (latest .zip)
   │   ├─ SUF Meeting Materials (latest .pdf)
   │   └─ Integrated Marketplace Protocol (latest .zip, optional)
   │
   ├─ For each document:
   │   ├─ Checks if already downloaded (by ID + name + hash)
   │   ├─ If not, downloads it
   │   └─ Saves metadata (ID, URL, SHA256 hash, local_path)
   │
   ├─ Parses RR Master List:
   │   ├─ Reads Excel with openpyxl
   │   └─ Filters only Status='Open' → dict of RRRecord
   │
   ├─ Processes CUF (if new):
   │   ├─ Extracts PDFs from the ZIP
   │   ├─ For each PDF:
   │   │   ├─ Extracts text with pypdf
   │   │   ├─ Searches for RR mentions with regex (RRN, RR-N, RR N)
   │   │   ├─ Extracts associated dates
   │   │   └─ Uploads PDF to SharePoint
   │   └─ Saves mention metadata
   │
   ├─ Processes SUF (if new):
   │   └─ Same as CUF, but it's a single PDF
   │
   ├─ Cross-reference:
   │   ├─ Intersects: mentioned_RRs ∩ Open_RRs = relevant_RRs
   │   └─ For each relevant RR, downloads its Recommendation Report
   │
   ├─ ⭐ CLAUDIFICATION (THIS IS WHERE YOUR WORK COMES IN):
   │   ├─ Claude Summarizer: extracts changes from CUF/SUF
   │   └─ Claude Executive Summary: consolidates everything with highlights
   │
   ├─ Stores in SharePoint:
   │   ├─ Downloaded documents
   │   ├─ Recommendation Reports
   │   └─ Executive summary (JSON)
   │
   ├─ Sends notifications:
   │   ├─ Email to PCI Organization
   │   ├─ Email to Stakeholders
   │   └─ Slack to the market updates channel
   │
   ├─ Saves reports:
   │   ├─ run-ID.json (full execution summary)
   │   └─ relevant-rrs-ID.json (relevant RRs only)
   │
   └─ Updates state (metadata_store.json) for the next execution
```

---

## ⚡ CRITICAL POINT: CROSS-REFERENCE

This is the heart of the agent and what differentiates it from a simple downloader.

**Example:**
```
RR Master List has: RR782, RR623, RR728 (Status='Open')
CUF PDF mentions: "RR782 will be implemented in Fall 2026, RR623..."
SUF PDF mentions: "Fall 2026 Release includes RR623, RR728"

Result: Relevant RRs = {782, 623, 728}
(the ones that are OPEN and are also mentioned in meetings)
```

This lets you filter out noise: there are hundreds of open RRs, but only a few are close to being implemented.

---

## 🎬 NEXT STEPS (RECOMMENDED ORDER)

### 1. Improve excel_parser.py (EASY)
Change from plain openpyxl to pandas + openpyxl:
- More readable
- More resilient to changes in Excel structure
- Preparation for Phase 2

### 2. Implement summarizer.py (CRITICAL)
Create two functions that use the Claude API:
```python
def claude_summarize_pdf(text: str) -> dict:
    # Input: text extracted from CUF/SUF PDF
    # Output: JSON with changes, RRs, dates

def claude_executive_summary(pdf_summary: dict, relevant_rrs: list) -> dict:
    # Input: PDF summary + relevant RR context
    # Output: JSON with executive summary + highlights
```

### 3. Implement real notifier (IMPORTANT)
Currently only logs the draft. Implement:
- Slack SDK to send real messages
- Email via SMTP (once IT provides credentials)

### 4. Improve sharepoint_client (WHEN READY)
Replace LocalSharePointClient with the real MS Graph API.

---

## 🔐 REQUIRED CONFIGURATION

Your teammate probably has a `config.py` similar to this:

```python
# config.py
import os
from pathlib import Path

SPP_BASE_URL = "https://spp.org"
DOCUMENT_SEARCH_PATH = "/Documents/Search"
RR_MASTER_QUERY = "RR Master List"
CUF_QUERY = "CUF Meeting Materials"
SUF_QUERY = "SUF Meeting Materials"
PROTOCOL_QUERY = "Integrated Marketplace Protocols"

LOW_TEXT_CHAR_THRESHOLD = 200  # Warn if PDF has very little text

RUNTIME_DIR = Path.home() / ".spp_rr_automation"
SHAREPOINT_FOLDERS = {
    "rr_master_list": "RR Master List",
    "cuf": "CUF Materials",
    "suf": "SUF Materials",
    "protocol": "Protocols",
    "recommendation_reports": "RR Reports",
}

def ensure_runtime_dirs(config):
    config.downloads_dir.mkdir(parents=True, exist_ok=True)
    config.extracted_dir.mkdir(parents=True, exist_ok=True)
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    config.logs_dir.mkdir(parents=True, exist_ok=True)
    config.state_file.parent.mkdir(parents=True, exist_ok=True)
```

**Required environment variables (.env):**
```
ANTHROPIC_API_KEY=sk-ant-... (for Claude)
SHAREPOINT_SITE=https://pcicompany.sharepoint.com/sites/energy
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/... (if using webhooks)
SMTP_SERVER=smtp.pci.local (once IT enables it)
SMTP_USER=agent@pci.local
SMTP_PASSWORD=... (store in keyring, not in .env)
```

---

## 📝 IMMEDIATE TASKS FOR CLAUDE IN VS CODE

When you open the project in VS Code with this context, Claude will be able to help you:

1. **Review and improve `excel_parser.py`** with pandas
2. **Implement `summarizer.py`** with the Anthropic SDK
3. **Create structured prompts** for Claude that generate valid JSON
4. **Improve `notifier.py`** to send real Slack messages
5. **Write unit tests** for each module
6. **Document the API** for each function
7. **Debug issues** in SPP.org scraping
8. **Optimize the cross-reference** logic

---

## 🚀 USEFUL COMMANDS TO RUN

```bash
# Initial setup
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt

# Run in dry-run (no downloading or storing)
python main.py run --dry-run

# Run for real
python main.py run

# View logs
type logs\run-YYYYMMDD-HHMMSS.log

# Review reports
type reports\relevant-rrs-YYYYMMDD-HHMMSS.json
```

---

## 📚 REFERENCES

- **Phase 1 flow diagram:** `fase1_architecture_drawio.xml` (import into draw.io)
- **Interactive HTML diagram:** `architecture_diagram.html`
- **Executive summary:** `resumen_fase1_para_presentacion.md`
- **Miquel's transcript:** Uses Flask + PyYAML + keyring (same stack as ours)
- **Current repository:** Teammate's code in the uploads

---

## ❓ FREQUENTLY ASKED QUESTIONS

**Q: Why is cross-reference important?**
A: There are ~1000 open RRs nationwide. Only ~10-50 are close to being implemented in a release. Without cross-reference, the summary would be useless.

**Q: Why not download EVERYTHING from SPP.org?**
A: That would be 100GB+ of data. Cross-reference filters down to only what's relevant.

**Q: Will Claude always understand the PDFs?**
A: Text extracted with pypdf sometimes has OCR errors or odd formatting. Claude is robust to that, but sometimes we'll need PyMuPDF or Claude's vision for complex PDFs.

**Q: What if SPP.org changes its HTML structure?**
A: The scraper will break. Solution: use Playwright to emulate a real browser (more robust but slower). It's already reserved in the code.

**Q: When does Phase 2 start?**
A: Once Phase 1 is in production and running cleanly every month.

---

## 🎯 FINAL GOAL

An **autonomous agent** that:
1. Runs without human intervention (Windows Task Scheduler)
2. Automatically downloads documents from SPP.org
3. Identifies what changes are coming and when (cross-reference)
4. Uses AI to generate a clear, actionable summary
5. Notifies stakeholders by email and Slack
6. Keeps a history in SharePoint for audit purposes

**Result:** The PCI team is **always informed** about regulatory changes without having to manually review SPP.org.

---

Any question about the context or the code — ask Claude in VS Code to explain it. It will have all this context available.
