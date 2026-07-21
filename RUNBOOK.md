# SPP AI Tool — Operations Runbook

_When each part of the pipeline runs, what change triggers what report, and how
the weekly job is scheduled. Flow agreed with Eduardo 2026-07-21._

> **Status legend**
> - ✅ **Implemented** — the code does this today.
> - 🎯 **Target** — agreed design, **not yet implemented** (and, where noted,
>   pending Elizabeth's sign-off). Do not assume the running tool behaves this way.

---

## 1. What the tool does

Unattended monitor of SPP regulatory filings for PCI's Market Systems team.
Three CLI commands off `main.py`:

- `python main.py run` — scrape spp.org (RR Master List, CUF/SUF meeting
  materials, Marketplace Protocols), cross-reference RRs, download each relevant
  RR's Recommendation Report. Also builds + publishes the HTML "Market Changes
  Summary" and posts to Slack.
- `python main.py report` — standalone HTML "Market Changes Summary" from the
  latest local CUF/SUF. (Same briefing `run` produces internally.)
- `python main.py settlement-report [--call-claude] [--all] [--stories]` — the
  settlements (BO) pipeline: RR docx → per-RR Jira story workbooks with redline
  screenshots. `--call-claude` = LLM story generation; `--stories` = also write
  the per-RR workbooks; `--all` = full re-run over the cache.

Two distinct deliverables, **different audiences and different sources**:

| Deliverable | Audience | Source | Command |
|---|---|---|---|
| **Market Changes Summary** (HTML briefing) | All PCI teams (FO, BO, ETRM…) | CUF/SUF **slides** | `run` / `report` |
| **Settlement Jira stories** (xlsx + workbooks) | BO / settlements devs | RR **Recommendation Reports** (docx) | `settlement-report` |

---

## 2. Fixed dependencies (not configurable)

- `run` **always precedes** `settlement-report`: it builds the relevant-RR list
  (in the shared state) and downloads the RR docx that settlement reads.
- The **ledger** (`check_analysis`/`record_analysis`, kind `settlement_report`,
  in `src/state/metadata_store.py`) makes each RR process **once per content
  version** — re-running costs no LLM unless an RR is new or its docx changed.
- The **market-initiative label** for an RR exists only on the CUF/SUF slide, not
  in the RR docx — so CUF/SUF is always the source that names the initiative.

---

## 3. Target weekly flow 🎯 (agreed 2026-07-21)

**When:** Windows Scheduled Task, **Monday ~10:00**, one chained job.

**Task mode:** **"Run only when user is logged on."** The job renders redline
screenshots via Microsoft Word automation (COM), which needs a real desktop
session. "Run whether user is logged on or not" (session 0, no desktop) makes
Word COM fail. Practical requirement: the laptop is on and the user is logged in
at the scheduled time (a **locked** screen is fine; **signed-off** is not).

```
MONDAY 10:00
  │
  ├─ 1. run: scrape spp.org (RR Master, CUF/SUF, Protocols)
  │        • refresh the WATCH LIST of RRs + their market initiatives (§5)
  │        • (re)download the Recommendation Report of each watched RR
  │
  ├─ 2. New CUF/SUF edition?  ──yes──▶ Market Changes Summary (HTML, all teams,
  │                                     lists relevant RRs) → Reports/SPPIM + Slack
  │                           ──no───▶ (briefing NOT regenerated)
  │
  ├─ 3. Any watched (open) RR whose Recommendation Report changed?
  │        ──yes──▶ settlement-report --call-claude --stories for those RRs
  │                 → report xlsx + per-RR workbooks with crops
  │                 → Story templates/SPPIM + Slack (drafts for PM review)
  │        ──no───▶ (settlement produces nothing)
  │
  └─ 4. Nothing changed at all?  ──▶ Heartbeat "nothing new" to Slack
```

If `run` fails, the job aborts before `settlement-report` (Slack failure alert
fires — already implemented on all three commands).

### Change → report mapping (the core of the design)

| Change in SPP | Triggers | Does NOT trigger |
|---|---|---|
| New **CUF/SUF** edition | Briefing HTML + refresh watch list / initiatives | — |
| **Recommendation Report** of a watched, open RR changed | That RR's settlement story (report + workbook) | The briefing |
| RR flips to **closed** in the master list | One final capture, then drop from watch list | — |
| **Nothing** | Heartbeat | Briefing and settlement |

---

## 4. The Market Changes Summary (briefing)

- 🎯 **Trigger:** regenerate **only when a new CUF/SUF edition is published.**
  Most weeks (no new CUF/SUF) it is not regenerated — this is the main
  cost/noise win of decoupling. RR-level updates travel via the settlement
  output, not the briefing.
- 🎯 **Content:** keeps listing the relevant RRs as context for all teams.
- ✅ The standalone `report` command stays as a manual escape hatch to force a
  briefing on demand, outside the schedule.
- **FO (future):** the briefing stays the high-level, all-teams digest; the FO
  spec-diff pipeline will produce its own deep per-team analysis, the same way
  settlement does.

---

## 5. Watch list model 🎯 — "Option B" (APPROVED by Eduardo 2026-07-21; inform Elizabeth)

**Problem with today's behavior (Option A):** settlement scope = "RRs mentioned
in the **latest** CUF/SUF ∩ open." An RR drops out of scope as soon as a newer
CUF/SUF stops mentioning it — so if SPP later re-publishes that RR's
Recommendation Report while it is still open, the change is **missed**.

**Option B (agreed direction):**
- The **watch list** = every open RR ever mentioned in CUF/SUF; its market
  initiative is **persisted** when first discovered.
- An RR is watched **while it is open** in the master list. CUF/SUF only
  *discovers* the RR and its initiative — it no longer *gates* ongoing tracking.
- Each run, every watched RR's Recommendation Report is (re)checked; a new/
  changed docx → an updated settlement story (ledger-gated, so no LLM cost
  unless it actually changed).
- **On close:** the run that first sees an RR flip to closed does **one final
  capture** of its Recommendation Report, then removes it from the watch list.
- **Seed:** initialize the watch list from the current relevant list (9 RRs) +
  everything already in the settlement ledger, so it doesn't start empty.
- **Classification:** the watch list holds all open mentioned RRs; the existing
  deterministic classification (inside `rr_structure.extract`, no LLM) decides
  which actually get a story. **Not every downloaded RR becomes a template:**

  | RR class | Output |
  |---|---|
  | `SETTLEMENT_CALC` (has # determinants/formulas) | Full settlement **story** (workbook) |
  | `SETTLEMENT_RELEVANT` (settlement impact via prose) | Single **review Task**, no full story |
  | `TARIFF_GOVERNANCE` (definitions/rates/prose only) | **Nothing** (Kashmita's scope rule) |

> ✅ **Approved by Eduardo 2026-07-21.** Option B revisits a decision previously
> locked with Elizabeth ("relevance = latest CUF/SUF editions only") — inform her
> as a courtesy, but implementation is green-lit.

### RR data model & outputs (clarified 2026-07-21)

- 🎯 **RR Control report** (persistent, from the watch list): one row per watched
  RR ever — RR#, title, class, open/closed, **market initiative**, story link,
  last updated. This is the "single control of all RRs" the team pictured. Today
  only the **per-run** `SPP_RR_Report_Summary.xlsx` exists (lists just the RRs
  processed that run — why only 3 RRs show even though 9 are downloaded).
- **Market initiative lives in BOTH places** (not either/or): the RR Control
  report (bird's-eye) AND each story's description (the actionable detail a dev
  reads without cross-referencing).
- **Snapshot of the 9 downloaded RRs (2026-07-21):** RR623, RR720, RR728, RR748,
  RR750 = `SETTLEMENT_CALC` (deserve a story); RR773 = `SETTLEMENT_RELEVANT`
  (review); RR665, RR684, RR786 = `TARIFF_GOVERNANCE` (no story). **Gap:** only
  RR623/728/748 have templates so far — **RR720 and RR750 are missing** (they
  were bootstrap-seeded into the ledger, not story-generated). RR720 is the CHILL
  RR with 0 determinants detected — its story may be thin; review separately.

---

## 6. Notifications

- ✅ Slack failure alerts on all three commands (a failed scheduled run is never
  silent).
- ✅ On a change, `run` posts the briefing link + relevant-RR list; `settlement-
  report` posts the report link + per-RR story-template links (PM review).
- 🎯 **Heartbeat:** on a run where nothing changed, post a short "nothing new
  this week" message so silence is never ambiguous (ran-and-clean vs failed).
  *(Not yet implemented — today `run` still posts the report whenever the
  relevant list is non-empty.)*
- 🎯 **Briefing Slack format = "by area" (Option B, chosen 2026-07-21, Miquel's
  richer-card idea):** the message groups **relevant changes per PCI area** with
  a count badge and item lines per area, plus a button to the full HTML. The 5
  areas come from `config/area_routing.yaml`: **Market Systems** (formerly "RTO
  Markets"), Asset Operations, Transmissions, ETRM, Optimization. **RRs are items
  under Market Systems only** (settlements + FO/BO live there) — they are NOT
  spread across areas; other areas list their own slide-level changes. Areas with
  no changes this edition are collapsed to a muted "no changes" line. Empty state
  degrades to the heartbeat.

---

## 7. Implementation status — current vs target

| Behavior | Today (✅ implemented) | Target (🎯) |
|---|---|---|
| Settlement scope | Latest CUF/SUF ∩ open (Option A) | Watch open RR by Recommendation-Report change (Option B) |
| Briefing trigger | Built when `any_change or relevant_rrs` (≈ every run) | Only on new CUF/SUF edition |
| Briefing / settlement | Coupled — one `run` does both | Decoupled by change type |
| No-change run | Posts report if relevant list non-empty | Heartbeat "nothing new" |
| Stories in automated run | Manual (`--stories`, crops approved) | Automatic `--call-claude --stories` |
| Schedule | None (manual 2-step) | Weekly Mon 10:00, chained job |

**Also uncommitted** (this laptop, as of 2026-07-21): Word COM render retries
(`pagination._com_call`, `render_pdf_with_word`) and the crop block-boundary fix
(`screenshots._starts_next_header`) — see `HANDOFF.md`. Suite: 102 passing.

---

## 8. Scheduling the task (when we set it up)

Windows Task Scheduler, **not yet created**:
- Trigger: weekly, Monday 10:00.
- Security option: **Run only when user is logged on** (see §3).
- Action: a wrapper that runs `python main.py run` and, on success, chains
  `python main.py settlement-report --call-claude --stories` (target flow), from
  the repo directory with the project's `.env` in scope.
- Validate once by hand before trusting it; watch the Word COM render.

Manual full run (until scheduled):
```
python main.py run
python main.py settlement-report --call-claude --stories
```

---

## 9. Pending approvals / open items

1. **Option B approved** by Eduardo 2026-07-21 (§5) — inform Elizabeth. Still
   worth showing her the RR728-27 crop change (it differs from her 20-jul
   approval); a corrected preview workbook exists locally
   (`RR728_Jira_Stories-PREVIEW-fixed.xlsx`, 39 images, single `[RR728-27]`).
2. **Implement** the target flow: watch list, decoupled triggers, heartbeat,
   the RR Control report (§5), and the by-area Slack briefing format (§6).
3. **Missing templates:** RR720 and RR750 are `SETTLEMENT_CALC` but have no story
   yet (§5). Not generating now (Eduardo, 2026-07-21) — will be picked up when
   Option B runs, or generate manually with
   `settlement-report --call-claude --stories --files …rr750…`.
4. **Schedule mode** confirmed as logged-on — needs the laptop on + logged in
   Monday 10:00.
5. Downstream backlog (`FEEDBACK_ACTIONS.md`): `pci_vocabulary.yaml`, SME
   questions (Miquel/Kashmita), and the FO spec-diff pipeline (P1).

---

## 10. Folder structure ✅ (migrated 2026-07-21, approved by Elizabeth)

Market at the top, self-contained per market. Executed layout:
```
${SPP_SYNC_ROOT}/          <- the ONLY per-machine variable (each person's .env)
  SPPIM/                   <- `market` (config.yaml, default SPPIM)
    Published Documents/   CUF/ SUF/ Protocols/ RR_Master_List/ Recommendation_Reports/
    Reports/
      Briefings/           SPP_Market_Changes_Summary-*.html   (+ Archive/)
      Summaries/ BO/       (RR_Control.xlsx once Option B lands; + Archive/)   FO/ (future)
    Stories/   BO/         RR<id>_Jira_Stories-*.xlsx  (+ Archive/)            FO/ (future)
    State/     metadata.json
  CAISO/ …                 (new market = new top-level folder, same subtree)
```

**Config — single ROOT variable:** every synced path is derived in `config.py`
from `SPP_SYNC_ROOT` (`.env`) + `market` (`config.yaml`, default `SPPIM`); a
teammate edits only `SPP_SYNC_ROOT`. `config.yaml` keeps just the local repo
working dirs. A new market = change `market` (or set `SPP_MARKET` in `.env`).

**Decisions (2026-07-21):**
- Market at the top; each market self-contained.
- **BO / FO split** under `Stories/` and `Reports/Summaries/` — settlements = BO.
- Source-docs folder named `Published Documents` (the parent already names the market).
- Versioning = stable name + `Archive/` (a correction overwrites in place; the
  prior version moves to a sibling `Archive/`). NOTE: the tool still writes
  timestamped filenames today — the stable-name + auto-archive behavior lands with
  the Option B / RR-Control work.

**Migration executed 2026-07-21** (all moves, reversible): inputs → `Published
Documents/`; briefings → `Reports/Briefings/` (newest kept, 5 older → `Archive/`);
per-run summaries → `Reports/Summaries/BO/Archive/`; story workbooks → `Stories/BO/`
(wrong-crop RR728 → `Stories/BO/Archive/`); `State/metadata.json` → `SPPIM/State/`.
Old top-level `Reports/`, `Story templates/`, `State/` removed. Verified: the tool
finds every input + the state, 104 tests pass, dry-run clean.
**Self-healing follow-up:** the shared ledger still records the pre-move local
paths, so the next real run re-downloads the source files once and re-records them
(hash-guarded — nothing reprocesses). Left as-is rather than hand-editing the ledger.
