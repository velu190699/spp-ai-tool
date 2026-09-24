# RR Control App — what we are building and why

_Status: design agreed 2026-09-15; a working prototype exists (§9), nothing
committed. Extends `FEEDBACK_ACTIONS.md`
(the 2026-07 backlog) with the decisions taken after the 2026-09-02 "Monitoring
tool update" meeting. Roles, not names: **BO PM** owns back office, **FO PM**
owns front office, **the builders** maintain the tool._

---

## 1. Where we are today

The tool runs unattended every Monday at 10:00 (`run` → `settlement-report`) and
publishes, into the synced SharePoint library:

- **RR Control dashboard** — `Reports/Control/RR_Control-<runid>.html`, one file
  per run (20 so far), plus `RR_Control.html`, a fixed-name copy added
  2026-09-15 so there is finally a link that never changes.
- **Full report** — `Reports/Briefings/SPP_Market_Changes_Summary-<runid>.html`,
  the LLM briefing, routed per PCI division by `config/area_routing.yaml`.
- **Story workbooks** — `Stories/BO/RR<n>_Jira_Stories-<runid>.xlsx`, the team's
  Jira template filled in, `Create?` blank for the PM gate.

State lives in `${SPP_SYNC_ROOT}/SPPIM/State/metadata.json`. Today it tracks
**19 RRs, all back office, all open**: 4 SETTLEMENT_CALC, 8 SETTLEMENT_RELEVANT,
5 TARIFF_GOVERNANCE, 2 with no Recommendation Report parsed yet.

### How the cost actually works

Worth stating plainly, because it shapes what the PM gate is for. The analysis
ledger (`metadata_store.check_analysis`, `main.py:1337`) keys on the **hash of
the Recommendation Report docx**. An RR whose docx has not changed is skipped
entirely — an already-processed RR costs **nothing** on a weekly run.

Re-analysis happens only when SPP **re-publishes** an RR: the zip is always
re-downloaded (it is deleted after extraction), the new hash does not match, the
new docx is stored alongside the original as `.rev-YYYYMMDD.docx`, the ledger
returns `updated`, and the RR is analysed again in full and flagged as an UPDATE
(~$1.15 and ~5 minutes of LLM per RR). That is where a PM's "does not apply"
saves money — not on the first pass, which happens the same Monday the RR is
discovered, before anyone has reviewed anything.

### The constraint that shapes everything (verified 2026-09-15)

SharePoint renders the published HTML inside a sandboxed iframe with an opaque
origin (`about:srcdoc`, `origin: null`). JavaScript runs, but `localStorage` and
`sessionStorage` throw `SecurityError`, `document.cookie` throws, and every
network call fails. Google Drive's viewer behaves the same way — that is why the
inline `onclick` on the Word links had to move into external JS. **A published
HTML file cannot store anything.** Whatever the PM marks has to live elsewhere.

## 2. What the meeting asked for

| # | Request | Status |
|---|---------|--------|
| 1 | RR-amends-RR link + Jira story number | Not built. An amending RR usually names the RR it amends in its opening text; the tool simply does not look. |
| 2 | Marketing Initiative catalog (draft + validated) | Extractor and `config/initiative_overrides.yaml` exist, but the override replaces the extracted value instead of sitting beside it. No catalog. |
| 3 | Filter / dim non-applicable RRs | **Done.** Dimming shipped 2026-09-02; the hide filter shipped 2026-09-15 (19 rows → 4). |
| 4 | Applies / Reviewed, editable by the PM | Not built. This app is the answer. |
| 5 | Hash change detection + published date | Covered for RR Master List, RR packages, CUF and Protocol. **Two gaps:** SUF skips the hash check (`main.py:751` passes neither `redownload_on_hash_change` nor `transient_local_copy`, so a cached SUF is returned unverified), and `record_document` does not persist the portal's published date although `_extract_published_date` already parses it. |
| 6 | Dashboard ↔ Full Report link + report index | **Partly done.** Fixed-name dashboard link and a masthead link to the newest full report shipped 2026-09-15. Per-row link and the index are part of this app. |
| 7 | Tech specs (WSDL/XSD) | `src/specs/` handles discovery, archiving, draft-vs-final and analysis, but is not wired into `main.py` and fetches only the "RTO Markets" family. Its own dashboard, same app. |
| 8 | SPP "Sub Updates" | Identified 2026-09-15: monthly PDFs published as e.g. *September 2026 SUF Updates* (`spp.org/documents/77734/...`, ~670 KB, posted 2026-09-10), separate from the quarterly `SUF Meeting Materials` zip. Treat as an **extension/refresh of the SUF materials**, not a new family. Note the URL form is `documents/<id>/<name>` — the ID-addressable pattern request 5 asked about, and what `SppClient` already keys on. |

