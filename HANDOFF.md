# SPP AI Tool — Session Handoff

_Snapshot for picking this project up in a fresh chat. Updated 2026-07-22._

## Latest session — 2026-07-22 (read this first)

**Everything committed; 136 tests passing.** Branch is ahead of origin by ~14
commits — **not pushed yet** (push when ready). This session finished Option B
items #4 and #5 and left **#6 as the next task, to be started in a fresh chat.**

- ✅ **#4 Initiative accumulation** across CUF/SUF editions (parse each edition
  once, backfill older synced editions, per-RR `mentions_seen` history,
  current-initiative = newest edition that names one).
- ✅ **#5 RR Control dashboard** (`src/summaries/rr_control.py`, `main.py
  rr-control`): dated + accumulating HTML → synced `Reports/Control/`. Two tabs —
  **Control** (watch-list register: RR#→docx link, class + MP-scope chip, status,
  initiative, story link, updated; rows expand to CUF/SUF mention history) and
  **Determinants** (collapsible per-RR tables of charge-code changes with
  formula-before / formula-after / page, reused from the story JSON; only
  in-scope SETTLEMENT_CALC RRs). Title "<market> Settlement Changes Control".
- ✅ **SME initiative overrides** (`config/initiative_overrides.yaml`,
  `apply_initiative_overrides`): RR750 pinned to "RTO Expansion Project"
  (Eduardo's call — verbatim from the SUF slide; the extractor couldn't infer it).
- ✅ **Coverage caveat** documented (May 2026 CUF sat in a personal OneDrive,
  unparsed — editions must be in the synced team folder).

### Decisions locked this session
- **RR750 initiative = "RTO Expansion Project"** (done, via the override file).
- **xlsx summary:** recommendation is to **retire the combined
  `SPP_RR_Report_Summary.xlsx` (overview) once Miquel confirms nothing downstream
  reads it** — the dashboard supersedes it — but **keep the per-RR Jira story
  workbooks** (redline screenshots → Jira). Not done yet; phased, pending Miquel.

### 🎯 NEXT: Option B #6 — heartbeat + per-report Slack messages (fresh chat)
Eduardo wants **good Slack messages for each report type** (not just a link):
- **Heartbeat:** on a no-change `run`, post a short "nothing new this week" so
  silence is never ambiguous (today `run` posts the briefing whenever the
  relevant list is non-empty — see RUNBOOK §6/§7).
- **Briefing Slack = "by area":** group relevant changes per PCI area (5 areas in
  `config/area_routing.yaml`; RRs live under Market Systems only), count badge +
  item lines, button to the full HTML. Empty state degrades to the heartbeat.
- **Distinct, well-crafted messages per report type:** the all-teams briefing
  (`run`), the settlement report + story drafts (`settlement-report`), the RR
  Control dashboard (`rr-control`, currently posts no Slack), and failures. See
  `src/notifications/notifier.py` (`send_slack_report_link`, `send_slack_story_drafts`,
  `send_slack_failure`, `log_slack_draft`). Slack is configured on this laptop
  (posts to the real `s-markets-monitoring-reports` channel — mind live posts).

---

## Earlier session — 2026-07-21

Large session; **everything committed, working tree clean, 110 tests passing.**
`RUNBOOK.md` is the canonical design doc. Highlights:

- **Crop fixes shipped** (`5c77ecc`, `75c92f8`): RR728-27 no longer swallows the
  next sub-determinant's IF/THEN; RR750 `#RtAdjMtr5minQty` no longer truncates at
  a redline inside open brackets (bracket-depth gate). Word COM render hardened
  with transient-error retries. RR728 + RR750 workbooks regenerated + republished
  corrected in `Stories/BO/`.
- **Synced library RESTRUCTURED + migrated** (`60e113b`): market-at-top,
  self-contained. New layout `${SPP_SYNC_ROOT}/SPPIM/{Published Documents,
  Reports/{Briefings,Summaries/{BO,FO}}, Stories/{BO,FO}, State}`. Every synced
  path is DERIVED in `config.py` from `SPP_SYNC_ROOT` (.env) + `market`
  (config.yaml, default SPPIM) — a teammate edits ONLY `SPP_SYNC_ROOT`. Files
  moved (reversible); old top-level `Reports/`, `Story templates/`, `State/`
  removed. **Follow-up:** the ledger still records pre-move local paths, so the
  next real run re-downloads the source files ONCE and re-records them
  (hash-guarded — nothing reprocesses).
- **Option B APPROVED (Elizabeth) + CORE IMPLEMENTED** (`3496b85`, `4cfe134`,
  `921fdcd`): watch list in state; `run` seeds it, fetches every watched-OPEN
  RR's Recommendation Report, and rebuilds the briefing ONLY on a new CUF/SUF
  edition; settlement scopes to the watch list (reprocess on Recommendation-Report
  change; final-capture-then-prune on close); initiatives come from the watch
  list. **The Option A gap is closed.** Watch list seeded with the 9 RRs.

