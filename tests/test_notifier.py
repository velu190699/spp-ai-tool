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

def test_send_slack_failure_posts_via_webhook_and_truncates():
    response = MagicMock()
    with patch("src.notifications.notifier.requests.post", return_value=response) as post:
        from src.notifications.notifier import send_slack_failure

        assert send_slack_failure("run", "RuntimeError: " + "x" * 600, webhook_url="https://hooks.slack/x") is True
        payload = post.call_args.kwargs["json"]
        assert "SPP tool FAILED at run" in payload["text"]
        assert len(payload["text"]) < 600  # long tracebacks are truncated
        assert ":rotating_light:" in payload["blocks"][0]["text"]["text"]


def test_send_slack_failure_skips_when_unconfigured():
    with patch("src.notifications.notifier.requests.post") as post:
        from src.notifications.notifier import send_slack_failure

        assert send_slack_failure("report", "boom") is False
        post.assert_not_called()


def test_format_story_drafts_message_lists_per_rr_templates_with_delta():
    from src.notifications.notifier import format_story_drafts_message

    payload = format_story_drafts_message(
        [("RR728", "https://sp/RR728_stories.xlsx"), ("RR623", "https://sp/RR623_stories.xlsx")],
        date_label="July 22, 2026",
        changes=[{"kind": "new", "text": "*RR728* first draft."}],
    )
    body = payload["blocks"][0]["text"]["text"]
    assert "SPP RR story drafts — July 22, 2026" in body
    assert "2 RR story templates ready for PM review" in body
    # The standalone settlement-report link was dropped from this message.
    assert "settlement report in SharePoint" not in body
    assert {"type": "divider"} in payload["blocks"]
    text = _section_text(payload)
    assert "New/updated this run:" in text and "RR728" in text
    assert "Story templates:" in text
    assert "<https://sp/RR728_stories.xlsx|RR728 story template>" in text
    assert "<https://sp/RR623_stories.xlsx|RR623 story template>" in text
    assert "RR728, RR623" in payload["text"]  # fallback names the RRs


def test_format_story_drafts_message_handles_missing_links_and_no_delta():
    from src.notifications.notifier import format_story_drafts_message

    payload = format_story_drafts_message([("RR728", "")], date_label="July 22, 2026")
    text = _section_text(payload)
    assert "1 RR story template ready" in payload["blocks"][0]["text"]["text"]  # singular
    assert "New/updated this run:" not in text                # no delta section when empty
    assert "RR728 story template (no link)" in text           # per-RR link absent


def test_send_slack_story_drafts_posts_via_bot():
    from src.notifications.notifier import send_slack_story_drafts

    response = MagicMock()
    response.json.return_value = {"ok": True}
    with patch("src.notifications.notifier.requests.post", return_value=response) as post:
        assert send_slack_story_drafts(
            [("RR728", "https://sp/rr728")], date_label="July 22, 2026",
            bot_token="xoxb-1", channel="#c",
        ) is True
        _, kwargs = post.call_args
        text = "\n".join(b["text"]["text"] for b in kwargs["json"]["blocks"] if b.get("type") == "section")
        assert "RR728 story template" in text


def test_format_heartbeat_message():
    from src.notifications.notifier import format_heartbeat_message

    payload = format_heartbeat_message("July 22, 2026", 9, "https://sp/control")
    body = payload["blocks"][0]["text"]["text"]
    assert "SPP weekly check — July 22, 2026" in body
    assert "Watching *9* open settlement RRs" in body
    assert "no changes" in payload["text"]
    ctx = payload["blocks"][1]["elements"][0]["text"]
    assert "<https://sp/control|Open the RR Control dashboard>" in ctx


def test_format_briefing_by_area_uses_colored_cards_and_bottom_buttons():
    from src.notifications.notifier import format_briefing_by_area

    areas = [
        {"name": "RTO Markets", "color": "#1f4e8c", "summary": "Fall bundle coming."},
        {"name": "ETRM", "color": "#6b3fa0", "summary": ""},  # empty -> degrades
    ]
    payload = format_briefing_by_area(
        "July 22, 2026", areas, sources_line="CUF Jul · SUF Apr",
        report_url="https://sp/report", control_url="https://sp/control",
    )
    # header + intro in top-level blocks; area cards + a trailing action attachment.
    assert payload["blocks"][0]["type"] == "header"
    assert [a["color"] for a in payload["attachments"] if "color" in a] == ["#1f4e8c", "#6b3fa0"]
    assert "RTO Markets" in payload["attachments"][0]["blocks"][0]["text"]["text"]
    assert "No notable changes" in payload["attachments"][1]["blocks"][0]["text"]["text"]
    # Buttons live in the LAST attachment so they render below every card.
    last = payload["attachments"][-1]
    assert "color" not in last and last["blocks"][0]["type"] == "actions"
    labels = [e["text"]["text"] for e in last["blocks"][0]["elements"]]
    assert labels == ["Open full report", "RR Control dashboard"]


def test_format_rr_control_message_with_and_without_delta():
    from src.notifications.notifier import format_rr_control_message

    with_delta = format_rr_control_message(
        "July 22, 2026", 9, [("settlement calc", 5), ("tariff / governance", 3), ("unused", 0)],
        changes=[{"kind": "new", "text": "*RR786* added."},
                 {"kind": "updated", "text": "*RR728* re-published."}],
        control_url="https://sp/control",
    )
    body = with_delta["blocks"][0]["text"]["text"]
    assert "Tracking *9* open RRs (5 settlement calc · 3 tariff / governance)" in body
    assert "0 unused" not in body  # zero-count classes are dropped
    text = _section_text(with_delta)
    assert "What changed since the last update:" in text and "RR786" in text
    assert with_delta["blocks"][-1]["elements"][0]["url"] == "https://sp/control"

    # With no delta, only the register line (and button if any) — no delta section.
    empty = format_rr_control_message("July 22, 2026", 9, [("settlement calc", 9)])
    assert "What changed" not in _section_text(empty)
    assert len(empty["blocks"]) == 1  # just the register summary


def test_relevant_rr_line_marks_updated_rrs():
    from src.notifications.notifier import _relevant_rr_line

    plain = _relevant_rr_line({"rr_number": "728", "title": "RUC MWP"})
    assert "UPDATED" not in plain
    updated = _relevant_rr_line({"rr_number": "728", "title": "RUC MWP", "updated": True})
    assert "*UPDATED*" in updated and "RR728" in updated
