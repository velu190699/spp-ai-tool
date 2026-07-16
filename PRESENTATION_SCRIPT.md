# SPP Market Intelligence Agent — Presentation Script

> **Historical snapshot.** Translated from the original Spanish (`script_presentacion.md`). Written as a presentation script early in the project — several items it describes as "in progress" or "blocked" (the Claude summarizer, real Slack delivery) have since been completed. Kept for historical context; see `README.md` for current behavior.

---

## INTRODUCTION

Today I'm presenting the SPP Market Intelligence Agent, a tool that automates monitoring of regulatory changes in the SPP market.

The problem it solves is simple: today, someone on the team has to manually log into SPP.org every month, download documents, review them, identify what changes are coming, and notify the team. That takes hours. This agent does it alone.

The flow has 5 phases. Of those 5, we have 3 fully implemented and working today. The other 2 are in progress.

---

## PHASE 1 — TRIGGER

The first phase is the trigger: how the agent starts without anyone launching it manually.

We use Windows Task Scheduler. We created a batch file called `run_agent.bat` that the scheduler runs automatically on the date we configure — monthly, quarterly, whatever we need.

One important thing we solved: if the computer was off on the scheduled day, the agent runs on the next startup. And if there's no internet connection, it waits — there's no point running if it can't download anything.

**Status: fully implemented and working.**

---

## PHASE 2 — WEB SCRAPING

The second phase downloads 4 documents from SPP.org:

- The RR Master List, an Excel file with all proposed changes
- The CUF materials, monthly meetings in ZIP format with PDFs inside
- The SUF materials, a quarterly settlement meeting
- The Integrated Marketplace Protocol, the reference protocol

To navigate SPP.org we use `requests` and `BeautifulSoup`, direct scraping without needing to open a browser. It works well for SPP.org as it is today.

We also have `Playwright` reserved as a fallback in case SPP.org ever requires more browser interaction, but it's not needed for now.

To avoid re-downloading the same thing, each file is registered with its SHA-256 hash. If the file hasn't changed on the next run, it's skipped.

Regarding SharePoint: files are saved locally in OneDrive. The real connection to SharePoint via the Microsoft API is pending — we need IT to configure the permissions in Azure, but the logic is already written and ready to connect once that's available.

**Status: download and deduplication are working. Real SharePoint pending IT.**

---

## PHASE 3 — PROCESSING AND CROSS-REFERENCE

This is the most important phase, the one that gives the agent its value.

The problem is that the RR Master List can have hundreds of open changes. Not all of them are relevant — only the ones close to being implemented. How do we identify which ones? By cross-referencing two sources.

First, we read the Excel with `openpyxl` and keep only the rows where Status is "Open."

Then we extract the text from the CUF and SUF PDFs using `pypdf`, and use regular expressions to find every RR number mentioned — whether as "RR623," "RR-623," or "RR 623." We also identify the dates that appear near each mention to determine the timeline.

One detail we solved this week: the CUF's Action Items file has a table where RR numbers appear without the "RR" prefix — they're just numbers in the first column. We added a specific extractor for that format.

The result of the cross-reference is: the RRs that are Open in the Master List AND are also mentioned in the CUF or SUF meetings. In the last run we identified 7 relevant RRs.

For each RR we also download its Recommendation Report, the official document with all the details of the change.

On tooling: we use `openpyxl` directly for the Excel file because the file structure is stable. At some point we'll migrate to `pandas`, which is more robust if SPP moves columns around. For PDFs we use `pypdf`, which works well for the current documents. `PyMuPDF` and `pdfplumber` are being considered for the day we need to extract complex tables.

**Status: fully implemented. 7 relevant RRs identified in the last run.**

---

## PHASE 4 — ARTIFICIAL INTELLIGENCE

The fourth phase connects the processing step to Claude, Anthropic's language model.

The idea is for Claude to receive the text extracted from the CUF and SUF PDFs, analyze it, and produce two things: first, a summary of what changes are coming, in which areas, and on what timeline. And second, an executive summary that highlights the most important points for the team.

That summary is what eventually goes to email and Slack, instead of a list of RR numbers that means nothing to anyone.

The `summarizer.py` file exists, but doesn't yet have the calls to the Claude API. It's the next step in development.

**Status: pending implementation. It's the next milestone.**

---

## PHASE 5 — OUTPUT AND DISTRIBUTION

The fifth phase distributes the results.

What already works: the agent generates a JSON report for each run with all relevant RRs, their dates, their sources, and the downloaded documents. That report is saved in OneDrive.

It also generates a draft Slack message with the 7 RRs, their associated dates, and the document and page where each was mentioned. For now that message is printed to the log — it still needs to be connected to the Slack SDK with the channel's webhook.

What's blocked: email. We need credentials for PCI's SMTP server, which is in IT's hands. An alternative we're evaluating is using MS Graph Mail, which doesn't require our own SMTP server and connects directly to Outlook, and we can implement it in parallel with SharePoint.

**Status: JSON reports working. Slack ready to connect. Email blocked by IT.**

---

## SUMMARY

To wrap up: we have an agent that today connects to SPP.org, downloads the 4 relevant documents, cross-references the information, and tells us exactly which 7 regulatory changes are close to being implemented, with date and source.

What's missing: the natural-language summary via Claude, and the real distribution channels — Slack, email, and SharePoint. Those three things are in progress and none of them require changes to the logic we've already built.

---
