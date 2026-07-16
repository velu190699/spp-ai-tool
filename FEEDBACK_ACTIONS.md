# Feedback Action Plan — SPP AI Market Monitoring Tool

_Derived from the review meeting on 2026-07-13 (Kashmita Ghimire — settlements/back
office; Miquel Fernandez Barros & Sahij — front office / market systems; Elizabeth
Oyarce & Lucia Carrion — builders). This is the prioritized backlog, not a code
change. Sequence and assign after review._

---

## The core insight from the meeting

Nobody said the tool is broken. They said it stops **one level too shallow**.

> "Just knowing that a change is coming is kind of like halfway through the actual
> goal." — Miquel

Today the tool reads the CUF/SUF **slides** and reports at slide level. Both SMEs
want it to (1) go one step deeper — fetch the actual spec/protocol document behind
the slide and describe the *concrete* change — and (2) produce something a PM can
act on (a reviewable story), not just a flag. Every item below serves one of those
two goals or removes noise that gets in their way.

Everyone agreed the direction is right and this is still experimental
("we are still experimenting" — Kashmita). The gold standard now exists: Miquel's
manual analysis + the Jira story he built. The tool's job is to reproduce that.

---

## P0 — Quick accuracy fixes (do first; low risk, rebuilds SME trust)

_Status 2026-07-14: P0-1 **done** (provisional YAML at `config/area_routing.yaml`,
pending Kashmita's corrections), P0-3 **done** (deterministic initiative
extraction from CUF/SUF mention contexts feeds the Market Initiative column and
the LLM story prompt). P0-2 **root-caused**: the June CUF was fully ingested;
the "stale" impression came from the tool not having run since SPP posted the
July 16 materials — fixed operationally by failure alerts + heartbeat and a
fresh run. Also done: shared processing ledger in the synced folder (with
UPDATE detection for re-published RR packages), Slack failure alerts on all
three commands._

### P0-1 · Fix the PCI area / division routing
- **What:** The five-card "executive overview" miscategorizes changes. Kashmita's
  example: WEIS/SPP-West winding down + final settlement showed under **ETRM**
  when it's really **market settlements**.
- **Why it happens:** The routing hints are hard-coded in
  `src/summaries/report_builder.py` (~lines 33-38). ETRM's hint literally lists
  "SPP West" and "bilateral settlements" — exactly the items that got misrouted.
- **Do:** Replace the hints with SME-validated topic lists per area. Add an
  explicit rule for the "bilateral" ambiguity Miquel raised — bilaterals appear in
  ETRM (deal calcs) *and* SPP settlements, so a bilateral change may need flagging
  in **both** areas, not routed to one.
- **Depends on:** Kashmita's corrected area→topic mapping (she offered to review
  offline once she has the link).
- **Effort:** S (prompt edit once mapping is in hand).

### P0-2 · Confirm the CUF version being ingested
- **What:** Miquel's front-office analysis (API services, V22→V17 web-services
  retirement) came from a CUF the report isn't fully reflecting; he asked "is this
  from the previous month?"
- **Do:** Verify `cuf_dir` holds the *latest* CUF and that the summarizer isn't
  silently skipping it. Cross-check `meta.files_read` / `files_skipped` in the
  report output against what's actually in the synced folder. Miquel confirmed the
  latest CUF *does* contain the API services.
- **Root cause to rule out:** stale/wrong file in the synced SharePoint mirror vs.
  the prompt dropping a file.
- **Effort:** S–M (investigation).

### P0-3 · Restore the RR → market-initiative link (known regression)
- **What:** The RR settlement report lists many "open" RRs, but not all tie to a
  market initiative — Kashmita called the RR master list "so much noise."
- **Why:** Elizabeth confirmed a prior template linked each RR to its CUF/SUF
  market initiative, but the current prompt didn't reproduce that column.
- **Do:** Explicitly re-add the market-initiative column in
  `src/settlement/rr_extraction_prompt.md`, linking each open RR to the initiative
  named in the CUF/SUF slides.
- **Note:** The existing filter (RR must be open in master list **AND** explicitly
  mentioned in CUF/SUF) is correct — Miquel agreed. This just adds the link back.
- **Effort:** S (prompt edit).

---

## P1 — Depth: fetch the real specs, not the slides (highest value)

_Unblocked — Elizabeth has Miquel's forwarded analysis, his Jira story, and the
tech-specs URL._

### P1-1 · Fetch the actual API / tech-spec documents behind a flagged change
- **What:** When a slide flags a web-service/API change, the tool should go fetch
  the real spec files from SPP's future-tech-specs page (URL from Miquel), not
  report from the slide alone.
