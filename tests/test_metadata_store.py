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
