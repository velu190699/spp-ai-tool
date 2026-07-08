from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from src.notifications.notifier import format_report_link_message, send_slack_report_link


def test_format_report_link_message_with_url():
    payload = format_report_link_message("Report Title", "https://sp/link?web=1")
    assert payload["text"] == "Report Title — https://sp/link?web=1"
    block_text = payload["blocks"][0]["text"]["text"]
    assert "*Report Title*" in block_text
    assert "<https://sp/link?web=1|Open the report in SharePoint>" in block_text


def test_format_report_link_message_without_url():
    payload = format_report_link_message("Report Title", "")
    assert payload["text"] == "Report Title (no SharePoint link available)"
    assert "no SharePoint link available" in payload["blocks"][0]["text"]["text"]


def test_send_slack_report_link_skips_when_nothing_configured():
    with patch("src.notifications.notifier.requests.post") as post:
        assert send_slack_report_link("Title", "https://sp/link") is False
        post.assert_not_called()


def test_send_slack_report_link_posts_via_webhook():
    response = MagicMock()
    with patch("src.notifications.notifier.requests.post", return_value=response) as post:
        assert send_slack_report_link("Title", "https://sp/link", webhook_url="https://hooks.slack/x") is True
        post.assert_called_once()
        args, kwargs = post.call_args
        assert args[0] == "https://hooks.slack/x"
        assert kwargs["json"]["text"] == "Title — https://sp/link"
        response.raise_for_status.assert_called_once()


def test_send_slack_report_link_prefers_bot_token():
    response = MagicMock()
    response.json.return_value = {"ok": True}
    with patch("src.notifications.notifier.requests.post", return_value=response) as post:
        assert send_slack_report_link(
            "Title",
            "https://sp/link",
            webhook_url="https://hooks.slack/x",
            bot_token="xoxb-123",
            channel="#market-updates",
        ) is True
        args, kwargs = post.call_args
        assert args[0] == "https://slack.com/api/chat.postMessage"
        assert kwargs["headers"]["Authorization"] == "Bearer xoxb-123"
        assert kwargs["json"]["channel"] == "#market-updates"
        assert kwargs["json"]["text"] == "Title — https://sp/link"


def test_send_slack_report_link_bot_reports_logical_failure():
    response = MagicMock()
    response.json.return_value = {"ok": False, "error": "not_in_channel"}
    with patch("src.notifications.notifier.requests.post", return_value=response):
        # HTTP 200 but ok=false must be treated as a failure.
        assert send_slack_report_link("Title", "https://sp/link", bot_token="xoxb-1", channel="#c") is False


def test_send_slack_report_link_swallows_errors():
    with patch("src.notifications.notifier.requests.post", side_effect=requests.RequestException("boom")):
        # A Slack failure must not raise — the report run already succeeded.
        assert send_slack_report_link("Title", "https://sp/link", webhook_url="https://hooks.slack/x") is False
