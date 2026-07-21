from pathlib import Path

from src.documents.local_source import (
    all_cuf_editions,
    all_suf_editions,
    latest_cuf_edition,
    latest_suf_edition,
    meeting_date_from_name,
    to_sharepoint_url,
)


def test_meeting_date_uses_first_yyyymmdd_token():
    assert meeting_date_from_name("CUF Meeting Materials 20260618_20260612").strftime("%Y-%m-%d") == "2026-06-18"
    assert meeting_date_from_name("no date here") is None


def test_to_sharepoint_url_builds_file_redirect_link(tmp_path):
    sync_root = tmp_path / "sync"
    sub = sync_root / "SPPIM" / "CUF" / "CUF Meeting Materials 20260618"
    sub.mkdir(parents=True)
    local = sub / "(07) Markets Releases.pdf"
    local.write_text("x", encoding="utf-8")

    url = to_sharepoint_url(local, sync_root, "https://mypci.sharepoint.com/base")
    # PDF -> ":b:" viewer link off the tenant root, spaces encoded, slashes literal.
    assert url == (
        "https://mypci.sharepoint.com/:b:/r/base/SPPIM/CUF/"
        "CUF%20Meeting%20Materials%2020260618/%2807%29%20Markets%20Releases.pdf?csf=1&web=1"
    )


def test_to_sharepoint_url_builds_folder_redirect_link(tmp_path):
    sync_root = tmp_path / "sync"
    folder = sync_root / "SPPIM" / "CUF" / "CUF Meeting Materials 20260618_20260612"
    folder.mkdir(parents=True)

    url = to_sharepoint_url(folder, sync_root, "https://mypci.sharepoint.com/base", is_folder=True)
    # Folder -> ":f:" link, which redirects to the library's folder view.
    assert url == (
        "https://mypci.sharepoint.com/:f:/r/base/SPPIM/CUF/"
        "CUF%20Meeting%20Materials%2020260618_20260612?csf=1&web=1"
    )


def test_to_sharepoint_url_outside_root_returns_empty(tmp_path):
    outside = tmp_path / "elsewhere" / "file.pdf"
    outside.parent.mkdir(parents=True)
    outside.write_text("x", encoding="utf-8")
    assert to_sharepoint_url(outside, tmp_path / "sync", "https://x/base") == ""


def test_latest_cuf_edition_picks_newest_folder(tmp_path):
    cuf_dir = tmp_path / "CUF"
    older = cuf_dir / "CUF Meeting Materials 20260521_20260515"
    newer = cuf_dir / "CUF Meeting Materials 20260618_20260612"
    for folder in (older, newer):
        folder.mkdir(parents=True)
        (folder / "Agenda.pdf").write_text("x", encoding="utf-8")

    edition = latest_cuf_edition(cuf_dir, tmp_path, "https://x/base")
    assert edition is not None
    assert edition.label == "CUF Meeting Materials 20260618_20260612"
    assert edition.meeting_date.strftime("%Y-%m-%d") == "2026-06-18"
    assert len(edition.files) == 1


def test_latest_suf_edition_picks_newest_pdf(tmp_path):
    suf_dir = tmp_path / "SUF"
    suf_dir.mkdir()
    (suf_dir / "SUF Meeting Materials 20260409_20260402.pdf").write_text("x", encoding="utf-8")
    (suf_dir / "SUF Meeting Materials 20260109_20260102.pdf").write_text("x", encoding="utf-8")

    edition = latest_suf_edition(suf_dir, tmp_path, "https://x/base")
    assert edition is not None
    assert "20260409" in edition.label
    assert len(edition.files) == 1


def test_missing_dirs_return_none(tmp_path):
    assert latest_cuf_edition(tmp_path / "nope", tmp_path, "u") is None
    assert latest_suf_edition(tmp_path / "nope", tmp_path, "u") is None


def test_all_cuf_editions_returns_every_folder_oldest_first(tmp_path):
    cuf_dir = tmp_path / "CUF"
    older = cuf_dir / "CUF Meeting Materials 20260521_20260515"
    newer = cuf_dir / "CUF Meeting Materials 20260618_20260612"
    for folder in (newer, older):  # create out of order; helper must sort
        folder.mkdir(parents=True)
        (folder / "Agenda.pdf").write_text("x", encoding="utf-8")

    editions = all_cuf_editions(cuf_dir, tmp_path, "https://x/base")
    assert [e.label for e in editions] == [
        "CUF Meeting Materials 20260521_20260515",
        "CUF Meeting Materials 20260618_20260612",
    ]
    assert all_cuf_editions(tmp_path / "nope", tmp_path, "u") == []


def test_all_suf_editions_returns_every_pdf_oldest_first(tmp_path):
    suf_dir = tmp_path / "SUF"
    suf_dir.mkdir()
    (suf_dir / "SUF Meeting Materials 20260409_20260402.pdf").write_text("x", encoding="utf-8")
    (suf_dir / "SUF Meeting Materials 20260109_20260102.pdf").write_text("x", encoding="utf-8")

    editions = all_suf_editions(suf_dir, tmp_path, "https://x/base")
    assert [e.meeting_date.strftime("%Y-%m-%d") for e in editions] == ["2026-01-09", "2026-04-09"]
    assert all_suf_editions(tmp_path / "nope", tmp_path, "u") == []