### Next steps (start the fresh chat here)
1. **Option B remaining** (design locked in RUNBOOK §5):
   - ✅ **(4) initiative accumulation** across CUF/SUF editions — DONE 2026-07-22.
     Parse each edition once (`parsed_editions`), one-time backfill (free — nothing
     marked parsed on first run), WATCHED RRs only, per-RR `mentions_seen` history,
     `market_initiative` = newest edition that names one. Verified on real data:
     recovered RR623 + RR728. **RR750 stayed blank — the premise was wrong: it has
     no seasonal initiative in ANY synced edition (one mention, SUF April, "RTO
     Expansion Project"), not one hidden in an older edition.** Open Q for
     Elizabeth/Kashmita: should "RTO Expansion Project" count? See RUNBOOK §5.
   - ✅ **(5) RR Control dashboard** — DONE 2026-07-22. `src/summaries/rr_control.py`
     + `main.py rr-control` (standalone, accumulates then builds, offline) + a hook
     in `run`. Dated + accumulating HTML → synced `Reports/Control/`. One row per
     watched RR (class/status/initiative/story/updated), expandable mention timeline.
     Title "<market> Settlement Changes Control"; classes = Settlement calc /
     Settlement review / Tariff-governance; candidate-initiative hint when none named.
     Published a real dated snapshot to the synced folder + reviewed visually.
   - **(6) heartbeat** + **Slack by-area** briefing (RRs under Market Systems). NOT built.
   - ⚠️ **Coverage caveat (found 2026-07-22):** the tool parses ONLY the CUF/SUF
     editions in the synced team folder (`Published Documents/{CUF,SUF}`). A
     SharePoint cross-check found a **May 2026 CUF** in a *personal* OneDrive
     (`SPP Agent Project/Documentation/`), never parsed. It only named RR728
     (already covered), so no impact — but the team must ensure every edition
     lands in the synced folder, not personal drives. See RUNBOOK §5 coverage caveat.
2. A real end-to-end run to exercise the full flow (first run re-downloads sources once).
3. Confirm with Miquel his sync app reads workbooks from `Stories/BO/`.
4. Schedule the weekly task (Mon 10:00, "run only when user is logged on").

_Everything below predates 2026-07-21 and is kept for background; RUNBOOK.md supersedes it where they differ._

## What this project is

> **Operational flow (when each piece runs, change→report mapping, folder layout,
> schedule) is documented in `RUNBOOK.md`.** Option B is approved and its CORE is
> implemented (watch list, decoupled triggers, watch-list settlement scoping);
> accumulation, the RR Control dashboard, and heartbeat/Slack-by-area remain (see
> the session note above and RUNBOOK §5).

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
3. **Word COM markup render: VALIDATED locally 2026-07-20** across RR623/RR728/RR748
   (interactive session). Three fixes landed this session (all UNCOMMITTED),
   suite now **102 passing**:
   - **Transient COM retry** on `render_pdf_with_word`: cold-start `Call was
     rejected by callee` (RPC_E_CALL_REJECTED) is retried 3× with backoff via a
     fresh instance (`_is_transient_com_error` + `_render_pdf_once`).
   - **Per-call COM retry** (`_com_call`): the post-Open calls (ActiveWindow.View,
     Export) are rejected while Word lays out a LARGER doc — RR748 failed 100% at
     the markup-view step until this. Restarting the whole render did NOT help
     (fresh instance busy at the same point); a short in-place wait does. This is
     what rescued RR748 (was silently producing 0 crops).
   - **Crop block-boundary fix** (`screenshots._starts_next_header`): a
     determinant's one-line formula no longer absorbs the NEXT sub-determinant's
     "(b.2.1) IF … THEN" header. Fixes Elizabeth's flag that RR728-27b was a lone
     "THEN"; item 27 is now a single complete crop, item 28 unchanged. RR623/RR748
     crops byte-identical (fix is a no-op there). Tests in `test_screenshots.py`.
   Crops re-validated: RR623=14, RR728=39 (was 40; the bogus 27b gone), RR748=2.
   **RE-APPROVAL:** only RR728-27 changed vs Elizabeth's 2026-07-20 approval (it's
   strictly better — one complete crop instead of a split ending in a lone THEN);
   worth a quick confirm with her.
   **STILL OPEN before scheduling WEEKLY:**
   - Decide the Scheduled Task mode. The TRUE headless case ("run whether user is
     logged on or not" = session 0, no desktop) is UNVALIDATED and Word COM usually
     fails hard there. Recommended: **"run only when user is logged on"** (real
     desktop session; retry fix covers cold-start flakiness). Eduardo: DECIDE LATER.
   - The full manual end-to-end (`run` + `settlement-report --call-claude --stories`)
     was NOT run this session — in steady state all 9 relevant RRs are already in the
     ledger, so a real settlement run does nothing unless forced with `--files`/`--all`.
     Note SPP RENAMED CUF doc 77179 → "CUF July 2026 Meeting Materials 20260716.zip";
     a real `run` will re-cross (same 9 RRs) and re-emit the LLM HTML report.
       python main.py run                                       # fetch new RRs from spp.org
       python main.py settlement-report --call-claude --stories # report + per-RR workbooks
   Cost is bounded: the ledger only LLM-processes RRs not already recorded.
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
