---
name: settlement-report
description: Run the SPP settlement RR pipeline reproducibly — generate the SPP_RR_Report_Summary xlsx (published to the synced SharePoint "Story templates/SPPIM" folder) and one Jira story per RR from Recommendation Report docx files. Use when asked to run/rerun the settlement report, regenerate RR stories, or produce the Jira story workbook.
---

# Settlement RR report pipeline

One command produces everything; the pipeline is deterministic except the LLM
story call, whose behavior is pinned by the versioned prompt.

## Commands

Incremental (only RRs on the current CUF/SUF relevant list not yet in the ledger):

    python main.py settlement-report --call-claude

Specific RRs (bypasses the ledger):

    python main.py settlement-report --call-claude --files "<path to RR docx>" ...

Flags: `--call-claude` = generate LLM stories (~6 min per RR, real cost; omit for a
classification-only triage). `--stories` = also fill Miquel's Jira workbook template,
one workbook per RR, into the synced "Story templates/SPPIM" folder (leave off until
Elizabeth's signoff). `--all` = full re-run over the cache.

## Reproducibility contract

- **Prompt**: `src/settlement/rr_extraction_prompt.md`, first line `PROMPT_VERSION:`.
  Every persisted stories JSON records the `prompt_version` that produced it.
  Bump the version whenever the prompt changes.
- **One story per RR**: the prompt's ONE STORY PER RR rule; the pipeline logs a
  warning if the LLM violates it.
- **Fidelity, not judgment**: the prompt forbids editorial notes ("confirm with
  SME", "possible error"); stories transcribe the RR exactly. Implementation risk
  is the developer's call.
- **Deterministic extraction**: redline/equation/pagination handling is pure code
  (`rr_structure.py`, `pagination.py`) — same docx in, same marked text out.
- **Per-item pages**: after the LLM writes the story, `correct_item_pages`
  (pipeline) rewrites each item's `[p.X]` to the page where that item's
  determinant actually appears in the MARKUP PDF (same view as the screenshots) —
  deterministic, no LLM cost.
- **Items mirror**: each story carries an `items` array (one entry per numbered
  description item: concise `action` + `determinant`, no formula). The report tab
  shows the full formula; the Jira workbook shows `<action> [RR<id>-NN] [p.X]`,
  where the code matches the screenshot so Miquel's app inserts the image.
- **Redline screenshots**: `screenshots.item_screenshots` crops the COMPLETE
  formula per item from the markup PDF (bounded by the next definition / the
  variable glossary / a blank gap); a formula that crosses a page break becomes
  two images. Image-only (picture) formulas are skipped and logged.
- **Links**: `annotate_links` (pipeline) resolves the RR docx link (added to the
  description and the report's SharePoint column) and the CUF/SUF file named in
  the initiative citation (clickable in the report's Market Initiative cell).
- **PCI vocabulary**: `config/pci_vocabulary.yaml` is injected into the prompt when
  it has content (SME-maintained).

## Where outputs land

- Report xlsx: built in `data/reports/settlement/`, **published to the synced
  `Story templates/SPPIM/` SharePoint folder** (config
  `published_settlement_reports_dir`; `Reports/SPPIM` is HTML-only).
- Stories JSON (the LLM output, reusable without a second LLM call):
  `data/reports/settlement/stories/<RR>-<report stem>.json`.
- Formula images / rendered PDFs: `data/reports/settlement/images/`, `rendered/`
  (working artifacts, never published).
- Jira story workbooks (with `--stories`): synced `Story templates/SPPIM/`,
  one `<RR>_Jira_Stories-<run id>.xlsx` per RR, `Create?` left blank for the PM.
  When redline crops are produced, the story row gets a Local ID (the RR id) and
  a sheet with that exact name holds one cropped image per item (Miquel's guide
  contract). Crops come from a markup-view PDF; image-only formulas are skipped.
- Redline crops + rendered PDFs: `data/reports/settlement/screenshots/`,
  `rendered/` (working artifacts, never published).

## Rules

- Never edit the numbered items by hand in outputs — fix the prompt or extraction
  and rerun, otherwise the stories JSON and the artifacts diverge.
- The RR folder is append-only (revisions land as `.rev-YYYYMMDD` files).
- Rebuilding artifacts from existing stories JSONs (no LLM cost) is fine; the JSON
  records its prompt_version so stale story sets are detectable.
