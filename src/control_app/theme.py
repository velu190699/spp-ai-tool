"""Visual language for the RR Control app.

Deliberately NOT a new design: the palette, the badges and the masthead are
lifted from the published dashboard's template (``src/summaries/rr_control.py``)
so the app and the HTML report read as the same product. The structural
conventions — CSS variables under one prefix, cards, a coloured sidebar — follow
the team's existing Streamlit app so this feels like something they already use.

Anything visual that a page needs should reference a ``--rr-*`` variable rather
than a fresh hex literal.
"""

from __future__ import annotations

import html as _html

import streamlit as st
import streamlit.components.v1 as components

# Straight from the report template's :root — same ink, same accent, same
# status colours, so a "Settlement calc" badge is the same blue in both.
PALETTE = {
    "ink": "#11161d",
    "ink_soft": "#3a4350",
    "paper": "#f7f8fa",
    "card": "#ffffff",
    "line": "#e2e6ec",
    "line_strong": "#c6ccd6",
    "muted": "#6b7585",
    "accent": "#1f4e8c",
    "open": "#1f7a4d",
    "open_bg": "#e8f5ee",
    "closed": "#6b7585",
    "closed_bg": "#eef1f5",
    "sc": "#1f4e8c",
    "sr": "#b4630a",
    "tg": "#6b7585",
    "un": "#9a2b2b",
}

# rr_class -> (label, css suffix, tint) mirroring _CLASS_META in the report.
CLASS_BADGE = {
    "SETTLEMENT_CALC": ("Settlement calc", "sc", "#e7eefa"),
    "SETTLEMENT_RELEVANT": ("Settlement review", "sr", "#fbf0e2"),
    "TARIFF_GOVERNANCE": ("Tariff / governance", "tg", "#eef1f5"),
    "": ("No recommendation report", "un", "#fbecec"),
}