## 3. Where we want to get to

The ask is to **centralise**: one place to see and act, instead of a document you
read and a spreadsheet you edit somewhere else. Everything the tool produces or
downloads should be reachable from there, including the source materials sitting
in SharePoint.

The deeper shift: today the tool decides what becomes a Jira story and the PM
finds out afterwards. The complaint raised in the meeting — too many templates
created for RRs that do not apply — is that symptom. **After this change the PM's
decision drives the pipeline:**

- PM marks an RR *does not apply* → the tool stops generating its story, and
  stops re-analysing it when SPP re-publishes it.
- PM marks an RR *does apply* → the tool generates it, flagged as a PM decision.
- PM discards an RR that already has a story workbook → the tool **archives** it
  (moves to `Stories/BO/Archive/`, never deletes).

That turns the dashboard from a register into the control surface of the pipeline.

## 4. Architecture

**Two owners, one view.** The tool owns `metadata.json` and the app never writes
to it. The app owns `decisions.db` (SQLite) and the tool only reads it. They are
joined by RR number when the table is drawn.

This is deliberate: the run keeps working whether or not anyone opens the app; if
the app breaks, no tool data is lost; and there is no read-merge-write dance in
which a run could overwrite what the PM just marked — the failure mode that made
an editable spreadsheet unattractive.

**Delivery** follows the precedent already in use by this team (the CloudDesk
app): a Streamlit app each person runs locally, no server, no VM, shared state in
a file on the NAS. The app lives inside this repo and reuses
`build_rr_control_rows`, `config.py` and the existing state reader.

**The database goes on the NAS, never in the OneDrive-synced folder.** OneDrive
syncs whole files and creates conflict copies; for SQLite that means silent
corruption. Only PMs write, so concurrent-write risk is otherwise low.

## 5. Data model

`decisions.db`, one row per RR:

| field | meaning |
|-------|---------|
| `rr_number` | key |
| `domain` | BO / FO — one app serves both, one row space |
| `applies` | yes / no / undecided — may contradict the tool |
| `reviewed` | one flag per RR (not per reviewer) |
| `reviewed_by`, `reviewed_at` | the acting account + timestamp (work email once signed in, Windows user locally) |
| `initiative_validated` | chosen from the catalog, or created on the spot |
| `related_rr` | the RR this one amends |
| `jira_key` | read from the workbook when possible, else typed |
| `note` | free text |
| `class_when_decided` | the tool's classification at the time of the decision |

`class_when_decided` is what stops us repeating the 2026-08 problem in which two
RRs kept offering an "open story" while the same row said "no calculation
impact". When the tool later reclassifies an RR, the app does not silently keep
or drop the decision: it flags the row as "the tool changed its mind since you
reviewed this". Same principle when SPP re-publishes a Recommendation Report:
`reviewed` is **not** cleared, the row is marked "reviewed, but a new version
arrived".

A second table holds the **initiative catalog** (name, active, notes).

## 6. Screens

1. **Control** (main view) — the RR table. Tool columns read-only; PM columns
   editable: applies, reviewed, validated initiative, related RR, Jira key, note.
   Filters: pending review, calculation changes only, discarded, all. Grouping by
   initiative. Row click expands the CUF/SUF mention history. A discarded RR
   stays visible, marked as discarded, and disappears under the filter.
   Show the validated initiative; show the tool's extracted value only when there
   is no validated one.
2. **Determinants** — the charge-code before/after table, as in today's HTML.
3. **Published** — every artefact the tool has published: dashboards, full
   reports, executive summaries and story workbooks, newest first, each opening
   the original. This is request 6's index portal.
