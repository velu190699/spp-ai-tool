"""Who is looking, and whether they may change anything.

Two identity sources, one answer. When the app is deployed behind corporate
sign-in (Streamlit's native OIDC against Entra ID), the viewer is whoever signed
in and is known by their work email. When it runs locally — a PM on their own
machine, or us developing — there is no sign-in, so the Windows account stands in
and everyone may edit, because the only person who can open it is the person who
started it.

Authorisation itself is the same either way: a list of PM accounts in
``config/app_access.yaml``. That list is ours to edit, not IT's, so a change of
PM never needs a ticket.

Deliberately NOT access control on its own: locally it trusts the desktop
session, which is fine for a tool on someone's own laptop and is not fine on a
shared URL. Deployed, the guarantee comes from the sign-in in front of it.
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st
import yaml

ACCESS_FILE = Path("config/app_access.yaml")


@dataclass(frozen=True)
class Viewer:
    name: str
    account: str          # work email when signed in, Windows user locally
    can_edit: bool
    signed_in: bool       # True only behind real corporate sign-in
    reason: str           # why can_edit is what it is, for the UI to explain

    @property
    def label(self) -> str:
        return self.name or self.account or "unknown"


def _windows_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def load_access(path: Path | str = ACCESS_FILE) -> dict[str, Any]:
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, OSError):
        return {}
    except yaml.YAMLError:
        # A broken access file must not lock everyone out of a read-only view.
        return {}


def editors(access: dict[str, Any]) -> list[str]:
    raw = access.get("editors") or []
    return [str(e).strip().lower() for e in raw if str(e).strip()]


def _streamlit_user() -> tuple[bool, str, str]:
    """(signed_in, email, name) from Streamlit's native OIDC, if configured."""
    try:
        user = st.user
        if not getattr(user, "is_logged_in", False):
            return False, "", ""
        return True, (getattr(user, "email", "") or "").strip(), (getattr(user, "name", "") or "").strip()
    except Exception:
        # st.user raises when no [auth] section exists — the normal local case.
        return False, "", ""


def current_viewer(access: dict[str, Any] | None = None) -> Viewer:
    access = load_access() if access is None else access
    allowed = editors(access)
    signed_in, email, name = _streamlit_user()

    if signed_in:
        can = email.lower() in allowed
        return Viewer(
            name=name or email,
            account=email,
            can_edit=can,
            signed_in=True,
            reason=("listed as an editor" if can else
                    "signed in, but not on the editor list — read only"),
        )

    who = _windows_user()
    # Running locally: if the file names editors, honour it (so a PM's laptop
    # behaves like the deployed app); if it names none, do not lock the only
    # user out of their own tool.
    if allowed:
        can = who.lower() in allowed
        return Viewer(
            name=who, account=who, can_edit=can, signed_in=False,
            reason=("listed as an editor" if can else
                    "not on the editor list — read only"),
        )
    return Viewer(
        name=who, account=who, can_edit=True, signed_in=False,
        reason="running locally with no editor list — everything is editable",
    )
