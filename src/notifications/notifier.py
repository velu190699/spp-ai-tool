from __future__ import annotations

import logging
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)

# Slack rejects Incoming Webhook payloads that take too long; keep it short.
_SLACK_TIMEOUT_SECONDS = 10
_SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


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


def format_report_link_message(report_title: str, report_url: str) -> dict[str, Any]:
    """Build the Slack Incoming Webhook payload announcing a published report.

    The message uses Block Kit so the SharePoint link renders as a labeled,
    clickable line rather than a bare URL. ``text`` is the notification/preview
    fallback used in banners and screen readers.
    """
    if report_url:
        body = f"*{report_title}*\n<{report_url}|Open the report in SharePoint>"
        fallback = f"{report_title} — {report_url}"
    else:
        # No SharePoint URL resolved (e.g. report published outside the synced
        # library); still announce it so the channel isn't left silent.
        body = f"*{report_title}*\n_Report published locally; no SharePoint link available._"
        fallback = f"{report_title} (no SharePoint link available)"
    return {
        "text": fallback,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": body}}],
    }


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
) -> bool:
    """Post the published report link to a Slack channel.

    Uses ``chat.postMessage`` when a bot token and channel are provided, else an
    Incoming Webhook. Returns True on success. Never raises: a Slack failure must
    not sink an otherwise-successful report run, so problems are logged only.
    """
    payload = format_report_link_message(report_title, report_url)

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