- **Confirmed source (2026-07-14):** the **Future Tech Specs** page,
  `https://spp.org/spp-documents-filings/?id=21071` (breadcrumb: CUF Reference
  Documents → Technical Specifications → Tech Specs → Future Tech Specs). The
  existing `SppClient` document-search plumbing covers this page; it's a new
  target, not new infrastructure. Observed contents (2026-07-14 screenshot):
  - `RTO_Markets_API_Specifications_20260708.zip` (4.41 MB) — what Miquel used
  - `Markets_Plus_Settlement_API_Specifications_20260630.zip`,
    `Markets_Plus_CRT_…`, `Markets_Plus_CLR_v2_…`, `Markets_Plus_Markets_…`
  - `SPP_CROW_API_Specifications_…` (two versions posted a week apart)
  - `Draft_RTO_Markets_API_Specifications_20260522.zip` — **draft**, and its
    filename date (05/22) differs from its posted date (June 30): the "slide
    dates lie" problem applies to filenames too.
  Implementation: track each **spec family** separately (filename stem before the
  date suffix), keep draft vs. final apart, key the archive by *posted* date +
  filename date, and **archive every downloaded zip** so there is always a
  previous same-family version to diff against. Markets+ settlement specs are on
  this page too — the BO pipeline may eventually want the same treatment.
- **Two hard problems Miquel named:**
  1. **Slide dates lie.** A slide said "publish 5/22" but the file was actually
     posted **June 30**. Can't use the slide to know when the file is available.
  2. **No link on the slide** — have to know where SPP posts these.
- **Effort:** L (new fetch + document-locating logic; timing/availability is the
  tricky part).

### P1-2 · Read the right file inside the spec package and describe the change
- **What:** Within a spec release, prefer the **diff / comparison report**
  (previous vs. new version) and the **"summary of changes"** file — those contain
  the concrete detail (e.g. "mean occurs changed 0 → 1", "new demand-management
  service").
- **Edge case:** Brand-new services (e.g. demand management) don't appear in the
  diff — nothing to compare against. Handle new-vs-changed separately.
- **Caveat:** Format is *not* consistent across releases (draft vs. final layouts
  differ). Aim for "best-effort analysis a human then validates," per Miquel — the
  human confirms; the AI does the first pass.
- **Upgrade (2026-07-14, from decomposing Miquel's real analysis):** don't rely
  only on SPP's own change-summary docs — **diff the XSDs/WSDLs deterministically**
  (lxml, already a dependency): new services, new operations, element additions,
  `minOccurs` changes. Every factual claim in Miquel's FO analysis
  (DemandManagement v1, RsrcCommitmentSchedule, OfflineMaxLimit 0→1,
  GetMarketApprovedPricingStatusByIntervalSetByDay) is derivable from a schema
  diff with zero hallucination risk. The LLM's job is then annotation on top:
  plain-English impact, external research on unknown services (e.g. CHILL),
  and framing DECISION-NEEDED items (store vs. ignore, support vs. JAR-only) —
  never the facts themselves. Sample XMLs for new elements can be generated
  from the XSDs too.
- **Effort:** L.

### P1-3 · Name the exact ISOCOM tasks and the specific calc change
- **What:** Miquel could see "calc changes" flagged but not *what* changed. Report
  should list which ISO-communication tasks are affected and the concrete change.
- **Enrichment, not blocker (reprioritized 2026-07-14, Elizabeth):** PCI
  vocabulary is *not* required — what matters is that the tool consistently
  produces the closest analysis it can from SPP's own artifacts, every run. The
  PCI mapping files below are an optional enrichment layer that raises fidelity
  when/if the SMEs provide them:
  - **FO:** SPP operation → GSMS ISOC task → screen (e.g.
    `GetEnergyCommitmentSetByDay` = "Download Start Stop Instructions"; lives in
    heads + the `ISOC_XSD_Versions` LOV). → `spp_operation_map.yaml`, seeded
    opportunistically.
  - **BO:** SPP bill determinant → PCI calculation class (Kashmita's
    billing-determinant-source artifact, see P2-4).
  Without the maps the story says "SPP changed determinant X (formula, page N)";
  with them it also says which PCI calc class that is. Both are useful; ship
  without, enrich later.
- **Effort:** M (falls out of P1-2 once specs are being read); mapping files
  land whenever SMEs supply them.

---

## P2 — Benchmark & story generation (turn analysis into deliverables)

### P2-1 · Calibrate against the SMEs' real analyses + Jira stories
- **What:** Feed the SMEs' work to Claude as the gold standard: "given this raw
  data, reproduce this analysis and this story." Compare the AI output and close
  the gap.
- **Gold standards in hand (2026-07-14):**
  - **FO:** Miquel's spec-diff analysis + story **SP-12813** "[SPPIM: ISO
    Communication] Add new Energy and Market services to ISO Com" (input: API
    spec zip diff).
  - **BO:** Kashmita's story **SP-12814** "[SPPIM: Back Office: Settlements]
    Update Calculation to Support Fall Market Initiative" (input: RR728
    Recommendation Report — the exact docx already in the tool's cache).
  - Both hang off epic **SP-12812 "2026 Fall SPP Market Initiative"** (Parent
    Link PM-944), and share the same description skeleton: *Use Case/Problem
    Definition → Changes → Investigation Done/Background → Steps to Reproduce →
    Checkin Plan → Acceptance Criteria → Definition of Done*, with team
    boilerplate for AC ("DST dates impact tested…") and DoD. The story writer
    should be one shared component with per-team content generators.
