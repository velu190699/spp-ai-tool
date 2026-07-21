# SPP AI Tool — Session Handoff

_Snapshot for picking this project up in a fresh chat. Written 2026-07-20,
reconciling the 2026-07-17 screenshot/links rework (tested, see below)._

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
  `--stories` = also fill Miquel's Jira workbook template, **including a redline
  screenshot sheet per RR** (still opt-in / paused-by-default pending
  story-quality signoff). `--all` = full re-run over the cache.

## The benchmark (the project's bar for "valuable")

Reproduce **Kashmita's Jira story SP-12814** (RR728, RUC MWP Distribution) from
the raw RR docx. **Status: PASSED on substance (2026-07-15)** — go-live
parameter block, 25 numbered per-determinant formula changes (SUG §2.7.10 only,
Tariff = one context sentence), real page citations, initiative verbatim + slide
citation, protocol link. Covers all 12 of Kashmita's items plus the rate/DC-Tie
restructure. Remaining gap = PCI vocabulary (see next steps).

## State of the tree (2026-07-20)

**A full 2026-07-17 rework is complete and tested (77 pytest passing) but NOT yet
committed.** It implements Eduardo's 2026-07-17 feedback:

1. **Per-item redline screenshots** (`src/settlement/screenshots.py`, new).
   Crops the COMPLETE tracked-changes formula for each numbered item from a
   MARKUP-view PDF (Word COM `Item=7` export), bounded by the next determinant
   definition / the variable glossary / a blank gap / a 2-page cap. A formula
   that crosses a page break becomes two images. Each crop is keyed by a stable
   code `RR<id>-NN` (also in the caption). Image-only (picture) formulas are
   skipped and logged. Emitted to a workbook sheet named EXACTLY the row's Local
   ID — Miquel's sync app attaches those images to the Jira issue.
2. **`items` mirror** (prompt v2026-07-17.2). Each story now carries an `items`
   array: one entry per numbered description item, with a concise formula-free
   `action` + `determinant`. The REPORT tab keeps the full formula; the JIRA
   WORKBOOK row shows `<action> [RR<id>-NN] [p.X]` so the screenshot code stands
   in for the formula and Miquel's app inserts the matching image.
3. **Deterministic per-item pages** (`pipeline.correct_item_pages`,
   `pagination.determinant_pages`, `settlement_report.rewrite_item_pages`).
   Rewrites each item's LLM-guessed `[p.X]` to the page where that determinant's
   formula actually appears in the MARKUP PDF (same view as the screenshots, so
   citations and crops agree). No LLM cost, no wording change. This closes the
   old "per-determinant page lookup" next step.
