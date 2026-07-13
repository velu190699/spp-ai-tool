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


_SAMPLE_RR = {
    "rr_number": "728",
    "title": "DAMKT VER Participation (HITT M2)",
    "primary_working_group": "MWG",
    "dates": ["June 6 2026"],
    "search_url": "https://www.spp.org/search?q=rr728",
}


def _section_text(payload) -> str:
    return "\n".join(
        b["text"]["text"] for b in payload["blocks"] if b.get("type") == "section"
    )


def test_format_report_link_message_omits_rr_section_by_default():
    # Backward compatible: no relevant_rrs arg -> just the title/link section.
    payload = format_report_link_message("Title", "https://sp/link")
    assert len(payload["blocks"]) == 1
    assert all(b.get("type") != "divider" for b in payload["blocks"])


def test_format_report_link_message_includes_relevant_rrs():
    payload = format_report_link_message("Title", "https://sp/link", [_SAMPLE_RR])
    # The link section is still first; a divider separates it from the RR list.
    assert "*Title*" in payload["blocks"][0]["text"]["text"]
    assert {"type": "divider"} in payload["blocks"]
    text = _section_text(payload)
    assert "Relevant open RRs (1)" in text
    assert "<https://www.spp.org/search?q=rr728|RR728>" in text
    assert "DAMKT VER Participation (HITT M2)" in text
    assert "MWG" in text
    assert "June 6 2026" in text


def test_format_report_link_message_empty_relevant_rrs():
    # An empty (but not None) list still renders the section, marked as empty.
    payload = format_report_link_message("Title", "https://sp/link", [])
    text = _section_text(payload)
    assert "Relevant open RRs (0)" in text
    assert "None identified" in text


def test_send_slack_report_link_includes_rrs_in_payload():
    response = MagicMock()
    response.json.return_value = {"ok": True}
    with patch("src.notifications.notifier.requests.post", return_value=response) as post:
        assert send_slack_report_link(
            "Title", "https://sp/link", bot_token="xoxb-1", channel="#c", relevant_rrs=[_SAMPLE_RR]
        ) is True
        _, kwargs = post.call_args
        blocks = kwargs["json"]["blocks"]
        text = "\n".join(b["text"]["text"] for b in blocks if b.get("type") == "section")
        assert "<https://www.spp.org/search?q=rr728|RR728>" in text


def test_relevant_rr_blocks_split_under_slack_limit():
    from src.notifications.notifier import _relevant_rr_blocks, _SLACK_SECTION_TEXT_LIMIT

    # A long RR list must fan out across multiple section blocks, each within
    # Slack's per-text limit, rather than one oversized (rejected) block.
    rrs = [
        {"rr_number": str(n), "title": "T" * 120, "search_url": "https://sp/x"}
        for n in range(200)
    ]
    blocks = _relevant_rr_blocks(rrs)
    assert len(blocks) >= 2
    for block in blocks:
        assert len(block["text"]["text"]) <= _SLACK_SECTION_TEXT_LIMIT


def test_relevant_rr_blocks_truncates_single_over_long_line():
    from src.notifications.notifier import _relevant_rr_blocks, _SLACK_SECTION_TEXT_LIMIT

    # A single pathologically long RR line must be truncated so its block stays
    # within Slack's limit (otherwise chat.postMessage rejects invalid_blocks).
    rrs = [{"rr_number": "123", "title": "A" * 5000, "search_url": "https://sp/rr123"}]
    blocks = _relevant_rr_blocks(rrs)
    for block in blocks:
        assert len(block["text"]["text"]) <= _SLACK_SECTION_TEXT_LIMIT


def test_format_report_link_message_note_overrides_link_line():
    # A build failure must NOT render the success-looking "published locally"
    # line; the note surfaces the real status instead.
    payload = format_report_link_message(
        "Title", "", note="Report generation failed; see the run log for details."
    )
    body = payload["blocks"][0]["text"]["text"]
    assert "Report generation failed" in body
    assert "published locally" not in body
    assert "Report generation failed" in payload["text"]
