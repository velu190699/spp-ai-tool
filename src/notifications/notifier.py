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
