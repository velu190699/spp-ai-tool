"""RR Control dashboard builder + renderer (src/summaries/rr_control.py)."""
from src.summaries.rr_control import build_rr_control_rows, render_rr_control, summarize


def _watched(**kw):
    base = {"rr_number": "728", "title": "RUC MWP", "status": "open", "last_seen": "2026-07-22T10:00:00+00:00"}
    base.update(kw)
    return base


def test_rows_carry_class_initiative_status_and_history():
    watched = [_watched(
        rr_class="SETTLEMENT_CALC", determinants=["#RtA", "#RtB"], mp_impact=True,
        market_initiative="2026 Settlements Fall Bundle",
        market_initiative_citation="CUF July.pdf:p6",
        primary_working_group="MWG", domain="BO",
        mentions_seen=[
            {"kind": "CUF", "label": "July", "meeting_date": "2026-07-16", "initiative": "2026 Settlements Fall Bundle"},
            {"kind": "CUF", "label": "June", "meeting_date": "2026-06-18", "initiative": "2026 Settlements Fall Bundle"},
        ],
    )]
    rows = build_rr_control_rows(watched)
    assert len(rows) == 1
    r = rows[0]
    assert r["rr_class"] == "SETTLEMENT_CALC"
    assert r["class_label"] == "Settlement calc" and r["class_code"] == "sc"
    assert r["det_count"] == 2 and r["determinants"] == ["#RtA", "#RtB"]
    assert r["out_of_scope"] is False
    assert r["market_initiative"] == "2026 Settlements Fall Bundle"
    assert r["last_updated"] == "2026-07-22"
    # History is sorted oldest -> newest so the timeline reads down the page.
    assert [m["date"] for m in r["mentions"]] == ["2026-06-18", "2026-07-16"]


def test_out_of_scope_flag_for_non_mp_rr():
    # RR773: classified but doesn't touch Market Protocols -> out of settlement scope.
    rows = build_rr_control_rows([_watched(rr_class="SETTLEMENT_RELEVANT", mp_impact=False)])
    assert rows[0]["out_of_scope"] is True
    # A not-yet-classified RR (mp_impact None) is NOT flagged out of scope.
    rows2 = build_rr_control_rows([_watched(rr_class="", mp_impact=None)])
    assert rows2[0]["out_of_scope"] is False
    # Determinants render as code chips in the expanded row.
    rows3 = build_rr_control_rows([_watched(rr_class="SETTLEMENT_CALC", determinants=["#RtCalMtr5minQty"], mp_impact=True)])
    html = render_rr_control(rows3, {"title": "T", "generated": "x", "market": "SPPIM"})
    assert "#RtCalMtr5minQty" in html and "charge code" in html


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
    # Two tabs: the Control register and the Determinants breakdown.
    assert 'id="tab-control"' in html and 'id="tab-dets"' in html
    assert 'id="panel-dets"' in html


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


def test_determinants_tab_table_with_before_after_and_pages():
    changes = [
        {"determinant": "#RtMwpDistHrlyAmt", "section": "2.7.10", "change_status": "MODIFIED",
         "formula_before": "#RtMwpDistHrlyAmt = RtMwpSppDistRate * RtDevHrlyQty",
         "formula_after": "#RtMwpDistHrlyAmt = RtMwpBaaDistRate * (RtDevHrlyQty + RtDcTieMwpDistAdjHrlyQty)",
         "page": 16},
    ]
    rows = build_rr_control_rows(
        [_watched(rr_class="SETTLEMENT_CALC", determinants=["#RtMwpDistHrlyAmt"], mp_impact=True)],
        changes_of=lambda rr: changes,
    )
    assert rows[0]["changes"] == changes
    html = render_rr_control(rows, {"title": "T", "generated": "x", "market": "SPPIM"})
    # Before/after formula columns + markup-view page.
    assert "Formula before" in html and "Formula after" in html
    assert "RtMwpSppDistRate" in html and "RtMwpBaaDistRate" in html
    assert "p.16" in html


def test_determinants_tab_falls_back_to_codes_without_a_story():
    rows = build_rr_control_rows(
        [_watched(rr_class="SETTLEMENT_CALC", determinants=["#RtCalMtr5minQty"], mp_impact=True)]
    )  # no items_of -> no story items
    html = render_rr_control(rows, {"title": "T", "generated": "x", "market": "SPPIM"})
    assert "#RtCalMtr5minQty" in html
    assert "after a settlement-report run" in html


def test_render_empty_state():
    html = render_rr_control([], {"title": "T", "generated": "July 22, 2026", "market": "SPPIM"})
    assert "No RRs are being watched yet" in html
