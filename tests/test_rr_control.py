"""RR Control dashboard builder + renderer (src/summaries/rr_control.py)."""
from src.summaries.rr_control import build_rr_control_rows, render_rr_control, summarize


def _watched(**kw):
    base = {"rr_number": "728", "title": "RUC MWP", "status": "open", "last_seen": "2026-07-22T10:00:00+00:00"}
    base.update(kw)
    return base


def test_rows_carry_class_initiative_status_and_history():
    watched = [_watched(
        market_initiative="2026 Settlements Fall Bundle",
        market_initiative_citation="CUF July.pdf:p6",
        primary_working_group="MWG", domain="BO",
        mentions_seen=[
            {"kind": "CUF", "label": "July", "meeting_date": "2026-07-16", "initiative": "2026 Settlements Fall Bundle"},
            {"kind": "CUF", "label": "June", "meeting_date": "2026-06-18", "initiative": "2026 Settlements Fall Bundle"},
        ],
    )]
    rows = build_rr_control_rows(watched, class_of=lambda rr: "SETTLEMENT_CALC")
    assert len(rows) == 1
    r = rows[0]
    assert r["rr_class"] == "SETTLEMENT_CALC"
    assert r["class_label"] == "Settlement calc" and r["class_code"] == "sc"
    assert r["market_initiative"] == "2026 Settlements Fall Bundle"
    assert r["last_updated"] == "2026-07-22"
    # History is sorted oldest -> newest so the timeline reads down the page.
    assert [m["date"] for m in r["mentions"]] == ["2026-06-18", "2026-07-16"]


def test_class_falls_back_to_stored_then_unclassified():
    # No resolver: use the stored rr_class if present, else Unclassified.
    rows = build_rr_control_rows([_watched(rr_class="TARIFF_GOVERNANCE"), _watched(rr_number="999", title="")])
    by_num = {r["rr_number"]: r for r in rows}
    assert by_num["728"]["class_label"] == "Tariff / governance"
    assert by_num["999"]["class_label"] == "Unclassified"
    assert by_num["999"]["title"] == "(title not captured)"


def test_open_rrs_sort_above_closed():
    watched = [
        _watched(rr_number="700", status="closed", last_seen="2026-07-22T10:00:00+00:00"),
        _watched(rr_number="728", status="open", last_seen="2026-07-20T10:00:00+00:00"),
    ]
    rows = build_rr_control_rows(watched)
    assert [r["rr_number"] for r in rows] == ["728", "700"]  # open first, despite older date


def test_summarize_counts():
    watched = [
        _watched(rr_number="728", status="open", rr_class="SETTLEMENT_CALC", market_initiative="Bundle"),
        _watched(rr_number="786", status="closed", rr_class="TARIFF_GOVERNANCE"),
    ]
    rows = build_rr_control_rows(watched, story_url_of=lambda rr: "http://x" if rr == "728" else "")
    stats = summarize(rows)
    assert stats == {"total": 2, "open": 1, "closed": 1, "settlement_calc": 1, "with_initiative": 1, "with_story": 1}


def test_render_is_self_contained_html_with_rows():
    rows = build_rr_control_rows([_watched(market_initiative="Fall 2026 Bundle")], class_of=lambda rr: "SETTLEMENT_CALC")
    html = render_rr_control(rows, {"title": "SPPIM Settlement Changes Control", "generated": "July 22, 2026", "market": "SPPIM"})
    assert html.startswith("<!DOCTYPE html>")
    assert "SPPIM Settlement Changes Control" in html  # title comes from meta
    assert "RR728" in html and "Fall 2026 Bundle" in html
    assert "Settlement calc" in html


def test_settlement_relevant_label_is_reworded():
    rows = build_rr_control_rows([_watched(rr_class="SETTLEMENT_RELEVANT")])
    assert rows[0]["class_label"] == "Settlement review"


def test_candidate_hint_shown_only_when_no_initiative():
    # No official initiative, but a nearby effort was captured -> shown as a hint.
    watched = [_watched(market_initiative="", mentions_seen=[
        {"kind": "SUF", "meeting_date": "2026-04-09", "initiative": "", "candidate": "RTO Expansion Project"},
    ])]
    rows = build_rr_control_rows(watched)
    assert rows[0]["initiative_hint"] == "RTO Expansion Project"
    html = render_rr_control(rows, {"title": "T", "generated": "x", "market": "SPPIM"})
    assert "nearby: RTO Expansion Project" in html
    # When an official initiative IS named, no hint leaks out.
    rows2 = build_rr_control_rows([_watched(market_initiative="Fall 2026 Bundle", mentions_seen=[
        {"kind": "CUF", "meeting_date": "2026-06-18", "initiative": "Fall 2026 Bundle", "candidate": ""},
    ])])
    assert rows2[0]["initiative_hint"] == ""


def test_render_empty_state():
    html = render_rr_control([], {"title": "T", "generated": "July 22, 2026", "market": "SPPIM"})
    assert "No RRs are being watched yet" in html
