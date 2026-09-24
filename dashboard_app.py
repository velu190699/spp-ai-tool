"""RR Control — the PM-facing dashboard (prototype).

    run_dashboard.bat        (or: python -m streamlit run dashboard_app.py)

Reads the real watch list through the same ``build_rr_control_rows`` the
published HTML uses, so the tool's half of every row is identical in both, and
wears the same palette and badges as the report (``src/control_app/theme.py``).
What the PM marks goes to ``decisions.db``; nothing here ever writes to
``metadata.json``.

Screens live in ``src/control_app/screens.py``; this file is the shell.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

import main as tool
from config import load_config
from src.control_app import screens
from src.control_app.auth import current_viewer
from src.control_app.decisions import DecisionStore
from src.control_app.theme import inject_css
from src.state.metadata_store import MetadataStore
from src.summaries import rr_control

st.set_page_config(page_title="RR Control", page_icon="📋", layout="wide",
                   initial_sidebar_state="expanded")

DEFAULT_DB = Path("data/state/decisions.db")


@st.cache_resource
def _config():
    return load_config()


def _rows(_config_obj) -> list[dict]:
    """The tool's half of every row — same source, and same resolvers, as the
    published HTML, so a row reads identically in both surfaces."""
    state = MetadataStore(_config_obj.state_file, legacy_path=Path("data/state/metadata.json"))
    return rr_control.build_rr_control_rows(
        state.list_watched(),
        story_url_of=tool._rr_story_url_resolver(_config_obj),
        changes_of=tool._rr_charge_changes_resolver(_config_obj),
    )


inject_css()
config = _config()
rows = _rows(config)
generated = datetime.now().strftime("%B %d, %Y %H:%M")

viewer = current_viewer()

with st.sidebar:
    st.markdown("### RR Control")
    st.caption(f"{viewer.label} · {'can edit' if viewer.can_edit else 'read only'}")
    if viewer.signed_in:
        st.button("Sign out", on_click=st.logout, width="stretch")
    st.caption(viewer.reason)
    st.divider()
    db_path = st.text_input(
        "Decisions database",
        value=str(st.session_state.get("db_path", DEFAULT_DB)),
        help="Prototype: a local file. In production this points at the NAS — never at a "
             "OneDrive-synced folder, where whole-file sync corrupts SQLite.",
    )
    st.session_state["db_path"] = db_path
    if st.button("Refresh from the tool", width="stretch"):
        st.cache_resource.clear()
        st.rerun()
    st.divider()
    st.caption("Reads the watch list the weekly run maintains; writes only PM decisions.")

store = DecisionStore(db_path)

# Named functions, not lambdas: st.navigation derives each page's URL from the
# callable's name, and four <lambda>s collide into one pathname.
def page_control():
    screens.control(rows, store, generated, viewer)


def page_briefing():
    screens.briefing(rows, store, config, generated)


def page_settings():
    screens.settings(rows, store, config, generated, viewer)


def page_published():
    screens.published(config, generated)


def page_materials():
    screens.materials(config, generated)


st.navigation(
    {
        # Briefing first: it is the report the whole of PCI reads. The control
        # register below it is the settlement PM's working tool.
        "Reports": [
            st.Page(page_briefing, title="Briefing", icon=":material/insights:", default=True),
            st.Page(page_control, title="Control", icon=":material/fact_check:"),
        ],
        "Library": [
            st.Page(page_published, title="Published reports", icon=":material/description:"),
            st.Page(page_materials, title="Source materials", icon=":material/folder_open:"),
        ],
        "Configure": [
            st.Page(page_settings, title="Settings", icon=":material/settings:"),
        ],
    }
).run()