_CSS = """
<style>
:root{
  --rr-ink:%(ink)s; --rr-ink-soft:%(ink_soft)s; --rr-paper:%(paper)s; --rr-card:%(card)s;
  --rr-line:%(line)s; --rr-line-strong:%(line_strong)s; --rr-muted:%(muted)s; --rr-accent:%(accent)s;
  --rr-open:%(open)s; --rr-open-bg:%(open_bg)s; --rr-closed:%(closed)s; --rr-closed-bg:%(closed_bg)s;
  --rr-sc:%(sc)s; --rr-sr:%(sr)s; --rr-tg:%(tg)s; --rr-un:%(un)s;
}
.stApp{ background:var(--rr-paper); }
.block-container{ padding-top:2.2rem; max-width:1500px; }
h1,h2,h3{ color:var(--rr-ink); letter-spacing:-0.01em; }

/* Masthead, same shape as the report's header block */
.rr-mast{ border-bottom:2px solid var(--rr-ink); padding-bottom:14px; margin-bottom:18px; }
.rr-eyebrow{ font-size:11.5px; letter-spacing:.16em; text-transform:uppercase;
  color:var(--rr-muted); font-weight:700; }
.rr-mast h1{ font-size:27px; margin:4px 0 6px; font-weight:700; }
.rr-sub{ color:var(--rr-ink-soft); font-size:14px; max-width:70ch; }
.rr-meta{ display:flex; flex-wrap:wrap; gap:6px 18px; margin-top:12px; font-size:12.5px; color:var(--rr-muted); }

/* Stat cards */
div[data-testid="stMetric"]{ background:var(--rr-card); border:1px solid var(--rr-line);
  border-top:3px solid var(--rr-accent); border-radius:10px; padding:14px 16px; }
div[data-testid="stMetricLabel"] p{ font-size:12px !important; text-transform:uppercase;
  letter-spacing:.05em; color:var(--rr-muted) !important; }
div[data-testid="stMetricValue"]{ font-size:26px; color:var(--rr-ink); }

/* Badges */
.rr-pill{ display:inline-block; font-size:11px; font-weight:700; padding:2px 9px;
  border-radius:20px; white-space:nowrap; }
.rr-open{ background:var(--rr-open-bg); color:var(--rr-open); }
.rr-closed{ background:var(--rr-closed-bg); color:var(--rr-closed); }
.rr-cls{ display:inline-block; font-size:11px; font-weight:700; padding:2px 9px; border-radius:5px; }
.rr-sc{ background:#e7eefa; color:var(--rr-sc); } .rr-sr{ background:#fbf0e2; color:var(--rr-sr); }
.rr-tg{ background:#eef1f5; color:var(--rr-tg); } .rr-un{ background:#fbecec; color:var(--rr-un); }

/* The register table, styled like the report's */
.rr-tab{ width:100%%; border-collapse:collapse; background:var(--rr-card);
  border:1px solid var(--rr-line); border-radius:10px; overflow:hidden; font-size:13px; }
.rr-tab th{ text-align:left; font-size:10.5px; letter-spacing:.06em; text-transform:uppercase;
  color:var(--rr-muted); font-weight:700; padding:10px 12px; background:#fbfcfd;
  border-bottom:2px solid var(--rr-ink); }
.rr-tab td{ padding:10px 12px; border-top:1px solid var(--rr-line); vertical-align:top; color:var(--rr-ink); }
.rr-tab tr.muted td{ background:#fcfcfd; } .rr-tab tr.muted .ttl{ opacity:.62; }
.rr-tab tr.picked td{ background:#f2f7ff; }
.rr-tab .rrid{ font-weight:700; white-space:nowrap; }
.rr-tab .rrid a{ color:var(--rr-accent); text-decoration:none; }
.rr-tab .rrid a:hover{ text-decoration:underline; }
.rr-tab .dom{ display:block; font-size:10.5px; color:var(--rr-muted); font-weight:600; margin-top:2px; }
.rr-tab .sub{ display:block; font-size:11.5px; color:var(--rr-muted); margin-top:3px; }
.rr-tab .blank{ color:var(--rr-muted); font-style:italic; }
.rr-tab .who{ font-size:11px; color:var(--rr-muted); }
.rr-tab .ttl a.pick{ color:var(--rr-ink); text-decoration:none; }
.rr-tab .ttl a.pick:hover{ color:var(--rr-accent); text-decoration:underline; }
.rr-tab tr.picked .ttl a.pick{ color:var(--rr-accent); }
.rr-tab td.act{ white-space:nowrap; text-align:right; }
.rr-tab td.act a{ font-size:11px; font-weight:700; letter-spacing:.04em; text-transform:uppercase;
  color:var(--rr-muted); text-decoration:none; border:1px solid var(--rr-line-strong);
  border-radius:20px; padding:3px 10px; }
.rr-tab td.act a:hover{ color:var(--rr-accent); border-color:var(--rr-accent); }

/* Library listings: one compact table per kind, the filename IS the link.
   An <h4> here would be turned into a Streamlit heading with its own anchor
   link, which looks like the link but goes nowhere. */
.rr-lib{ width:100%%; border-collapse:collapse; background:var(--rr-card);
  border:1px solid var(--rr-line); border-radius:10px; overflow:hidden; font-size:13px;
  margin-bottom:6px; }
.rr-lib th{ text-align:left; font-size:10.5px; letter-spacing:.06em; text-transform:uppercase;
  color:var(--rr-muted); font-weight:700; padding:8px 12px; background:#fbfcfd;
  border-bottom:1px solid var(--rr-line-strong); }
.rr-lib td{ padding:8px 12px; border-top:1px solid var(--rr-line); color:var(--rr-ink); }
.rr-lib td.w{ white-space:nowrap; color:var(--rr-muted); font-variant-numeric:tabular-nums; }
.rr-lib a{ color:var(--rr-accent); text-decoration:none; font-weight:600; }
.rr-lib a:hover{ text-decoration:underline; }
.rr-lib tr.newest td{ background:#f2f7ff; }
.rr-lib .tag{ font-size:10.5px; color:var(--rr-muted); font-weight:700; text-transform:uppercase;
  letter-spacing:.04em; }
.rr-sec{ font-size:12px; letter-spacing:.06em; text-transform:uppercase; color:var(--rr-muted);
  font-weight:700; margin:18px 0 6px; }

/* Filter row, mirroring the report's pill-shaped toggle */
div[data-testid="stCheckbox"] label p{ font-size:13px !important; color:var(--rr-ink-soft) !important; }

/* Determinant tables inside the detail panel */
.rr-det{ width:100%%; border-collapse:collapse; font-size:12.5px; background:var(--rr-card);
  border:1px solid var(--rr-line); border-radius:8px; overflow:hidden; }
.rr-det th{ text-align:left; font-size:10px; letter-spacing:.04em; text-transform:uppercase;
  color:var(--rr-muted); font-weight:700; padding:7px 10px; background:#fbfcfd;
  border-bottom:1px solid var(--rr-line-strong); }
.rr-det td{ padding:7px 10px; border-top:1px solid var(--rr-line); vertical-align:top; }
.rr-det td.det{ white-space:nowrap; font-weight:600; }
.rr-det td.pg{ white-space:nowrap; color:var(--rr-accent); font-weight:600; }
.rr-det .sec{ display:block; font-size:10px; color:var(--rr-muted); margin-top:2px; }

/* Decision card: the one place a PM types, so it gets an accent edge and a
   header that names what is being decided. */
.rr-dec-head{ background:var(--rr-card); border:1px solid var(--rr-line);
  border-top:3px solid var(--rr-accent); border-radius:10px 10px 0 0; padding:14px 18px 12px; }
.rr-dec-head .num{ font-size:19px; font-weight:700; color:var(--rr-accent); }
.rr-dec-head .ttl{ font-size:19px; font-weight:700; color:var(--rr-ink); }
.rr-dec-head .meta{ margin-top:7px; display:flex; flex-wrap:wrap; gap:8px 14px;
  align-items:center; font-size:12.5px; color:var(--rr-muted); }
.rr-dec-head a{ color:var(--rr-accent); text-decoration:none; font-weight:600; font-size:12.5px; }
.rr-dec-head a:hover{ text-decoration:underline; }

/* Briefing page: one block per market initiative */
.rr-init{ background:var(--rr-card); border:1px solid var(--rr-line); border-radius:10px;
  padding:14px 16px; margin-bottom:12px; }
.rr-init h3{ margin:0; font-size:15px; font-weight:700; color:var(--rr-ink); }
.rr-init .n{ font-size:12px; color:var(--rr-muted); margin-top:2px; }
.rr-init ul{ margin:10px 0 0; padding-left:0; list-style:none; }
.rr-init li{ padding:6px 0; border-top:1px solid var(--rr-line); font-size:13px;
  display:flex; gap:10px; align-items:baseline; flex-wrap:wrap; }
.rr-init li .rr{ font-weight:700; color:var(--rr-accent); white-space:nowrap; min-width:56px; }
.rr-init li .t{ flex:1; min-width:220px; }
.rr-noinit{ border-left:3px solid var(--rr-line-strong); }

section[data-testid="stSidebar"]{ background:var(--rr-card); border-right:1px solid var(--rr-line); }
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS % PALETTE, unsafe_allow_html=True)


def masthead(title: str, subtitle: str, meta: list[str]) -> None:
    bits = "".join(f"<span>{_html.escape(m)}</span>" for m in meta if m)
    st.markdown(
        f'<div class="rr-mast"><div class="rr-eyebrow">PCI Energy Solutions &middot; SPPIM</div>'
        f"<h1>{_html.escape(title)}</h1><div class='rr-sub'>{_html.escape(subtitle)}</div>"
        f'<div class="rr-meta">{bits}</div></div>',
        unsafe_allow_html=True,
    )


def class_badge(rr_class: str) -> str:
    label, suffix, _ = CLASS_BADGE.get(rr_class, CLASS_BADGE[""])
    return f'<span class="rr-cls rr-{suffix}">{_html.escape(label)}</span>'


def status_pill(status: str) -> str:
    cls = "rr-open" if status == "open" else "rr-closed"
    return f'<span class="rr-pill {cls}">{_html.escape(status)}</span>'


def esc(text: object) -> str:
    return _html.escape(str(text or ""))


# Streamlit's markdown sanitiser rewrites every <a> to target="_blank" and drops
# a target of our own, so a link meant to navigate the app itself opens a second
# copy in a new tab. The links that do that are ours and recognisable — their
# href starts with "?" — so an invisible component reaches up into the page and
# puts them back to _self. It re-applies on every DOM update because Streamlit
# re-renders the table whenever anything changes.
_SAME_TAB_JS = """
<script>
(function () {
  const doc = window.parent && window.parent.document;
  if (!doc) return;
  const fix = () => doc.querySelectorAll('a[href^="?"]').forEach(a => {
    a.setAttribute('target', '_self');
    a.removeAttribute('rel');
  });
  fix();
  new MutationObserver(fix).observe(doc.body, { childList: true, subtree: true });
})();
</script>
"""


def same_tab_links() -> None:
    """Keep in-app links (href="?...") in the current tab. See _SAME_TAB_JS."""
    components.html(_SAME_TAB_JS, height=0)
