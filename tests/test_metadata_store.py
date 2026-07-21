import json

from src.state.metadata_store import MetadataStore, current_initiative


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


def test_current_initiative_picks_newest_dated_non_blank():
    assert current_initiative([]) == ("", "")
    # Only an older edition names it; a newer silent edition must not blank it.
    history = [
        {"edition": "CUF|old", "meeting_date": "2026-05-21", "initiative": "2026 Settlements Fall Bundle", "initiative_citation": "old.pdf:p6"},
        {"edition": "CUF|new", "meeting_date": "2026-07-16", "initiative": "", "initiative_citation": ""},
    ]
    assert current_initiative(history) == ("2026 Settlements Fall Bundle", "old.pdf:p6")
    # A newer edition that DOES name one updates the current initiative.
    history.append({"edition": "SUF|newer", "meeting_date": "2026-08-01", "initiative": "Spring 2027 Bundle", "initiative_citation": "s.pdf:p2"})
    assert current_initiative(history) == ("Spring 2027 Bundle", "s.pdf:p2")


def test_parsed_editions_registry_tracks_once(tmp_path):
    store = MetadataStore(tmp_path / "m.json")
    assert not store.is_edition_parsed("CUF|July")
    store.mark_edition_parsed("CUF|July", {"pdfs": 3})
    assert store.is_edition_parsed("CUF|July")
    # Survives save/reload.
    store.save()
    assert MetadataStore(tmp_path / "m.json").is_edition_parsed("CUF|July")


def test_add_watched_mention_recovers_initiative_from_older_edition(tmp_path):
    store = MetadataStore(tmp_path / "m.json")
    # RR750 is watched but its latest-edition initiative came up blank.
    store.upsert_watched("750", {"title": "MSR", "market_initiative": "", "status": "open"})

    # An OLDER edition named the initiative — accumulation recovers it.
    store.add_watched_mention("750", {
        "edition": "CUF|old", "meeting_date": "2026-05-21",
        "initiative": "2026 Settlements Fall Bundle", "initiative_citation": "old.pdf:p6",
    })
    assert store.get_watched("750")["market_initiative"] == "2026 Settlements Fall Bundle"
    assert len(store.get_watched("750")["mentions_seen"]) == 1

    # Re-recording the SAME edition is idempotent (deduped by edition key).
    store.add_watched_mention("750", {
        "edition": "CUF|old", "meeting_date": "2026-05-21",
        "initiative": "2026 Settlements Fall Bundle", "initiative_citation": "old.pdf:p6",
    })
    assert len(store.get_watched("750")["mentions_seen"]) == 1


def test_add_watched_mention_is_noop_for_unwatched_rr(tmp_path):
    store = MetadataStore(tmp_path / "m.json")
    # Backfill fills watched RRs only — an RR seen only in an old edition is skipped.
    assert store.add_watched_mention("999", {"edition": "CUF|old", "initiative": "X"}) is None
    assert store.get_watched("999") is None


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
