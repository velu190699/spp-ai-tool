from __future__ import annotations

import logging
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)

# Slack rejects Incoming Webhook payloads that take too long; keep it short.
_SLACK_TIMEOUT_SECONDS = 10
_SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
# Slack rejects a Block Kit text object longer than 3000 chars; pack RR lines
# into multiple section blocks, splitting before this soft limit.
_SLACK_SECTION_TEXT_LIMIT = 2900

# Icons for the "what changed since last time" delta lines shared by the RR
# Control and story-drafts messages. Keyed by change kind.
_DELTA_ICONS = {
    "new": ":new:",
    "updated": ":arrows_counterclockwise:",
    "closed": ":white_check_mark:",
    "status": ":arrow_right:",
}


def format_delta_lines(changes: list[dict[str, Any]]) -> list[str]:
    """Render ``[{kind, text}, ...]`` into mrkdwn bullet lines, icon by kind.

    ``kind`` is one of new/updated/closed/status; an unknown kind falls back to a
    plain bullet. ``text`` is already-formatted mrkdwn (may contain *bold*).
    """
    lines = []
    for change in changes:
        icon = _DELTA_ICONS.get(change.get("kind", ""), "•")
        lines.append(f"• {icon} {change.get('text', '')}")
    return lines


def _deliver(payload: dict[str, Any], *, webhook_url: str, bot_token: str, channel: str, what: str) -> bool:
    """Send a prebuilt payload via bot token (preferred) or webhook; never raises.

    Shared by the newer notifications; mirrors the delivery rules of
    ``send_slack_report_link``. Returns True only on a confirmed post.
    """
    if bot_token and channel:
        ok = _post_via_bot(bot_token, channel, payload)
    elif webhook_url:
        ok = _post_via_webhook(webhook_url, payload)
    else:
        LOGGER.info("Slack not configured; %s notification skipped", what)
        return False
    if ok:
        LOGGER.info("Posted %s notification to Slack", what)
    return ok


def format_slack_draft(relevant_rrs: list[dict[str, Any]], warnings: list[str]) -> str:
    lines = ["SPP RR automation draft notification", ""]
    if not relevant_rrs:
        lines.append("No relevant open RRs were identified in the latest CUF/SUF materials.")
    else:
        lines.append("Relevant open RRs identified:")
        for rr in relevant_rrs:
            dates = ", ".join(rr.get("dates", [])) or "No nearby dates found"
            title = rr.get("title") or "(no title)"
            sources = ", ".join(rr.get("sources", [])) or "unknown source"
            lines.append(f"- RR{rr['rr_number']}: {title} | dates: {dates} | sources: {sources}")
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend(["", "Slack delivery and stakeholder routing are pending in v1."])
    return "\n".join(lines)


def log_slack_draft(relevant_rrs: list[dict[str, Any]], warnings: list[str]) -> str:
    draft = format_slack_draft(relevant_rrs, warnings)
    LOGGER.info("Slack draft notification:\n%s", draft)
    return draft


def _relevant_rr_line(rr: dict[str, Any]) -> str:
    """One Block Kit mrkdwn bullet for a relevant RR, linked to its SPP search."""
    number = rr.get("rr_number", "?")
    title = rr.get("title") or "(no title)"
    url = rr.get("search_url") or ""
    label = f"<{url}|RR{number}>" if url else f"RR{number}"
    line = f"• {label}: {title}"
    if rr.get("updated"):
        # SPP re-published this RR since it was last analyzed — reviewers must
        # treat any previously generated analysis/story for it as stale.
        line = f"• :arrows_counterclockwise: *UPDATED* {label}: {title}"
    group = rr.get("primary_working_group")
    if group:
        line += f" — {group}"
    dates = ", ".join(rr.get("dates", []))
    if dates:
        line += f" ({dates})"
    return line


