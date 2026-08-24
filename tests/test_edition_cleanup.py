"""main._remove_superseded_editions: dedup CUF folders when SPP republishes
a meeting's materials under a new filename (same meeting date, later publish
date) -- the old folder must not stick around as a stale duplicate."""
from main import _remove_superseded_editions


def test_removes_sibling_with_same_meeting_date(tmp_path):
    cuf_dir = tmp_path / "CUF"
    original = cuf_dir / "CUF Meeting Materials 20260716_20260709"
    republished = cuf_dir / "CUF July 2026 Meeting Materials 20260716_20260720"
    unrelated = cuf_dir / "CUF Meeting Materials 20260618_20260612"
    for folder in (original, republished, unrelated):
        folder.mkdir(parents=True)
        (folder / "Agenda.pdf").write_text("x", encoding="utf-8")

    removed = _remove_superseded_editions(cuf_dir, republished)

    assert removed == [original.name]
    assert not original.exists()
    assert republished.exists()
    assert unrelated.exists()  # different meeting date -- left alone


def test_no_siblings_removes_nothing(tmp_path):
    cuf_dir = tmp_path / "CUF"
    only = cuf_dir / "CUF Meeting Materials 20260618_20260612"
    only.mkdir(parents=True)

    assert _remove_superseded_editions(cuf_dir, only) == []
    assert only.exists()
