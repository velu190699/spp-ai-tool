"""Who may edit the RR Control app (src/control_app/auth.py)."""
import yaml

from src.control_app import auth


def _write(tmp_path, data):
    path = tmp_path / "app_access.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_no_access_file_means_editable(tmp_path, monkeypatch):
    # Locally there is nobody to protect the tool from: the only person who can
    # open it is the one who started it. Locking them out would be absurd.
    monkeypatch.setattr(auth, "_windows_user", lambda: "someone")
    viewer = auth.current_viewer(auth.load_access(tmp_path / "missing.yaml"))
    assert viewer.can_edit is True and viewer.signed_in is False


def test_a_broken_access_file_still_allows_reading(tmp_path, monkeypatch):
    path = tmp_path / "app_access.yaml"
    path.write_text("editors: [unclosed\n", encoding="utf-8")
    monkeypatch.setattr(auth, "_windows_user", lambda: "someone")
    # Malformed YAML must not throw on every page load.
    assert auth.load_access(path) == {}


def test_windows_user_is_matched_against_the_list(tmp_path, monkeypatch):
    access = auth.load_access(_write(tmp_path, {"editors": ["BO.PM", "eoyarce"]}))
    monkeypatch.setattr(auth, "_windows_user", lambda: "eoyarce")
    assert auth.current_viewer(access).can_edit is True
    monkeypatch.setattr(auth, "_windows_user", lambda: "visitor")
    denied = auth.current_viewer(access)
    assert denied.can_edit is False and "editor list" in denied.reason


def test_signed_in_email_decides_when_deployed(tmp_path, monkeypatch):
    access = auth.load_access(_write(tmp_path, {"editors": ["Pm@Pci.com"]}))
    monkeypatch.setattr(auth, "_streamlit_user", lambda: (True, "pm@pci.com", "A PM"))
    viewer = auth.current_viewer(access)
    assert viewer.can_edit is True and viewer.signed_in is True
    assert viewer.account == "pm@pci.com" and viewer.name == "A PM"

    monkeypatch.setattr(auth, "_streamlit_user", lambda: (True, "someone@pci.com", "Someone"))
    other = auth.current_viewer(access)
    assert other.can_edit is False and other.signed_in is True


def test_signed_in_ignores_an_empty_list_rather_than_opening_up(tmp_path, monkeypatch):
    # The "empty list = everyone edits" shortcut is for local use only. Behind a
    # shared URL an empty list must NOT hand editing to anyone who signs in.
    access = auth.load_access(_write(tmp_path, {"editors": []}))
    monkeypatch.setattr(auth, "_streamlit_user", lambda: (True, "anyone@pci.com", "Anyone"))
    assert auth.current_viewer(access).can_edit is False


def test_editors_are_normalised(tmp_path):
    access = auth.load_access(_write(tmp_path, {"editors": ["  Mixed@Case.COM ", "", "x"]}))
    assert auth.editors(access) == ["mixed@case.com", "x"]