def _relevant_rr_blocks(relevant_rrs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Block Kit section(s) listing the relevant open RRs.

    Lines are packed into as few section blocks as possible, splitting before a
    block would exceed Slack's per-text limit so a long RR list isn't rejected.
    """
    header = f"*Relevant open RRs ({len(relevant_rrs)})*"
    if not relevant_rrs:
        return [{"type": "section", "text": {"type": "mrkdwn",
                 "text": f"{header}\n_None identified in the latest CUF/SUF materials._"}}]
    blocks: list[dict[str, Any]] = []
    chunk = header
    for rr in relevant_rrs:
        line = _relevant_rr_line(rr)
        # Guarantee no single line can produce an over-limit (rejected) block.
        # The linked RR label leads the line, so truncating the tail only clips
        # a pathologically long title, leaving the <url|RRnnn> link intact.
        if len(line) > _SLACK_SECTION_TEXT_LIMIT:
            line = line[: _SLACK_SECTION_TEXT_LIMIT - 1] + "…"
        candidate = f"{chunk}\n{line}"
        if len(candidate) > _SLACK_SECTION_TEXT_LIMIT:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})
            chunk = line
        else:
            chunk = candidate
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})
    return blocks


def format_report_link_message(
    report_title: str,
    report_url: str,
    relevant_rrs: list[dict[str, Any]] | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Build the Slack payload announcing a published report.

    The message uses Block Kit so the SharePoint link renders as a labeled,
    clickable line rather than a bare URL. ``text`` is the notification/preview
    fallback used in banners and screen readers. When ``relevant_rrs`` is
    provided (even an empty list), the relevant open RRs are appended below the
    link as a bulleted list; pass ``None`` to omit that section entirely.

    ``note`` overrides the link line with an explicit status line. Use it when
    no report was published (build failed, or no source materials) so the
    channel isn't sent a success-looking "published" message for a non-event.
    """
    if note:
        body = f"*{report_title}*\n:warning: {note}"
        fallback = f"{report_title} — {note}"
    elif report_url:
        body = f"*{report_title}*\n<{report_url}|Open the report in SharePoint>"
        fallback = f"{report_title} — {report_url}"
    else:
        # No SharePoint URL resolved (e.g. report published outside the synced
        # library); still announce it so the channel isn't left silent.
        body = f"*{report_title}*\n_Report published locally; no SharePoint link available._"
        fallback = f"{report_title} (no SharePoint link available)"
    blocks: list[dict[str, Any]] = [{"type": "section", "text": {"type": "mrkdwn", "text": body}}]
    if relevant_rrs is not None:
        blocks.append({"type": "divider"})
        blocks.extend(_relevant_rr_blocks(relevant_rrs))
    return {"text": fallback, "blocks": blocks}


def format_story_drafts_message(
    rr_links: list[tuple[str, str]],
    *,
    date_label: str = "",
    changes: list[dict[str, Any]] | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Build the Slack payload announcing per-RR Jira story templates.

    Leads with what changed this run (Eduardo, 2026-07-22): a heading, an
    optional "New/updated this run" delta, then one linked line per RR pointing
    at that RR's story-template workbook so a PM opens the exact template from
    Slack. The standalone settlement-report link was dropped — the per-RR
    templates are the deliverable. ``rr_links`` is [(rr_id, workbook_url), …]; a
    blank url falls back to the bare RR id. ``note`` replaces the body with a
    status line (e.g. a failure).
    """
    n = len(rr_links)
    suffix = f" — {date_label}" if date_label else ""
    header = f":memo: *SPP RR story drafts{suffix}*"
    if note:
        body = f"{header}\n:warning: {note}"
    else:
        body = f"{header}\n{n} RR story template{'' if n == 1 else 's'} ready for PM review."
    blocks: list[dict[str, Any]] = [{"type": "section", "text": {"type": "mrkdwn", "text": body}}]

    if changes:
        lines = ["*New/updated this run:*"] + format_delta_lines(changes)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})

    tmpl_lines = ["*Story templates:*"]
    for rr, url in rr_links:
        tmpl_lines.append(f"• <{url}|{rr} story template>" if url else f"• {rr} story template (no link)")
    blocks.append({"type": "divider"})
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(tmpl_lines)}})

    rr_names = ", ".join(rr for rr, _ in rr_links)
    fallback = f"SPP RR story drafts{suffix} — {rr_names}" if rr_links else f"SPP RR story drafts{suffix}"
    return {"text": fallback, "blocks": blocks}


def send_slack_story_drafts(
    rr_links: list[tuple[str, str]],
    *,
    date_label: str = "",
    changes: list[dict[str, Any]] | None = None,
    webhook_url: str = "",
    bot_token: str = "",
    channel: str = "",
    note: str = "",
) -> bool:
    """Post the story-templates announcement (delta + per-RR template links).

    Same delivery rules as ``send_slack_report_link``; never raises.
    """
    payload = format_story_drafts_message(rr_links, date_label=date_label, changes=changes, note=note)
    return _deliver(payload, webhook_url=webhook_url, bot_token=bot_token, channel=channel,
                    what=f"story-drafts ({len(rr_links)} templates)")


def _post_via_webhook(webhook_url: str, payload: dict[str, Any]) -> bool:
    try:
        response = requests.post(webhook_url, json=payload, timeout=_SLACK_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        LOGGER.error("Failed to post to Slack webhook: %s", exc)
        return False
    return True


def _post_via_bot(bot_token: str, channel: str, payload: dict[str, Any]) -> bool:
    body = {"channel": channel, **payload}
    headers = {"Authorization": f"Bearer {bot_token}"}
    try:
        response = requests.post(_SLACK_POST_MESSAGE_URL, json=body, headers=headers, timeout=_SLACK_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        LOGGER.error("Failed to call Slack chat.postMessage: %s", exc)
        return False
    # chat.postMessage returns HTTP 200 even for logical failures (bad channel,
    # missing scope, bot not in channel); the real status is the `ok` field.
    if not data.get("ok"):
        LOGGER.error("Slack chat.postMessage rejected the message: %s", data.get("error", "unknown error"))
        return False
    return True


def send_slack_failure(
    step: str,
    error: str,
    *,
    webhook_url: str = "",
    bot_token: str = "",
    channel: str = "",
) -> bool:
    """Announce a failed scheduled run so it never dies silently.

    Same delivery rules as ``send_slack_report_link``; never raises. The error
    text is truncated — the log file has the full traceback, Slack only needs
    enough to know something broke and where.
    """
    detail = error if len(error) <= 500 else error[:499] + "…"
    payload = {
        "text": f"SPP tool FAILED at {step}: {detail}",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":rotating_light: *SPP tool run failed* — step: `{step}`\n```{detail}```\n_See the run log for the full traceback._",
                },
            }
        ],
    }
    if bot_token and channel:
        ok = _post_via_bot(bot_token, channel, payload)
    elif webhook_url:
        ok = _post_via_webhook(webhook_url, payload)
    else:
        LOGGER.info("Slack not configured; failure notification skipped")
        return False
    if ok:
        LOGGER.info("Posted failure notification to Slack (step: %s)", step)
    return ok


def send_slack_report_link(
    report_title: str,
    report_url: str,
    *,
    webhook_url: str = "",
    bot_token: str = "",
    channel: str = "",
    relevant_rrs: list[dict[str, Any]] | None = None,
    note: str = "",
) -> bool:
    """Post the published report link to a Slack channel.

    Uses ``chat.postMessage`` when a bot token and channel are provided, else an
    Incoming Webhook. When ``relevant_rrs`` is given, the message also lists the
    relevant open RRs beneath the link. ``note`` replaces the link line with an
    explicit status line (e.g. a build failure). Returns True on success. Never
    raises: a Slack failure must not sink an otherwise-successful report run, so
    problems are logged only.
    """
    payload = format_report_link_message(report_title, report_url, relevant_rrs, note)

    if bot_token and channel:
        ok = _post_via_bot(bot_token, channel, payload)
    elif webhook_url:
        ok = _post_via_webhook(webhook_url, payload)
    else:
        LOGGER.info("Slack not configured (no bot token/channel or webhook); skipping notification")
        return False

    if ok:
        LOGGER.info("Posted report link to Slack: %s", report_url or "(no link)")
    return ok


# --------------------------------------------------------------------------- #
# Option B #6 — distinct, well-crafted messages per report type.
# --------------------------------------------------------------------------- #

def format_heartbeat_message(
    date_label: str,
    watched_count: int,
    control_url: str = "",
) -> dict[str, Any]:
    """A no-change weekly ``run`` heartbeat, so silence is never ambiguous.

    Confirms the tool ran and found nothing new; links the RR Control dashboard
    for the current watch list. Posted only when a run detected no new CUF/SUF
    edition and no RR-level change.
    """
    body = (
        f":zzz: *SPP weekly check — {date_label}*\n"
        f"No new CUF/SUF materials and no RR changes since last week. "
        f"Watching *{watched_count}* open settlement RR{'' if watched_count == 1 else 's'} — nothing to action."
    )
    blocks: list[dict[str, Any]] = [{"type": "section", "text": {"type": "mrkdwn", "text": body}}]
    if control_url:
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"<{control_url}|Open the RR Control dashboard>"}]})
    return {"text": f"SPP weekly check — {date_label}: no changes", "blocks": blocks}


def send_slack_heartbeat(
    date_label: str,
    watched_count: int,
    *,
    control_url: str = "",
    webhook_url: str = "",
    bot_token: str = "",
    channel: str = "",
) -> bool:
    """Post the no-change heartbeat; same delivery rules; never raises."""
    payload = format_heartbeat_message(date_label, watched_count, control_url)
    return _deliver(payload, webhook_url=webhook_url, bot_token=bot_token, channel=channel, what="heartbeat")


def _briefing_action_elements(report_url: str, control_url: str) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    if report_url:
        elements.append({"type": "button", "style": "primary",
                         "text": {"type": "plain_text", "text": "Open full report", "emoji": True},
                         "url": report_url})
    if control_url:
        elements.append({"type": "button",
                         "text": {"type": "plain_text", "text": "RR Control dashboard", "emoji": True},
                         "url": control_url})
    return elements


def format_briefing_by_area(
    date_label: str,
    areas: list[dict[str, Any]],
    *,
    sources_line: str = "",
    report_url: str = "",
    control_url: str = "",
) -> dict[str, Any]:
    """All-teams briefing as one colored card per PCI area (the skim view).

    ``areas`` is ``[{name, color, summary}, …]`` in display order — the area's
    tight summary blurb, not a list of RRs. Each area renders as a Slack
    attachment with its color bar. The action buttons live in a trailing
    attachment so they appear BELOW the cards (top-level blocks always render
    above attachments in Slack). Posted only when a new CUF/SUF edition arrived.
    """
    intro = "Weekly summary of SPP market changes by PCI area."
    if sources_line:
        intro += f"\n_{sources_line}_"
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"SPP Market Changes — {date_label}", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": intro}},
    ]

    attachments: list[dict[str, Any]] = []
    for area in areas:
        summary = area.get("summary") or "_No notable changes this cycle._"
        attachments.append({
            "color": area.get("color", "#cccccc"),
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": f"*{area['name']}*\n{summary}"}}],
        })

    elements = _briefing_action_elements(report_url, control_url)
    if elements:
        # A colorless trailing attachment keeps the buttons below every area card.
        attachments.append({"blocks": [{"type": "actions", "elements": elements}]})

    return {"text": f"SPP Market Changes — {date_label}", "blocks": blocks, "attachments": attachments}


def send_slack_briefing_by_area(
    date_label: str,
    areas: list[dict[str, Any]],
    *,
    sources_line: str = "",
    report_url: str = "",
    control_url: str = "",
    webhook_url: str = "",
    bot_token: str = "",
    channel: str = "",
) -> bool:
    """Post the by-area briefing; same delivery rules; never raises."""
    payload = format_briefing_by_area(date_label, areas, sources_line=sources_line,
                                      report_url=report_url, control_url=control_url)
    return _deliver(payload, webhook_url=webhook_url, bot_token=bot_token, channel=channel, what="by-area briefing")


def format_rr_control_message(
    date_label: str,
    watched_total: int,
    class_counts: list[tuple[str, int]],
    *,
    changes: list[dict[str, Any]] | None = None,
    control_url: str = "",
) -> dict[str, Any]:
    """The RR Control register summary with a "what changed" delta.

    ``class_counts`` is ``[(label, count), …]`` (already human-labeled, e.g.
    ("settlement calc", 5)); the header reads "Tracking N open RRs (5 settlement
    calc · …)". ``changes`` is the delta ([{kind, text}]); the delta section is
    shown only when non-empty — the no-change case is carried by the run
    heartbeat, and the standalone dashboard refresh just states the register.
    """
    breakdown = " · ".join(f"{count} {label}" for label, count in class_counts if count)
    tail = f" ({breakdown})" if breakdown else ""
    body = (f":ledger: *SPP Settlement Changes Control — {date_label}*\n"
            f"Tracking *{watched_total}* open RR{'' if watched_total == 1 else 's'}{tail}.")
    blocks: list[dict[str, Any]] = [{"type": "section", "text": {"type": "mrkdwn", "text": body}}]
    if changes:
        lines = ["*What changed since the last update:*"] + format_delta_lines(changes)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
    if control_url:
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "style": "primary",
             "text": {"type": "plain_text", "text": "Open the control dashboard", "emoji": True},
             "url": control_url}]})
    return {"text": f"SPP Settlement Changes Control — {date_label}", "blocks": blocks}


def send_slack_rr_control(
    date_label: str,
    watched_total: int,
    class_counts: list[tuple[str, int]],
    *,
    changes: list[dict[str, Any]] | None = None,
    control_url: str = "",
    webhook_url: str = "",
    bot_token: str = "",
    channel: str = "",
) -> bool:
    """Post the RR Control register summary; same delivery rules; never raises."""
    payload = format_rr_control_message(date_label, watched_total, class_counts,
                                        changes=changes, control_url=control_url)
    return _deliver(payload, webhook_url=webhook_url, bot_token=bot_token, channel=channel, what="RR control")