4. **Materials** — the source documents downloaded into SharePoint (CUF/SUF
   editions, Recommendation Reports, protocols, SUF Updates), browsable and
   openable from here rather than by navigating the library by hand.
5. **Settings** — initiative catalog, and the division topics that drive the
   executive summary (today `config/area_routing.yaml`). It belongs to another
   pipeline, but the point of the app is that everything is reachable in one
   place.

The published HTML keeps being generated as the read-only view for whoever does
not install the app, and once `decisions.db` exists the tool reflects the PM's
marks in it.

### History

Each published dashboard is already a snapshot of the register on that date, so
the **Published** screen links them rather than trying to re-open them inside the
app — they are the frozen version of what the app shows live and better. For
real history ("what changed since last week") the app writes its own structured
snapshot each run from now on. Parsing 20 existing HTML files to reconstruct the
past would be expensive and fragile; linking them costs nothing.

## 7. Decisions taken (2026-09-15)

- Two PMs: back office (the only half implemented today) and front office.
  **One app, both domains**, hence `domain` in the schema.
- The PM may contradict the tool: the tool assists, the PM decides.
- `reviewed` is one flag per RR, not per reviewer.
- The PM may create a new initiative on the spot, not only pick from a list.
- Jira key: try to read it from the workbook, but let the PM type it.
- The weekly Slack message says how many RRs are pending review, alongside the
  existing "what changed since the previous version" delta.
- VPN/office only. Acceptable: if a PM is travelling, they are not working.
- Maintained by the builders, ideally by the PMs in time.

## 8. Open questions

- **Access control.** Settled in shape (§10): open to read, signed in to edit.
  What remains is whether the admin credential is one shared password or one per
  person, and who issues it.
- **Distribution.** The NAS is reachable for both PMs. `git pull` suits the
  builders; a zip may suit a PM who does not use git. Possibly both.
- **How early the gate applies.** Stopping story generation is simple. Stopping
  the re-analysis of a discarded RR when SPP re-publishes it is where the money
  is (see §1). Both are wanted; confirm the second is worth the extra wiring.
- **Forced "applies" with no source.** If a PM forces "applies" on an RR with no
  Recommendation Report, there is nothing to analyse. What should the tool do?
- **Sub Updates.** Shape now known (§2). Still to decide: does an update to an RR
  already on the watch list re-trigger anything, or is it informational?

## 9. What the prototype actually is (2026-09-24)

Built and working against the real watch list. `run_dashboard.bat`, or
`python -m streamlit run dashboard_app.py`. Nothing is committed yet.

| file | what it is |
|---|---|
| `dashboard_app.py` | shell: theme, viewer, navigation |
| `src/control_app/screens.py` | the pages |
| `src/control_app/decisions.py` | `decisions.db` — PM decisions + initiative catalog |
| `src/control_app/auth.py` | who is looking, and whether they may edit |
| `src/control_app/library.py` | what has been published, and the source materials |
| `src/control_app/theme.py` | the report's palette, badges and masthead |
| `config/app_access.yaml` | the editor list |
| `tests/test_decisions.py`, `tests/test_auth.py` | 170 tests pass |

**Pages.** Briefing (the published `SPP_Market_Changes_Summary` served as-is,
with an edition picker, plus the register grouped by initiative) · Control (the
register, the report's own stats and hide filter, clickable rows, a decision
panel and a detail dialog) · Published reports · Source materials · Settings
(initiative catalog and the division topics in `area_routing.yaml`).

**Decisions** save to SQLite with the account, the timestamp and the tool's
classification at the time. A later reclassification flags the row rather than
discarding or silently keeping the decision.

**Access.** Read for everyone; editing limited to the accounts in
`config/app_access.yaml`. Empty list means editable **locally only** — deployed,
an empty list grants nobody editing. Ready for Streamlit's native OIDC
(`st.login` / `st.user`, present in 1.58) once there is an Entra registration;
until then the Windows account stands in.

### Not built

- The pipeline gate (§3) — the whole point of the exercise, and untouched: the
  tool does not read `decisions.db` yet.
- `reviewed` is not reset or flagged when SPP re-publishes a Recommendation
  Report (decided in §7, not implemented).
