from pathlib import Path

from src.documents.rr_extractor import initiative_from_contexts
from src.summaries.report_builder import build_area_guide


def test_initiative_is_verbatim_with_citation():
    contexts = ["RR728 is part of the Fall 2026 Market Initiative go-live"]
    sources = ["(07) Settlement Releases - CUF July 2026.pdf:p6"]
    label, cite = initiative_from_contexts(contexts, sources)
    assert label == "Fall 2026 Market Initiative"  # verbatim slide wording
    assert cite == "(07) Settlement Releases - CUF July 2026.pdf:p6"


def test_initiative_from_real_spp_phrasing_verbatim():
    # Verbatim phrasing observed in the July 2026 CUF/SUF decks.
    bundle = "6 2026 Settlements Fall Bundle This release includes RR728 DAMKT VER Participation"
    label, _ = initiative_from_contexts([bundle])
    assert label == "2026 Settlements Fall Bundle"  # the slide's own words
    release = "items for our next Integrated Marketplace release in Fall 2026 . This is the current list"
    label, _ = initiative_from_contexts([release])
    assert label == "release in Fall 2026"
    hitt_only = "TRANSMISSION HITT C1 EFFORT RR665 establishes a Sub-Regional Cost Allocation"
    label, _ = initiative_from_contexts([hitt_only])
    assert label == "HITT C1"


def test_initiative_preference_order_and_absence():
    bundle = "2026 Settlements Fall Bundle includes RR728"
    explicit = "scope of Fall 2026 Market Initiative includes RR728"
    hitt = "RR728 DAMKT VER Participation (HITT M2)"
    # Explicit "Market Initiative" wording outranks bundle/release phrasing;
    # both outrank a bare HITT code.
    label, _ = initiative_from_contexts([bundle, explicit, hitt])
    assert label == "Fall 2026 Market Initiative"
    label, _ = initiative_from_contexts([bundle, hitt])
    assert label == "2026 Settlements Fall Bundle"
    # A bare "market initiative" without season+year identifies nothing.
    assert initiative_from_contexts(["part of a future market initiative"]) == ("", "")
    assert initiative_from_contexts([]) == ("", "")
    assert initiative_from_contexts(None) == ("", "")


def test_initiative_citations_pair_with_contexts():
    contexts = ["no initiative here", "2026 Settlements Fall Bundle includes RR728"]
    sources = ["a.pdf:p1", "b.pdf:p6"]
    label, cite = initiative_from_contexts(contexts, sources)
    assert label == "2026 Settlements Fall Bundle"
    assert cite == "b.pdf:p6"  # the source of the MATCHING context, not the first


def test_area_guide_reads_repo_routing_yaml():
    guide = build_area_guide(Path("config/area_routing.yaml"))
    # The two SME corrections from the 2026-07 feedback meeting must be present.
    assert "WEIS / SPP West wind-down" in guide
    assert "BOTH ETRM and RTO Markets" in guide
    # All five areas are still listed for the router.
    for key in ("rto_markets", "asset_operations", "transmissions", "etrm", "optimization"):
        assert key in guide


def test_area_guide_falls_back_when_file_missing(tmp_path):
    guide = build_area_guide(tmp_path / "does-not-exist.yaml")
    assert "Area routing hints:" in guide
    assert "rto_markets" in guide


def test_area_guide_survives_broken_yaml(tmp_path):
    bad = tmp_path / "broken.yaml"
    bad.write_text("areas: [unclosed", encoding="utf-8")
    guide = build_area_guide(bad)  # must not raise — the weekly report depends on it
    assert "Area routing hints:" in guide


def test_latest_rr_docx_prefers_newest_revision(tmp_path):
    from main import _latest_rr_docx_files

    rr = tmp_path / "rr773"
    rr.mkdir()
    (rr / "RR773 Recommendation Report.docx").write_bytes(b"v1")
    (rr / "RR773 Recommendation Report.rev-20260714.docx").write_bytes(b"v2")
    other = tmp_path / "rr623"
    other.mkdir()
    (other / "RR623 Recommendation Report.docx").write_bytes(b"v1")

    files = _latest_rr_docx_files(tmp_path)
    names = [f.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for f in files]
    assert "RR773 Recommendation Report.rev-20260714.docx" in names
    assert "RR773 Recommendation Report.docx" not in names  # superseded
    assert "RR623 Recommendation Report.docx" in names  # no revisions -> original
