"""Option B: run()'s watch-list seeding/refresh (`_refresh_watch_list`)."""
from main import _refresh_watch_list
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
