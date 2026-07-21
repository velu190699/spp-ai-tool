import json

from src.state.metadata_store import MetadataStore


def test_metadata_store_detects_new_duplicate_and_hash_change(tmp_path):
    store = MetadataStore(tmp_path / "metadata.json")
    assert store.check_document("123", "file.zip", "aaa").is_new

    store.record_document("123", "file.zip", {"sha256": "aaa", "local_path": "file.zip"})
    duplicate = store.check_document("123", "file.zip", "aaa")
    assert not duplicate.is_new
    assert not duplicate.hash_changed

    changed = store.check_document("123", "file.zip", "bbb")
    assert not changed.is_new
    assert changed.hash_changed


def test_metadata_store_migrates_from_legacy_location(tmp_path):
    legacy = tmp_path / "old" / "metadata.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"documents": {"1|a.zip": {"sha256": "aaa"}}, "runs": []}), encoding="utf-8")
    shared = tmp_path / "shared" / "metadata.json"

    store = MetadataStore(shared, legacy_path=legacy)
    assert not store.check_document("1", "a.zip").is_new  # legacy content loaded

    store.save()
    assert shared.exists()  # saved to the shared location
    # A later load prefers the shared file even though legacy still exists.
    store2 = MetadataStore(shared, legacy_path=legacy)
    assert not store2.check_document("1", "a.zip").is_new


def test_analysis_ledger_new_unchanged_updated(tmp_path):
    store = MetadataStore(tmp_path / "metadata.json")
    assert store.check_analysis("settlement", "RR728", "h1") == "new"

    store.record_analysis("settlement", "RR728", "h1", {"xlsx": "report.xlsx"})
    assert store.check_analysis("settlement", "RR728", "h1") == "unchanged"
    # SPP re-published the RR: same key, different input hash -> UPDATE.
    assert store.check_analysis("settlement", "RR728", "h2") == "updated"

    store.record_analysis("settlement", "RR728", "h2")
    assert store.check_analysis("settlement", "RR728", "h2") == "unchanged"
    # The superseded version is kept in the audit trail.
    entry = store.data["analyses"]["settlement|RR728"]
    assert entry["history"][0]["input_hash"] == "h1"


def test_watch_list_upsert_preserves_initiative_and_first_seen(tmp_path):
    store = MetadataStore(tmp_path / "metadata.json")
    # Discovered via the July CUF with its initiative.
    store.upsert_watched("728", {"title": "RUC MWP", "market_initiative": "Fall 2026 Bundle",
                                 "domain": "BO", "status": "open"})
    first = store.get_watched("728")
    assert first["market_initiative"] == "Fall 2026 Bundle"
    assert first["status"] == "open" and first["first_seen"]

    # A later run whose materials DON'T name the initiative must not wipe it,
    # and first_seen must be preserved.
    store.upsert_watched("728", {"market_initiative": "", "status": "open"})
    again = store.get_watched("728")
    assert again["market_initiative"] == "Fall 2026 Bundle"
    assert again["first_seen"] == first["first_seen"]


def test_watch_list_status_list_and_prune(tmp_path):
    store = MetadataStore(tmp_path / "metadata.json")
    store.upsert_watched("728", {"status": "open"})
    store.upsert_watched("750", {"status": "open"})
    assert [w["rr_number"] for w in store.list_watched()] == ["728", "750"]

    store.set_watched_status("728", "closed")
    assert [w["rr_number"] for w in store.list_watched(status="open")] == ["750"]
    assert [w["rr_number"] for w in store.list_watched(status="closed")] == ["728"]

    store.remove_watched("728")  # after the final capture on close
    assert store.get_watched("728") is None
    assert [w["rr_number"] for w in store.list_watched()] == ["750"]


def test_watch_list_survives_save_reload(tmp_path):
    path = tmp_path / "metadata.json"
    store = MetadataStore(path)
    store.upsert_watched("786", {"market_initiative": "X", "domain": "BO"})
    store.save()
    reloaded = MetadataStore(path)
    assert reloaded.get_watched("786")["market_initiative"] == "X"


def test_relevant_rrs_roundtrip_and_atomic_save(tmp_path):
    path = tmp_path / "metadata.json"
    store = MetadataStore(path)
    assert store.load_relevant_rrs() is None

    rrs = [{"rr_number": "728", "title": "RUC MWP", "market_initiative": "Fall 2026 Market Initiative"}]
    store.save_relevant_rrs(rrs)
    store.save()

    reloaded = MetadataStore(path)
    assert reloaded.load_relevant_rrs() == rrs
    # No stray temp files left behind by the atomic write.
    assert [p.name for p in tmp_path.iterdir()] == ["metadata.json"]