- Per-row link from an RR to the briefing that discussed it (§2 request 6):
  briefings are named by run id and the state records no path, so the mapping
  does not exist. Recording the published path against the edition key is the
  prerequisite.
- The FO half: one app, one `domain` column, but no FO rows exist yet.
- The two §2 request-5 gaps in the tool itself (SUF hash check, published date).

### Known rough edges

- Clicking a row is a real link, so the page reloads — a couple of seconds,
  because importing `main` pulls in the whole pipeline. Caching the watch-list
  read would cut most of it.
- Streamlit rewrites every markdown link to `target="_blank"`; an invisible
  component puts the in-app ones back to `_self` (`theme.same_tab_links`).
- Editing a module while the app runs does not always reload it — restart after
  changing anything under `src/`.

## 10. Deployment and access

The original ask was **a link everyone can open, where the PM can act**. A
Streamlit app each person installs and runs locally does not meet that: the link
would be `localhost`, working only on that machine. Running the same app on a
machine that is always on does meet it — the code is identical, only where it
runs changes.

Three levels, in order of commitment:

| | What it gives | What it costs |
|---|---|---|
| **Local** (today) | Enough to validate whether the way of working suits the PMs | No link; every person installs it |
| **An always-on machine** | A real URL on the internal network, in an afternoon | Dies when that machine is off; no IT involvement |
| **A VM** | The same, properly hosted | Infrastructure to request and maintain |

**Access model (the team's existing internal-tool pattern):** open read access —
anyone with the link sees the register, the briefing, the library — and an
**admin sign-in with username and password** for editing. Signed out, the app is
a dashboard; signed in, the decision controls and Settings appear. That matches
what people already expect from the team's other internal tools, and it removes
the awkwardness of a Windows username that records who acted but stops nobody.

Implications worth stating before it is built:

- Credentials live in the app's config (hashed, never in the repo), not in Azure
  AD. This is not SSO: it will not know who someone is, only that they hold the
  admin credential. Enough for "who may edit", not an audit trail on its own —
  which is why `reviewed_by` should record the signed-in account, not the
  Windows user, once this exists.
- A shared password cannot attribute a decision to a person. One credential per
  PM keeps `reviewed_by` meaningful.
- **Data access is the real work.** The app reads `metadata.json` from the
  OneDrive-synced library and writes `decisions.db` on the NAS. A host that is
  not somebody's laptop must reach both — either it syncs that library too, or
  the state moves to a network path. Nobody has looked at this yet.
- The weekly run still happens wherever the scheduled task is registered. The
  app is a reader of its output, not its host, so the two can live apart.

## 11. Questions for the PMs

Open items that need a human answer, grouped by what each unblocks. The first
three block design; the rest can follow.

**Dashboard**

1. What must "a link everyone can open" allow — a browser with nothing
   installed, or installing an app once? (Answer recorded: open read access plus
   an admin login, per §10.)
2. One shared admin password, or one per PM? The second keeps "reviewed by"
   truthful.
3. Is access from outside the office needed, or is VPN/office enough?

**The pipeline gate**

4. If a PM marks an RR as not applying, should the tool stop generating its
   story?
5. And the reverse: if a PM says it does apply after the tool dismissed it,
   should the tool generate one?
6. When a discarded RR is re-published by SPP, should it be re-analysed? Today it
   is, at roughly $1.15 and five minutes each time.
7. If a PM discards an RR that already has a workbook, archive it automatically?

**Front office**

8. What is the unit of the FO dashboard — a spec release, a service, an
   operation? Deferred since August; nothing can be designed without it.
9. Is the `MaxOfflineResponse` change across the eight Reserve operations in
   scope for the ISOCOM story? The deterministic analysis found it and the
   reference story did not include it.
10. What do SPP's "Sub Updates" actually contain, and does anyone use them?
11. Who curates the market initiative catalog, given that only PMs can edit?

**Long-standing**

12. Does the sync app read workbooks from `Stories/BO/`?
13. Can it attach images to Jira issues? This is the biggest fidelity gap
    between what the tool emits through Excel and what real stories contain.
14. Can the combined `SPP_RR_Report_Summary.xlsx` be retired?