4. **SharePoint links** (`pipeline.annotate_links`). Resolves the RR docx link
   (appended to the description AND the report's SharePoint column) and the
   CUF/SUF file named in the initiative citation (made clickable in the report's
   Market Initiative cell).
5. **Slack on every settlement report** (`main.py`) — not just the HTML briefing.
6. **FIDELITY-NOT-JUDGMENT** prompt hard rule — no editorial notes in stories
   ("confirm with SME", "possible error"); transcribe the RR exactly.
   Implementation risk is the developer's call. See `[[spp-tool-language-and-fidelity]]`.

Deps added: `pypdfium2==5.12.1` (in requirements.txt; used for the crops).
`pypdf` and `pypdfium2` are installed on this laptop.

**2026-07-20 crop + Slack refinements (also uncommitted, tested — 93 pytest):**
- Rewrote `screenshots.py` block detection. A determinant's crop = its whole
  formula: stops at `Where` / a different def / prose; includes IF/THEN/ELSE;
  prepends the `IF … THEN` header above the `<det> =` line (`_formula_header`,
  handles labeled `(b.2.1) IF`, multi-line + page-crossing conditions, and
  IF-with-no-THEN); jumps a footnote between page-halves; drops the `(a.1) …`
  prose. `_text_defines` makes the text fallback match a real definition (not a
  usage/glossary row). Two-part crops use `a`/`b` codes in the caption AND the
  description (`[RR728-02a] [RR728-02b]`). **Crops reviewed + APPROVED by
  Elizabeth 2026-07-20**; validated across RR728/RR623/RR748 (0 missing-IF, 0
  over-extension). RR728 items 22/23/26 are image-only / defined-elsewhere → no
  crop (expected).
- Enriched the story-drafts Slack message (`notifier.send_slack_story_drafts`):
  report link on top, then a per-RR link to each RR's story-template workbook.
  Note: on a `--stories` run the plain report-link message (always) AND this
  drafts message both fire — offered to unify to one; left as two for now.

**Not yet verified end-to-end on a real RR** — the screenshot crop heuristics are
new and geometry-based; a visual check on RR728 (`--call-claude --stories`) is the
natural next step before trusting the crops. Tunable constants live at the top of
`screenshots.py` (gap/glossary/footer/margin/page-cap).

## Elizabeth's + Eduardo's locked decisions (do not re-litigate)

- Story scope: **Market Protocols / Settlement User Guide sections only** —
  Tariff & other impacted docs are one background sentence, never story items.
- Initiative labels **verbatim from the slide** + file/page citation everywhere
  (e.g. RR728 → "2026 Settlements Fall Bundle" [(07) Settlement Releases – CUF
  July 2026.pdf p.6]). Never invent labels like "SPPIM Settlements".
- **One Jira story per RR** (prompt hard rule; pipeline warns if violated).
- **One combined report** (`SPP_RR_Report_Summary-*.xlsx`); per-RR story
  workbooks stay behind `--stories` until quality signoff.
- Jira template rows: **no epic row** (PM fills Epic column), `Create?` blank
  (PM opts in), green sync columns never written; Tests tab ships blank below its
  header. Template: `templates/Jira_Story_Creator_template.xlsx` (Miquel's
  v1.1.0). Miquel's story-creation guide is `templates/Story Creation
  Process_*.pdf` (the contract behind the per-Local-ID screenshot sheet).
- **Both Excel outputs (report + story workbooks) publish to synced
  `Story templates/SPPIM/`** (`Reports/SPPIM` is HTML-only). Working artifacts
  (stories JSON, images, screenshots, rendered PDFs) stay local in
  `data/reports/settlement/`.
- Report = full formulas; workbook row = action + screenshot code + page.
  ("Workbook code, report keeps formula" — Eduardo, 2026-07-17.)
- Per-item pages + screenshots both come from the **MARKUP** PDF view; never mix
  markup-view and content-view page numbers.
- RR folder is **append-only**: originals never overwritten; revisions as
  `.rev-YYYYMMDD` files; pipeline analyzes the newest revision.
- Go-live parameter block added to **every** RR story.
- Relevance = latest CUF/SUF editions only; already-processed RRs skipped via the
  ledger (`check_analysis`/`record_analysis` in `src/state/metadata_store.py`,
  kind "settlement_report").
- State lives in the synced folder (`${SPP_SYNC_ROOT}/State/metadata.json`) —
  Elizabeth isn't fully happy with the location but keep it for now.
- Reproducibility = versioned prompt (`PROMPT_VERSION:` line 1, stamped into every
  stories JSON) + deterministic extraction + `config/pci_vocabulary.yaml`. Repo
  skill `.claude/skills/settlement-report/SKILL.md` wraps the pipeline.
- Slack: Bot User OAuth Token (xoxb-) as `SLACK_BOT_TOKEN` + `SLACK_CHANNEL`.

## Immediate next steps

1. ~~Commit the rework~~ **DONE** — committed 2026-07-20 (`044ea8f` code + tests +
   Miquel's guide PDF; `72e1e7f` skill/handoff docs) and pushed to origin/master.
   93 pytest passing.
2. ~~Visually verify the screenshots~~ **DONE** — crops reviewed and approved by
   Elizabeth 2026-07-20 across RR728/RR623/RR748. Block-detection tunables are at
   the top of `screenshots.py` if a future RR needs adjustment.
3. **NEXT: manual end-to-end validation run**, then schedule WEEKLY. Elizabeth
   wants the pipeline scheduled to run once a week; before scheduling, do one full
   manual run to confirm the unattended flow works on this laptop:
       python main.py run                                       # fetch new RRs from spp.org
       python main.py settlement-report --call-claude --stories # report + per-RR workbooks
   Watch the **Word COM markup render** — a headless Windows Scheduled Task
   ("run whether user is logged on or not") may not give Word a usable session;
   validate that before trusting the schedule. Cost is bounded: the ledger only
   LLM-processes RRs not already recorded. (This step was moved out of the old
   #3 numbering below.)
3. **`config/pci_vocabulary.yaml`** — skeleton exists, all commented out.
   Elizabeth + Kashmita fill it ("add calculation class", "shadow calculation",
   "copy value from statement", 3-decimal rounding). Injected automatically when
   it has content.
4. RR720 (CHILL) story JSON was never persisted (predates persistence) — rerun
   with `--call-claude --files ...rr720...` when wanted.
5. Questions parked with **Miquel**: workbook lifecycle (append vs new file),
   image handling through his sync app (does the Local-ID sheet contract work as
   built?). **Kashmita**: area-routing YAML review (`config/area_routing.yaml`,
   provisional) + determinant-source artifact.
6. Bigger roadmap: `FEEDBACK_ACTIONS.md` (P1 spec-diff pipeline for FO next).

## Machine facts (this laptop, user `eoyarce`)

- `.env` at repo root (gitignored) has `SPP_SYNC_ROOT` and `CLAUDE_CODE_BINARY`.
  **Slack IS configured on this laptop now** (`SLACK_BOT_TOKEN` xoxb + `SLACK_CHANNEL`
  = `s-markets-monitoring-reports`, a real team channel) — notifications posted
  from here go to the team. `SLACK_WEBHOOK_URL` is empty (bot token path is used).
- Synced library: `C:/Users/eoyarce/PCI Energy Solutions/Market Systems - ISO
  Agent Market Updates` (NOT the "OneDrive -" prefixed path). HTML reports →
  `Reports/SPPIM/`; report xlsx + story workbooks → `Story templates/SPPIM/`.
- **No venv** — system Python 3.14 has all deps. `pywin32` is installed but NOT
  in requirements.txt (COM is Windows-only) — install manually on new machines
  for the pagination / markup-render fallback.
- Claude CLI at `C:/Users/eoyarce/.local/bin/claude.exe`, logged in; headless
  calls cost real money (~6 min per RR story).
- Microsoft Word installed — required for the pagination + markup-view renders (COM).
- Tests: `python -m pytest -q` → **77 passing**.

## Working agreement with Elizabeth

Preview-first: show her report/story previews and get explicit approval before
changing code behavior. Ask clarification questions liberally — she prefers being
asked over assumptions. Never restructure the team's synced folders.