- **Status:** Inputs in hand. Lucia also asked to keep Miquel's analysis for
  double-checking.
- **Effort:** M.

### P2-2 · Include the right working set
- **What:** Use the **fall-2026 market-initiative** files as the analysis input set
  (Sahij), and prior analysis outputs as benchmarks — **not** as raw input to
  re-analyze. (This is the "use it as a benchmark, not during the call"
  distinction Kashmita and Miquel clarified.)
- **Effort:** S.

### P2-3 · Generate real Jira stories with descriptions — BUILT 2026-07-14
_Implemented in `src/settlement/jira_template_writer.py`, wired into
`settlement-report`. Output: `Jira_Stories_SPPIM-<runid>.xlsx` in the synced
`Story templates/SPPIM/` folder (per-market layout), announced in Slack.
Create? blank on every row (PM gate), green columns untouched, epic Parent
Link blank. New workbook per run until Miquel answers the append-vs-new
question. Remaining: his answer, and the attachments/formula-images question._
- **What:** Move the settlement pipeline past Excel triage to filling Miquel's
  **`Jira_Story_Creator_template.xlsx`** (team format v1.1.0, in
  `marketsys/Shared Documents/RTO Development/Story Creation/`). His sync app
  reads this workbook and creates the Jira issues, then writes back the green
  columns (Jira Key, Sync Status, Sync Timestamp, Sync Error) — so the output
  must match the template **exactly** (sheet names, columns, amber/green split).
- **Template contract ("Jira Stories" tab, amber = we fill):**
  `Create?, Issue Type, Local ID, Summary, Description, Steps to Reproduce,
  Client Ticket, Epic, Epic Name, Parent Link, Complete After, Priority,
  Acceptance Criteria`. Summary convention: `[SPP: Back Office] <change>`.
  Epics come first with a Local ID (E1); stories point at the epic via that ID.
