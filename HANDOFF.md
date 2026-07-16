# SPP AI Tool — Session Handoff

_Snapshot for picking this project up in a fresh chat. Written 2026-07-15, after
the SME-feedback rework and the RR728 benchmark pass._

## What this project is

An unattended agent for PCI's Market Systems team that monitors SPP regulatory
filings so nobody checks spp.org by hand. Three CLI commands off `main.py`:

- **`python main.py run`** — scrapes spp.org (RR Master List, CUF/SUF meeting
  materials, Marketplace Protocol), cross-references RRs mentioned in the
  **latest** CUF/SUF editions against open RRs, downloads each relevant RR's
  Recommendation Report. Ledger-tracked: unchanged docs are skipped, re-published
  docs are re-downloaded as dated `.rev-YYYYMMDD` files (originals never touched)
  and flagged **UPDATED** in warnings/Slack.
- **`python main.py report`** — LLM HTML "Market Changes Summary" for all PCI
  teams → synced `Reports/SPPIM/` folder + Slack.
- **`python main.py settlement-report [--call-claude] [--all] [--stories]`** —
  the settlements pipeline. Default = incremental: only RRs in the current
  relevant list not yet in the ledger. `--call-claude` = LLM story generation
  (stories persist as JSON under `data/reports/settlement/stories/`).
  `--stories` = also fill Miquel's Jira workbook template (PAUSED by default
  pending story-quality signoff). `--all` = full re-run over the cache.

## The benchmark (the project's bar for "valuable")

Reproduce **Kashmita's Jira story SP-12814** (RR728, RUC MWP Distribution) from
the raw RR docx. **Status: PASSED on substance (2026-07-15)** — see
`data/reports/settlement/stories/RR728-SPP_RR_Report_Summary-20260715-181926.json`:
go-live parameter block, 25 numbered per-determinant formula changes (SUG
§2.7.10 only, Tariff = one context sentence), real page citations, initiative
verbatim + slide citation, protocol link. Covers all 12 of Kashmita's items plus
the rate/DC-Tie restructure. Remaining gap = PCI vocabulary (see below).

## What was fixed to pass it (this session)

1. **False HARD_FAIL**: RR728's Impacted block cites Market Protocols §4.5.9.10
   but the body uses Settlement User Guide numbering §2.7.10 (same doc family,
   different numbering) → now `PASS_NUMBERING_MAPPED` with a note. RR720's
   dot-mangled sections ("4.3.11" = body "4.3.1.1") → digit-sequence matching.
   Both in `src/settlement/rr_structure.py`.
2. **Equations**: RR728's formulas are legacy MathType OLE → WMF images that are
   just **Σ operators** (operands are text). Now emitted as `[[EQ-IMG: imageN.wmf]]`
   markers + PNGs extracted to `data/reports/settlement/images/rr<N>/`.
3. **Page numbers**: RR728's docx has ZERO saved page breaks (all sections said
   p.1). `src/settlement/pagination.py` renders docx→PDF via **headless Word COM**
   (pywin32; PDFs cached in `data/reports/settlement/rendered/`) and takes true
   pages from the PDF. Page-anchored citations are passed into the LLM prompt.
4. **Prompt** (`src/settlement/rr_extraction_prompt.md`): SUG/MP-only scope,
   numbered item per added/replaced/deleted formula with `[p.X]`, go-live
   parameter block first, `SUM_i(...)` reconstruction of Σ-image equations.

## Elizabeth's locked decisions (do not re-litigate)

- Story scope: **Market Protocols / Settlement User Guide sections only** —
  Tariff & other impacted docs are one background sentence, never story items.
- Initiative labels **verbatim from the slide** + file/page citation everywhere
  (e.g. RR728 → "2026 Settlements Fall Bundle" [(07) Settlement Releases – CUF
  July 2026.pdf p.6]). Never invent labels like "SPPIM Settlements".
- **One combined report** (`SPP_RR_Report_Summary-*.xlsx`); per-RR story
  workbooks paused behind `--stories` until quality signoff.
- Jira template rows: **no epic row** (PM fills Epic column), `Create?` blank
  (PM opts in), green sync columns never written. Template:
  `templates/Jira_Story_Creator_template.xlsx` (Miquel's v1.1.0; his app syncs
  it to Jira). Outputs go to synced `Story templates/SPPIM/`.
- RR folder is **append-only**: originals never overwritten; revisions as
  `.rev-YYYYMMDD` files; pipeline analyzes the newest revision.
- Go-live parameter block added to **every** RR story.
- Relevance = latest CUF/SUF editions only; already-processed RRs skipped via
  the ledger (`check_analysis`/`record_analysis` in
  `src/state/metadata_store.py`, kind "settlement_report").
- State lives in the synced folder (`${SPP_SYNC_ROOT}/State/metadata.json`) —
  Elizabeth isn't fully happy with the location but keep it for now.
- Reproducibility = versioned prompt + deterministic extraction +
  `config/pci_vocabulary.yaml` (NOT a separate skill; a skill may later wrap the
  same pipeline).

## Immediate next steps

1. **"URLs verbatim" prompt rule** — last run the LLM decorated the Protocols
   folder URL into a fake share-link. Add the rule, rerun RR728 to confirm.
2. **`config/pci_vocabulary.yaml`** — skeleton exists, all commented out.
   Elizabeth + Kashmita fill it ("add calculation class", "shadow calculation",
   "copy value from statement", 3-decimal rounding). Injected automatically.
3. Optional: per-determinant page lookup (today pages resolve per section — all
   RR728 items cite p.15).
4. RR720 (CHILL) story JSON was never persisted (predates persistence) — rerun
   with `--call-claude --files ...rr720...` when wanted.
5. Questions parked with **Miquel**: workbook lifecycle (append vs new file),
   attachments/images through his sync app, previous RTO Markets API zip for
   the FO spec-diff archive. **Kashmita**: area-routing YAML review
   (`config/area_routing.yaml`, provisional) + determinant-source artifact.
6. Bigger roadmap: `FEEDBACK_ACTIONS.md` (P1 spec-diff pipeline for FO next).

## Machine facts (this laptop, user `eoyarce`)

- `.env` at repo root (gitignored) has `SPP_SYNC_ROOT` and `CLAUDE_CODE_BINARY`.
  **Slack keys are blank here** — alerts/notifications only fire from the
  machine that has them (coworker's scheduled tasks).
- Synced library: `C:/Users/eoyarce/PCI Energy Solutions/Market Systems - ISO
  Agent Market Updates` (NOT the "OneDrive -" prefixed path). Reports →
  `Reports/SPPIM/`, story workbooks → `Story templates/SPPIM/`.
- **No venv** — system Python 3.14 has all deps. Pillow is in requirements.txt;
  **pywin32 is installed but NOT in requirements.txt** (COM is Windows-only) —
  install manually on new machines for the pagination fallback.
- Claude CLI at `C:/Users/eoyarce/.local/bin/claude.exe`, logged in; headless
  calls cost real money (~6 min per RR story).
- Microsoft Word installed — required for the pagination fallback (COM).
- Tests: `python -m pytest -q` → 68 passing.

## Working agreement with Elizabeth

Preview-first: show her report/story previews and get explicit approval before
changing code behavior. Ask clarification questions liberally — she prefers
being asked over assumptions. Never restructure the team's synced folders.
