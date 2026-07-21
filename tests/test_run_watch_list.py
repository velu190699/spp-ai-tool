"""Option B: run()'s watch-list seeding/refresh (`_refresh_watch_list`) and
initiative accumulation across CUF/SUF editions."""
from types import SimpleNamespace

import main
from main import (
    _enrich_relevant_from_watch_list,
    _refresh_watch_list,
    accumulate_watch_list_initiatives,
)
from src.documents.pdf_parser import PdfParseResult
from src.documents.rr_extractor import RRMention
from src.state.metadata_store import MetadataStore


def test_seeds_from_cross_reference_and_fetches_open_rrs(tmp_path):
    store = MetadataStore(tmp_path / "m.json")
    relevant = [
        {"rr_number": "728", "title": "RUC MWP", "market_initiative": "Fall 2026 Bundle",
         "search_url": "https://spp.org/?q=rr728", "primary_working_group": "MWG"},
        {"rr_number": "750", "title": "MSR", "market_initiative": "", "search_url": ""},
    ]
    open_rrs = {"728": object(), "750": object()}  # both open in the master list

    download = _refresh_watch_list(store, relevant, open_rrs)
    assert sorted(r["rr_number"] for r in download) == ["728", "750"]
    assert store.get_watched("728")["market_initiative"] == "Fall 2026 Bundle"
    assert store.get_watched("728")["domain"] == "BO"


def test_watched_open_rr_still_fetched_when_not_in_latest_cross_reference(tmp_path):
    # The point of Option B: RR728 was relevant once, then a newer CUF/SUF stops
    # mentioning it — but it's still OPEN, so it stays watched and is refetched
    # (catching a late revision), and its initiative is preserved.
    store = MetadataStore(tmp_path / "m.json")
    _refresh_watch_list(store, [{"rr_number": "728", "market_initiative": "Fall 2026 Bundle"}],
                        {"728": object()})
    download = _refresh_watch_list(store, [], {"728": object()})  # no longer cross-referenced, still open
    assert [r["rr_number"] for r in download] == ["728"]
    assert store.get_watched("728")["market_initiative"] == "Fall 2026 Bundle"


def test_closed_rr_drops_out_of_the_fetch_set(tmp_path):
    store = MetadataStore(tmp_path / "m.json")
    _refresh_watch_list(store, [{"rr_number": "728"}, {"rr_number": "750"}],
                        {"728": object(), "750": object()})
    download = _refresh_watch_list(store, [], {"750": object()})  # 728 gone from master -> closed
    assert [r["rr_number"] for r in download] == ["750"]
    assert store.get_watched("728")["status"] == "closed"


def _mk_config(tmp_path):
    cuf_dir = tmp_path / "CUF"
    suf_dir = tmp_path / "SUF"
    cuf_dir.mkdir()
    suf_dir.mkdir()
    return SimpleNamespace(
        cuf_dir=cuf_dir, suf_dir=suf_dir,
        sharepoint_sync_root=tmp_path, sharepoint_base_url="https://x/base",
    )


def test_accumulation_recovers_initiative_named_only_in_an_older_edition(tmp_path, monkeypatch):
    # RR750's symptom: its initiative was named in an OLDER CUF edition than the
    # one run() parses for relevance, so it shows blank. Accumulation walks all
    # editions and recovers it.
    config = _mk_config(tmp_path)
    older = config.cuf_dir / "CUF Meeting Materials 20260521_20260515"
    newer = config.cuf_dir / "CUF Meeting Materials 20260716_20260710"
    for folder in (older, newer):
        folder.mkdir()
        (folder / "releases.pdf").write_text("x", encoding="utf-8")

    def fake_parse(path):
        # Only the OLDER edition names RR750's initiative; the newer one is silent.
        if "20260521" in str(path):
            ctx = "RR750 is part of the 2026 Settlements Fall Bundle scheduled for release."
            return PdfParseResult(path=path, text=ctx,
                                  rr_mentions=[RRMention(rr_number="750", context=ctx, source=path.name, page=6)])
        return PdfParseResult(path=path, text="RR728 only here", rr_mentions=[])

    monkeypatch.setattr(main, "parse_pdf", fake_parse)

    store = MetadataStore(tmp_path / "m.json")
    store.upsert_watched("750", {"title": "MSR", "market_initiative": "", "status": "open"})
    warnings: list[str] = []
    accumulate_watch_list_initiatives(store, config, warnings)

    watched = store.get_watched("750")
    assert watched["market_initiative"] == "2026 Settlements Fall Bundle"
    assert watched["mentions_seen"]  # history recorded
    # Both editions are marked parsed so a second run doesn't re-parse them.
    assert store.is_edition_parsed("CUF|CUF Meeting Materials 20260521_20260515")
    assert store.is_edition_parsed("CUF|CUF Meeting Materials 20260716_20260710")


def test_accumulation_parses_each_edition_only_once(tmp_path, monkeypatch):
    config = _mk_config(tmp_path)
    folder = config.cuf_dir / "CUF Meeting Materials 20260521_20260515"
    folder.mkdir()
    (folder / "releases.pdf").write_text("x", encoding="utf-8")

    calls = {"n": 0}

    def fake_parse(path):
        calls["n"] += 1
        return PdfParseResult(path=path, text="", rr_mentions=[])

    monkeypatch.setattr(main, "parse_pdf", fake_parse)
    store = MetadataStore(tmp_path / "m.json")
    store.upsert_watched("750", {"status": "open"})

    accumulate_watch_list_initiatives(store, config, [])
    accumulate_watch_list_initiatives(store, config, [])  # second run: edition already parsed
    assert calls["n"] == 1


def test_accumulation_ignores_unwatched_rrs(tmp_path, monkeypatch):
    config = _mk_config(tmp_path)
    folder = config.cuf_dir / "CUF Meeting Materials 20260521_20260515"
    folder.mkdir()
    (folder / "releases.pdf").write_text("x", encoding="utf-8")

    ctx = "RR999 is part of the 2026 Settlements Fall Bundle."
    monkeypatch.setattr(main, "parse_pdf", lambda p: PdfParseResult(
        path=p, text=ctx, rr_mentions=[RRMention(rr_number="999", context=ctx, source=p.name, page=1)]))

    store = MetadataStore(tmp_path / "m.json")
    store.upsert_watched("750", {"status": "open"})  # 999 is NOT watched
    accumulate_watch_list_initiatives(store, config, [])
    assert store.get_watched("999") is None  # never added


def test_enrich_relevant_from_watch_list_fills_only_blanks(tmp_path):
    store = MetadataStore(tmp_path / "m.json")
    store.upsert_watched("750", {"market_initiative": "Fall 2026 Bundle",
                                 "market_initiative_citation": "old.pdf:p6", "status": "open"})
    store.upsert_watched("728", {"market_initiative": "Recovered", "status": "open"})
    relevant = [
        {"rr_number": "750", "market_initiative": ""},              # blank -> filled
        {"rr_number": "728", "market_initiative": "Latest label"},  # present -> untouched
    ]
    _enrich_relevant_from_watch_list(store, relevant)
    assert relevant[0]["market_initiative"] == "Fall 2026 Bundle"
    assert relevant[0]["market_initiative_citation"] == "old.pdf:p6"
    assert relevant[1]["market_initiative"] == "Latest label"
