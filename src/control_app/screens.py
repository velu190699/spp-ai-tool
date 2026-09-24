"""The RR Control app's screens.

Kept out of ``dashboard_app.py`` so the entry point stays a shell: theme,
navigation, and the two data sources it hands to every page.

The register's stat row and its filter are deliberately THE SAME as the
published report's (``rr_control.summarize`` and the "hide RRs with no
calculation change" toggle). The app adds exactly one number the report cannot
know — how many still await a PM — and nothing else, so the two surfaces never
disagree about how many RRs there are or what is worth looking at.
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from src.control_app import library
from src.control_app.auth import Viewer
from src.control_app.decisions import DecisionStore, stale_decision
from src.control_app.theme import class_badge, esc, masthead, same_tab_links, status_pill
from src.summaries.rr_control import summarize


def is_relevant(row: dict, decision: dict) -> bool:
    """Is this RR worth a PM's attention?

    The tool's verdict is the starting point — only a real charge-code change
    (SETTLEMENT_CALC) asks for a decision — but the PM's own call overrides it in
    both directions: forcing "applies" pulls an RR in even when the tool
    dismissed it, and discarding one drops it even when the tool flagged it.
    """
    applies = (decision or {}).get("applies", "")
    if applies == "Yes":
        return True
    if applies == "No":
        return False
    return row["rr_class"] == "SETTLEMENT_CALC"


def _decision_cell(decision: dict, stale: bool) -> str:
    if not decision or not (decision.get("applies") or decision.get("reviewed")):
        return '<span class="blank">not reviewed</span>'
    bits = []
    applies = decision.get("applies")
    if applies == "Yes":
        bits.append('<span class="rr-pill rr-open">applies</span>')
    elif applies == "No":
        bits.append('<span class="rr-pill rr-closed">discarded</span>')
    if decision.get("reviewed"):
        who = esc(decision.get("reviewed_by", ""))
        when = esc((decision.get("reviewed_at") or "")[:10])
        bits.append(f'<span class="sub">reviewed by {who} &middot; {when}</span>')
    if stale:
        bits.append('<span class="sub" style="color:#9a2b2b;">tool reclassified since</span>')
    return "".join(bits)


def _register_table(rows: list[dict], decisions: dict, picked: str) -> str:
    head = (
        "<tr><th>RR</th><th>Title</th><th>Class / scope</th><th>Status</th>"
        "<th>Market initiative</th><th>Story</th><th>PM decision</th><th>Updated</th><th></th></tr>"
    )
    body = []
    for r in rows:
        rr = r["rr_number"]
        d = decisions.get(rr, {})
        stale = stale_decision(d, r["rr_class"])
        classes = []
        if r["muted"]:
            classes.append("muted")
        if rr == picked:
            classes.append("picked")
        rr_cell = (
            f'<a href="{esc(r["rr_url"])}" target="_blank" rel="noopener noreferrer">RR{esc(rr)}</a>'
            if r["rr_url"] else f"RR{esc(rr)}"
        )
        initiative = d.get("initiative_validated") or r["market_initiative"]
        if d.get("initiative_validated"):
            init_cell = f"{esc(initiative)}<span class='sub'>validated</span>"
        elif initiative:
            init_cell = esc(initiative)
        elif r["initiative_hint"]:
            init_cell = f'<span class="blank">not named</span><span class="sub">nearby: {esc(r["initiative_hint"])}</span>'
        else:
            init_cell = '<span class="blank">not named</span>'
        story = (
            f'<a href="{esc(r["story_url"])}" target="_blank" rel="noopener noreferrer">open</a>'
            if r["story_url"]
            else ('<span class="blank">Not applicable</span>' if r["out_of_scope"] else '<span class="blank">&mdash;</span>')
        )
        scope = "<span class='sub'>no calculation impact</span>" if r["out_of_scope"] else ""
        dets = (
            f"<span class='sub'>{r['det_count']} charge code{'s' if r['det_count'] != 1 else ''}</span>"
            if r["det_count"] else ""
        )
        body.append(
            f'<tr class="{" ".join(classes)}">'
            f'<td class="rrid">{rr_cell}<span class="dom">{esc(r["domain"])}</span></td>'
            f'<td class="ttl"><a class="pick" href="?rr={esc(rr)}">{esc(r["title"])}</a></td>'
            f"<td>{class_badge(r['rr_class'])}{scope}{dets}</td>"
            f"<td>{status_pill(r['status'])}</td>"
            f"<td>{init_cell}</td>"
            f"<td>{story}</td>"
            f"<td>{_decision_cell(d, stale)}</td>"
            f'<td style="white-space:nowrap; color:#6b7585;">{esc(r["last_updated"])}</td>'
            f'<td class="act"><a href="?rr={esc(rr)}&amp;detail={esc(rr)}">detail</a></td></tr>'
        )
    return f'<table class="rr-tab"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


def _determinant_table(changes: list[dict]) -> str:
    head = "<tr><th style='width:34px;'>#</th><th style='width:170px;'>Determinant</th><th>Formula before</th><th>Formula after</th><th style='width:52px;'>Page</th></tr>"
    body = []
    for i, c in enumerate(changes, 1):
        section = f"<span class='sec'>{esc(c.get('section'))}</span>" if c.get("section") else ""
        body.append(
            f"<tr><td class='w'>{i}</td>"
            f"<td class='det'>{esc(c.get('determinant'))}{section}</td>"
            f"<td>{esc(c.get('formula_before')) or '&mdash;'}</td>"
            f"<td>{esc(c.get('formula_after')) or '&mdash;'}</td>"
            f"<td class='pg'>{esc(c.get('page')) or '&mdash;'}</td></tr>"
        )
    return f'<table class="rr-det"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


def _mention_table(mentions: list[dict]) -> str:
    head = "<tr><th style='width:88px;'>Date</th><th style='width:46px;'>Kind</th><th>Document</th><th>Initiative named</th></tr>"
    body = []
    for m in mentions:
        init = esc(m.get("initiative")) or '<span class="sec">none named</span>'
        cite = f"<span class='sec'>{esc(m.get('citation'))}</span>" if m.get("citation") else ""
        body.append(
            f"<tr><td class='w'>{esc(m.get('date'))}</td><td class='w'>{esc(m.get('kind'))}</td>"
            f"<td>{esc(m.get('label'))}</td><td>{init}{cite}</td></tr>"
        )
    return f'<table class="rr-det"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


@st.dialog("RR detail", width="large")
def _detail_dialog(row: dict, decision: dict) -> None:
    st.markdown(
        f"### RR{row['rr_number']} — {row['title']}\n\n{class_badge(row['rr_class'])} &nbsp; {row['class_blurb']}",
        unsafe_allow_html=True,
    )
    links = []
    if row["rr_url"]:
        links.append(f"[Recommendation Report]({row['rr_url']})")
    if row["story_url"]:
        links.append(f"[Story workbook]({row['story_url']})")
    if links:
        st.markdown(" · ".join(links))
    if stale_decision(decision, row["rr_class"]):
        st.warning(f"Decided when the tool said `{decision['class_when_decided']}`; it now says `{row['rr_class']}`.")
    st.markdown("<div class='rr-sec'>Charge-code determinants</div>", unsafe_allow_html=True)
    if row["changes"]:
        st.markdown(_determinant_table(row["changes"]), unsafe_allow_html=True)
    elif row["determinants"]:
        st.caption("Determinants found, formulas not extracted: " + ", ".join(row["determinants"]))
    else:
        st.caption("No charge-code determinants in this RR.")
    st.markdown("<div class='rr-sec'>CUF/SUF mention history</div>", unsafe_allow_html=True)
    if row["mentions"]:
        st.markdown(_mention_table(row["mentions"]), unsafe_allow_html=True)
    else:
        st.caption("No mentions recorded.")


def control(rows: list[dict], store: DecisionStore, generated: str, viewer: Viewer) -> None:
    decisions = store.all()
    stale_set = {r["rr_number"] for r in rows if stale_decision(decisions.get(r["rr_number"], {}), r["rr_class"])}
    stats = summarize(rows)  # the report's own numbers, not a second opinion
    relevant = [r for r in rows if is_relevant(r, decisions.get(r["rr_number"], {}))]
    pending = [r for r in relevant if not decisions.get(r["rr_number"], {}).get("reviewed")]

    masthead(
        "Settlement Changes Control",
        "Every Revision Request the settlement team is tracking — open and recently closed — "
        "with its class, market initiative, and CUF/SUF mention history. The tool proposes; the PM decides.",
        [f"Generated: {generated}", "Market: SPPIM"],
    )

    # Same four cards as the published report, plus the one number only the app
    # can know. Keeping the report's four identical means the two never disagree.
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Watched RRs", stats["total"])
    c2.metric("Settlement calc", stats["settlement_calc"])
    c3.metric("With initiative", stats["with_initiative"])
    c4.metric("With story", stats["with_story"])
    c5.metric("Pending review", len(pending), help="Calculation changes not yet reviewed by a PM.")

    if stale_set:
        st.warning(
            "Reclassified by the tool after they were reviewed, so the decision was made about a "
            "different classification: " + ", ".join("RR" + s for s in sorted(stale_set))
        )

    # The report's filter, verbatim, plus the same idea applied to review state.
    f1, f2, f3 = st.columns([1.3, 1, 1])
    hide = f1.checkbox(f"Hide RRs with no calculation change ({stats['hideable']})", value=False)
    only_pending = f2.checkbox(f"Only pending review ({len(pending)})", value=False)
    hide_discarded = f3.checkbox("Hide RRs the PM discarded", value=False,
                                 help="Rows where a PM answered No to “Applies”.")

    shown = rows
    if hide:
        shown = [r for r in shown if not r["muted"]]
    if only_pending:
        shown = [r for r in shown if r in pending]
    if hide_discarded:
        shown = [r for r in shown if decisions.get(r["rr_number"], {}).get("applies") != "No"]

    # Clicking a row is a plain link that sets ?rr=<n> (and ?detail=<n>), so the
    # register keeps the report's styling instead of becoming a Streamlit widget.
    params = st.query_params
    by_rr = {r["rr_number"]: r for r in rows}
    wanted = params.get("rr", "")
    picked = wanted if wanted in by_rr else ((shown or rows)[0]["rr_number"] if (shown or rows) else "")

    if not shown:
        st.success("Nothing matches these filters.")
    else:
        st.markdown(_register_table(shown, decisions, picked), unsafe_allow_html=True)
        same_tab_links()
        st.caption(
            f"{len(shown)} of {len(rows)} RRs · click a title to work on it, "
            "“detail” for the full picture, the RR number for its Recommendation Report"
        )

    st.divider()
    if picked:
        _decision_panel(rows, store, decisions, picked, viewer)

        # Open the dialog once per click: the URL still says detail=<n> after it
        # closes, so remember which one was last honoured instead of reopening
        # it on every rerun.
        asked = params.get("detail", "")
        if asked in by_rr and st.session_state.get("_detail_shown") != asked:
            st.session_state["_detail_shown"] = asked
            _detail_dialog(by_rr[asked], decisions.get(asked, {}))


def _decision_panel(rows: list[dict], store: DecisionStore, decisions: dict, picked: str,
                    viewer: Viewer) -> None:
    """Just the decision.

    Everything the tool knows — determinants, mention history, links — is in the
    table above and in the detail dialog, so repeating it here only made the page
    longer and squeezed the determinant table into half the width.
    """
    by_rr = {r["rr_number"]: r for r in rows}
    row, d = by_rr[picked], decisions.get(picked, {})

    links = []
    if row["rr_url"]:
        links.append(f'<a href="{esc(row["rr_url"])}" target="_blank" rel="noopener noreferrer">Recommendation Report</a>')
    if row["story_url"]:
        links.append(f'<a href="{esc(row["story_url"])}" target="_blank" rel="noopener noreferrer">Story workbook</a>')
    dets = f"{row['det_count']} charge code{'s' if row['det_count'] != 1 else ''}" if row["det_count"] else "no charge codes"
    st.markdown(
        f'<div class="rr-dec-head"><span class="num">RR{esc(picked)}</span> '
        f'<span class="ttl">{esc(row["title"])}</span>'
        f'<div class="meta">{class_badge(row["rr_class"])} {status_pill(row["status"])}'
        f'<span>{esc(dets)}</span><span>{esc(row["domain"])}</span>{"".join(links)}</div></div>',
        unsafe_allow_html=True,
    )
    if stale_decision(d, row["rr_class"]):
        st.warning(
            f"Reviewed when the tool said `{d['class_when_decided']}`; it now says "
            f"`{row['rr_class']}`. Worth confirming the decision still holds."
        )

    # Prepared before the form: an exception inside one aborts it before its
    # submit button exists, which Streamlit then reports as a second, misleading
    # "this form has no submit button" error.
    catalog = [i["name"] for i in store.initiatives()]
    seen = sorted(({r["market_initiative"] for r in rows if r["market_initiative"]}
                   | {v.get("initiative_validated", "") for v in decisions.values()}
                   | set(catalog)) - {""})
    current = d.get("initiative_validated", "")

    if not viewer.can_edit:
        with st.container(border=True):
            st.markdown("**Decision**")
            applies_label = {"Yes": "Applies", "No": "Does not apply"}.get(d.get("applies", ""), "Undecided")
            st.write(f"Applies: **{applies_label}** · Reviewed: **{'yes' if d.get('reviewed') else 'no'}**")
            if d.get("initiative_validated"):
                st.write(f"Market initiative: **{d['initiative_validated']}**")
            if d.get("note"):
                st.info(d["note"])
            if d.get("reviewed_by"):
                st.caption(f"Reviewed by {d['reviewed_by']} on {(d.get('reviewed_at') or '')[:10]}")
            st.caption(f"You are signed in as {viewer.label} — {viewer.reason}.")
        if st.button("Open full detail", width="content"):
            _detail_dialog(row, d)
        return

    with st.container(border=True):
        with st.form(f"decision_{picked}", border=False):
            c1, c2, c3 = st.columns([1.1, 0.7, 1.4])
            with c1:
                applies = st.segmented_control(
                    "Does this RR apply?",
                    options=["Undecided", "Applies", "Does not apply"],
                    default={"": "Undecided", "Yes": "Applies", "No": "Does not apply"}.get(d.get("applies", ""), "Undecided"),
                )
            with c2:
                st.write("")
                reviewed = st.toggle("Reviewed", value=bool(d.get("reviewed", 0)))
            with c3:
                initiative = st.selectbox(
                    "Market initiative", options=["—"] + seen,
                    index=(seen.index(current) + 1) if current in seen else 0,
                    help="Curate the official list under Settings.",
                )
            c4, c5, c6 = st.columns([0.8, 0.8, 1.6])
            related = c4.text_input("Amends RR", value=d.get("related_rr", ""), placeholder="728")
            jira = c5.text_input("Jira key", value=d.get("jira_key", ""), placeholder="SP-12814")
            note = c6.text_input("Note", value=d.get("note", ""),
                                 placeholder="Anything the next person should know.")
            b1, b2 = st.columns([1, 3])
            saved = b1.form_submit_button("Save decision", type="primary", width="stretch")
            if d.get("reviewed_by"):
                b2.caption(f"Last reviewed by {d['reviewed_by']} on {(d.get('reviewed_at') or '')[:10]}")
            if saved:
                store.save(
                    picked,
                    {
                        "applies": {"Undecided": "", "Applies": "Yes", "Does not apply": "No"}[applies],
                        "reviewed": reviewed,
                        "initiative_validated": "" if initiative == "—" else initiative,
                        "related_rr": related.strip(),
                        "jira_key": jira.strip(),
                        "note": note.strip(),
                    },
                    domain=row["domain"],
                    tool_class=row["rr_class"],
                    user=viewer.account,
                )
                st.rerun()

    if st.button("Open full detail", width="content"):
        _detail_dialog(row, d)


# ---------------------------------------------------------------------------
# Briefing: the register read as "what is coming", grouped the way the business
# thinks about it (by market initiative) rather than RR by RR. This is the view
# the meeting asked for and that the register alone does not give.
# ---------------------------------------------------------------------------

def _initiative_block(name: str, items: list[dict], decisions: dict, *, unnamed: bool = False) -> str:
    calc = sum(1 for r in items if r["rr_class"] == "SETTLEMENT_CALC")
    reviewed = sum(1 for r in items if decisions.get(r["rr_number"], {}).get("reviewed"))
    lines = []
    for r in sorted(items, key=lambda x: x["rr_number"]):
        d = decisions.get(r["rr_number"], {})
        mark = ""
        if d.get("applies") == "No":
            mark = '<span class="rr-pill rr-closed">discarded</span>'
        elif d.get("reviewed"):
            mark = '<span class="rr-pill rr-open">reviewed</span>'
        link = (
            f'<a href="{esc(r["rr_url"])}" target="_blank" rel="noopener noreferrer">RR{esc(r["rr_number"])}</a>'
            if r["rr_url"] else f'RR{esc(r["rr_number"])}'
        )
        lines.append(
            f'<li><span class="rr">{link}</span><span class="t">{esc(r["title"])}</span>'
            f'{class_badge(r["rr_class"])}{mark}</li>'
        )
    title = "Not tied to an initiative" if unnamed else esc(name)
    plural = "s" if len(items) != 1 else ""
    cplural = "s" if calc != 1 else ""
    return (
        f'<div class="rr-init{" rr-noinit" if unnamed else ""}"><h3>{title}</h3>'
        f'<div class="n">{len(items)} RR{plural} &middot; {calc} calculation change{cplural} '
        f'&middot; {reviewed} reviewed</div>'
        f'<ul>{"".join(lines)}</ul></div>'
    )


def briefing(rows: list[dict], store: DecisionStore, config, generated: str) -> None:
    """The published briefing itself, rendered in the app.

    Not a reimplementation: the weekly run already writes
    ``SPP_Market_Changes_Summary-<runid>.html`` with the team's own layout (the
    per-division cards, the timeline, the tabs), and its content is the LLM's,
    which the app has no way to reproduce. So the page serves that exact file —
    same bytes a person would open from SharePoint — with a picker for earlier
    editions, and adds underneath the one thing the briefing cannot know: how the
    register groups by initiative once a PM has validated the names.
    """
    reports = [i for i in library.published(config) if i.kind == "Full report"]
    masthead(
        "Briefing",
        "The full Market Changes Summary the tool publishes for every new CUF/SUF edition, "
        "exactly as it appears in SharePoint.",
        [f"{len(reports)} editions published", f"Generated: {generated}"],
    )

    if not reports:
        st.info("No briefing published yet. It is written whenever SPP posts a new CUF/SUF edition.")
    else:
        pick_l, pick_r = st.columns([3, 1])
        with pick_l:
            chosen = st.selectbox(
                "Edition", options=reports,
                format_func=lambda i: f"{i.when} — {i.name}",
                label_visibility="collapsed",
            )
        with pick_r:
            st.markdown(
                f'<div style="padding-top:6px;"><a href="{esc(chosen.url)}" target="_blank" '
                f'rel="noopener noreferrer">Open in SharePoint</a></div>',
                unsafe_allow_html=True,
            )
        try:
            html = chosen.path.read_text(encoding="utf-8")
        except OSError as exc:
            st.error(f"Could not read {chosen.name}: {exc}")
        else:
            # Served in its own frame so the briefing's stylesheet cannot fight
            # the app's, and vice versa.
            components.html(html, height=1500, scrolling=True)

    st.divider()
    decisions = store.all()
    grouped: dict[str, list[dict]] = {}
    unnamed: list[dict] = []
    for r in rows:
        name = decisions.get(r["rr_number"], {}).get("initiative_validated") or r["market_initiative"]
        if name:
            grouped.setdefault(name, []).append(r)
        else:
            unnamed.append(r)

    with st.expander(f"Register grouped by market initiative ({len(grouped)} initiatives, "
                     f"{len(unnamed)} unassigned)"):
        st.caption(
            "What the briefing cannot show: the live register grouped by the business unit of work, "
            "with each PM decision. A validated initiative wins over the one extracted from the slides."
        )
        for name in sorted(grouped, key=lambda n: (-len(grouped[n]), n)):
            st.markdown(_initiative_block(name, grouped[name], decisions), unsafe_allow_html=True)
        if unnamed:
            st.markdown(_initiative_block("", unnamed, decisions, unnamed=True), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Settings: the two lists a PM needs to curate. Both are read and written where
# the tool already expects them — the catalog in decisions.db, the division
# topics in config/area_routing.yaml, which the briefing pipeline reads on every
# run.
# ---------------------------------------------------------------------------

def settings(rows: list[dict], store: DecisionStore, config, generated: str, viewer: Viewer) -> None:
    masthead(
        "Settings",
        "The curated lists behind the dashboard: which market initiatives are official, and which "
        "topics route a change to each PCI division in the full report.",
        [f"Generated: {generated}"],
    )

    st.markdown("<div class='rr-sec'>Market initiative catalog</div>", unsafe_allow_html=True)
    st.caption(
        "The same initiative reaches us under different names depending on the slide it came from, "
        "which is what makes RRs hard to group. Curate the official names here; a PM picks from this "
        "list when validating an RR. Retiring a name keeps it resolvable for RRs already decided under it."
    )

    if not viewer.can_edit:
        st.info(
            f"You are viewing as {viewer.label} — {viewer.reason}. "
            "The catalog and the routing below are read-only for you."
        )

    usage = store.initiative_usage()
    catalog = store.initiatives(active_only=False)
    extracted = sorted({r["market_initiative"] for r in rows if r["market_initiative"]}
                       - {c["name"] for c in catalog})

    if viewer.can_edit:
        with st.form("add_initiative", border=True):
            st.markdown("**Add an initiative**")
            c1, c2 = st.columns([2, 3])
            name = c1.text_input("Name", placeholder="2026 Settlements Fall Bundle")
            note = c2.text_input("Note", placeholder="Where the name comes from, go-live, anything useful")
            if st.form_submit_button("Add to catalog", type="primary"):
                if not name.strip():
                    st.error("Give it a name first.")
                elif store.add_initiative(name, note=note, user=viewer.account):
                    st.success(f"Added {name.strip()}")
                    st.rerun()
                else:
                    st.info(f"{name.strip()} is already in the catalog.")

        if extracted:
            st.caption("Names the tool extracted from CUF/SUF slides that are not in the catalog yet:")
            cols = st.columns(min(3, len(extracted)))
            for n, candidate in enumerate(extracted):
                if cols[n % len(cols)].button(f"Adopt: {candidate}", key=f"adopt_{n}", width="stretch"):
                    store.add_initiative(candidate, note="adopted from a CUF/SUF slide", user=viewer.account)
                    st.rerun()
    elif extracted:
        st.caption(f"{len(extracted)} name(s) extracted from slides are not in the catalog yet.")

    if not catalog:
        st.info("The catalog is empty." + (" Add the official names, or adopt the extracted ones above."
                                           if viewer.can_edit else ""))
    else:
        for entry in catalog:
            c1, c2, c3 = st.columns([3, 2, 1])
            state = "" if entry["active"] else " · retired"
            used = usage.get(entry["name"], 0)
            c1.markdown(f"**{entry['name']}**{state}")
            plural = "s" if used != 1 else ""
            c2.caption(f"{used} RR{plural} validated · {entry.get('note') or 'no note'}")
            if viewer.can_edit:
                label = "Retire" if entry["active"] else "Restore"
                if c3.button(label, key=f"tog_{entry['name']}", width="stretch"):
                    store.set_initiative_active(entry["name"], not entry["active"])
                    st.rerun()

    st.divider()
    st.markdown("<div class='rr-sec'>Division topics (full report routing)</div>", unsafe_allow_html=True)
    st.caption(
        "Which topics send a change to which PCI division in the full report. This belongs to the "
        "briefing pipeline, not the register — it is here because everything should be reachable in "
        "one place. Saving rewrites config/area_routing.yaml, which the next run reads."
    )
    _area_routing_editor(config, viewer)


def _area_routing_editor(config, viewer: Viewer) -> None:
    import yaml

    path = config.area_routing_file
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        st.warning(f"{path} not found.")
        return
    areas = data.get("areas") or {}
    if not areas:
        st.warning("No areas defined in the routing file.")
        return

    edited: dict[str, list[str]] = {}
    for key, area in areas.items():
        topics = area.get("topics") or []
        with st.expander(f"{area.get('name', key)} · {len(topics)} topics"):
            text = st.text_area(
                "One topic per line", value="\n".join(topics),
                height=150, key=f"topics_{key}", label_visibility="collapsed",
            )
            edited[key] = [line.strip() for line in text.splitlines() if line.strip()]

    if viewer.can_edit and st.button("Save routing", type="primary"):
        for key, topics in edited.items():
            areas[key]["topics"] = topics
        data["areas"] = areas
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        st.success(f"Saved to {path}. The next run picks it up.")