- **Decisions (2026-07-14):**
  - **Granularity:** one Story row per **RR + charge code** (mirrors the current
    triage sheet 1:1).
  - **Epic:** the tool generates one Epic row per run (e.g. "SPP Fall 2026
    Settlement Changes", Local ID `E1`); **Parent Link left blank** for the PM
    to fill with the initiative key (PM-XXX).
  - **Tests tab:** skipped in v1 — stories only.
  - **Quality bar for Description:** the real stories, not the template examples.
    For settlements that's **SP-12814**: link the RR docx, a go-live parameter
    block (old logic before go-live date / new after, "Go Live Date TBD" —
    reusable boilerplate for every market-initiative change), then numbered
    per-determinant instructions ("Update calculation for `RtDevHrlyQty` to match
    the math below", "Add calculation class for X… shadow calculation… round to
    3 decimal places"), each with the **formula image** from the RR.
- **Open problem — formulas/images:** Kashmita's description embeds formula
  screenshots (`!screenshot-N.png!`) clipped from the RR, and attaches the RR
  docx (`[^RR728 Recommendation Report.docx]`). The Excel template has no
  attachments column. Options: (a) ask Miquel whether his sync app can upload
  attachments referenced from a folder; (b) extract formula images from the RR
  docx (`word/media/`) to SharePoint and put **links** in the description;
  (c) transcribe formulas to text (risky for complex math). **Ask Miquel — this
  is the biggest fidelity gap between what the tool can emit via Excel and what
  the SMEs' real stories contain.**
- **Implementation notes:** fill a **copy of the real template** (preserves the
  app's expected formatting/validation) rather than rebuilding with openpyxl
  styling. Template must be fetched once — it lives in the RTO Development
  library, *not* in the synced ISO Agent Market Updates root. Write the filled
  copy to the "Story templates/SPPIM" folder so the existing Slack notifier
  announces it.
- **Confirmed scope (Kashmita):** Only **market-protocol** changes become
  settlement stories. Tariff/governance changes are informational only — no story.
  The tool's current classification already reflects this; keep it.
- **Depends on:** a local copy of the template file (in hand 2026-07-14 —
  Downloads). P2-4's determinant mapping *enriches* descriptions but is not a
  blocker: v1 ships with SPP-vocabulary descriptions (determinant names +
  formulas + page citations as they appear in the RR).
- **Effort:** M.

### P2-4 · Finish charge-code → billing-determinant mapping
- **What:** The settlement report identifies charge codes, page-cited
  modifications, and new/deleted status, but doesn't yet map each billing
  determinant — blocked on parsing the long formula format.
- **Elevated (2026-07-14):** SP-12814 shows this is *the* enabler for real BO
  stories — the story body is per-determinant instructions in **PCI calc-class
  vocabulary** (`RtDevHrlyQty`, `RtSIDevInc5minQty`, "shadow calculation",
  "copy value from statement"). Two layers needed:
  1. Extract per-determinant changes + formula images from the RR docx (tool
     side, automatable).
  2. Map SPP determinant names → PCI calculation classes (SME knowledge —
     **this is exactly Kashmita's billing-determinant-source artifact**; her
     follow-up meeting is now the critical path for BO story quality).
- **Effort:** M.
- **Related:** Kashmita's artifact on "where the source for each billing
  determinant is" (she's done day-ahead + real-time energy charge codes so far).
  Scheduled for a **separate follow-up meeting** — direct input to this item.

### P2-5 · Build the PM-review → generate-selected-stories workflow
- **What:** Miquel's proposed loop: AI proposes candidate stories/analysis in a
  spreadsheet → PM checks which ones to actually create → AI generates only the
  checked items. A checklist-driven middle step so the PM stays the decision-maker
  ("it's a decision from the PM to say yes/no we want this story").
- **Effort:** L.

### P2-6 · Package each analysis as a reusable Claude **skill** (Miquel's idea — promoted)
- **What:** Reproducibility is the requirement Elizabeth confirmed (2026-07-14):
  the same report, at the same quality, every run — not a one-off prompt that
  drifts. Package each pipeline's method as a versioned skill the tool invokes
  headlessly:
  - `spp-spec-diff-analysis` — FO: given two same-family spec zips, run the
    deterministic XSD/WSDL diff, then write the analysis in Miquel's exact
    structure (enumerated changes → impact → DECISION-NEEDED items).
  - `spp-settlement-story` — BO: given a classified RR docx, produce the
    SP-12814-shaped story (go-live parameter block → numbered per-determinant
    changes with citations → boilerplate AC/DoD).
- **Why skills specifically:** the method lives in a git-versioned SKILL.md
  (workflow + output skeleton + the gold-standard examples from P2-1 embedded
  as few-shot references), not in an engineer's chat history. Anyone on the
  team can re-run it; changes to the method are code-reviewed diffs.
- **Consistency levers, in order of power:** (1) deterministic pre-processing
  produces the *facts* (schema diff, charge-code extraction) so the LLM never
  free-recalls them; (2) fixed output skeleton in the skill; (3) gold-standard
  examples as calibration; (4) reconciliation gates like the settlement
  pipeline's existing hard-fail check.
- **Effort:** M (the settlement pipeline already has the headless-claude
  invocation pattern to build on).

---

## Awaiting external input (not blocked on us)

- **Kashmita — area→topic mapping** for P0-1, and her verdict on **report
  structure**: are both tabs (Exec-by-division + Full-by-topic) needed, or is one
  more useful? She's reviewing offline against her CUF/SUF copies once she has the
  link. **Action: send her the report link.**
- **Follow-up meeting** on Kashmita's billing-determinant-source artifact (feeds
  P2-4).

---

## Suggested sequence

1. **This week:** P0-1, P0-2, P0-3 (accuracy — cheap, rebuilds trust). Send
   Kashmita the link so her feedback lands.
2. **Next:** P2-1 (benchmark against both SMEs' stories — sets the target output)
   then P1-1 / P1-2 (spec fetching + deterministic diff — the real depth).
3. **Then:** P2-3 (template writer) + P2-6 (skills — lock in reproducibility),
   with P2-4 mapping enrichment and P2-5 PM workflow layered on after.
