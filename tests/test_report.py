import pytest

from src.summaries.html_renderer import render_report
from src.summaries.report_builder import DocumentText, build_context, build_report
from src.summaries.report_engine import StubEngine, _extract_json, build_engine
from src.summaries.report_model import ReportData, ReportValidationError


def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_strips_fences():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_finds_embedded_object():
    assert _extract_json('Here you go:\n{"a": 1}\nThanks') == {"a": 1}


def test_build_engine_stub():
    engine = build_engine("stub")
    assert isinstance(engine, StubEngine)


def test_build_engine_unknown():
    with pytest.raises(Exception):
        build_engine("nope")


def test_report_model_rejects_unknown_area():
    with pytest.raises(ReportValidationError):
        ReportData.from_dict({"areas": [{"key": "not_a_real_area"}]})


def test_report_model_fills_all_areas_from_stub():
    engine = StubEngine()
    report = ReportData.from_dict(engine.generate("i", "c"))
    keys = {a.key for a in report.areas}
    assert "rto_markets" in keys
    assert len(report.narrative) >= 1


def test_build_context_flags_unreadable_files():
    docs = [
        DocumentText(kind="CUF", filename="readable.pdf", sharepoint_url="u1", text="Some content here."),
        DocumentText(kind="CUF", filename="scan.pdf", sharepoint_url="u2", text="", readable=False),
    ]
    context = build_context(cuf_label="C", suf_label="S", documents=docs, relevant_rrs=[])
    assert "NOT READABLE" in context
    assert "scan.pdf" in context
    assert "Some content here." in context


def test_build_report_end_to_end_with_stub():
    report = build_report(
        engine=StubEngine(),
        cuf_label="CUF X (June 18, 2026)",
        suf_label="SUF Y (April 9, 2026)",
        documents=[DocumentText(kind="CUF", filename="a.pdf", sharepoint_url="u", text="text")],
        relevant_rrs=[],
        generated="July 1, 2026",
    )
    assert report.meta.generated == "July 1, 2026"
    html = render_report(report)
    assert "<!DOCTYPE html>" in html
    assert "SPP Market Changes Summary" in html
    assert "Executive Overview" in html
    assert "Full Summary" in html
    # All five area cards render.
    for code in ("g-ms", "g-ao", "g-tx", "g-et", "g-op"):
        assert code in html
    # Clean UTF-8, no mojibake artifacts from the sample.
    assert "Â·" not in html


def test_header_links_cuf_folder_and_suf_pdf():
    report = build_report(
        engine=StubEngine(),
        cuf_label="CUF X (June 18, 2026)",
        suf_label="SUF Y (April 9, 2026)",
        documents=[DocumentText(kind="CUF", filename="a.pdf", sharepoint_url="u", text="text")],
        relevant_rrs=[],
        generated="July 1, 2026",
        cuf_url="https://sp/CUF%20folder",
        suf_url="https://sp/SUF%20file.pdf",
    )
    # Engine-supplied edition links are overwritten by the deterministic ones.
    assert report.meta.cuf_url == "https://sp/CUF%20folder"
    assert report.meta.suf_url == "https://sp/SUF%20file.pdf"
    html = render_report(report)
    assert '<a href="https://sp/CUF%20folder">CUF' in html
    assert '<a href="https://sp/SUF%20file.pdf">SUF' in html


def test_header_falls_back_to_plain_sources_without_urls():
    report = build_report(
        engine=StubEngine(),
        cuf_label="CUF X (June 18, 2026)",
        suf_label="SUF Y (April 9, 2026)",
        documents=[DocumentText(kind="CUF", filename="a.pdf", sharepoint_url="u", text="text")],
        relevant_rrs=[],
        generated="July 1, 2026",
    )
    assert report.meta.cuf_url == ""
    html = render_report(report)
    # No edition anchors when URLs are unavailable; sources_line still shows.
    assert 'href="https://sp' not in html
