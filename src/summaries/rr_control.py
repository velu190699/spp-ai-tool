"""The RR Control dashboard: a persistent, bird's-eye view of the watch list.

Unlike the per-cycle Market Changes briefing (slide-derived, one edition) and the
per-run settlement summary (only the RRs processed that run), this renders EVERY
RR the tool has ever watched — open and closed — with its class, status, market
initiative, story link, and the accumulated CUF/SUF mention history that Option B
builds up across editions. It is written dated + accumulating (a snapshot per
generation, never overwritten), so the evolution of the tracked state is on record.

The builder is pure: it takes the watch-list rows and two optional resolver
callbacks (class-of-RR, story-url-of-RR) so the docx parsing and ledger lookups
stay in the caller and this module stays unit-testable against plain dicts.
"""
from __future__ import annotations

from typing import Any, Callable

from jinja2 import Environment

# Human labels + CSS codes for the three RR classes (see rr_structure.extract).
# The label must stand on its own — the class drives which deliverable an RR gets,
# and reviewers shouldn't need the glossary to read the board.
_CLASS_META = {
    "SETTLEMENT_CALC": ("Settlement calc", "sc",
                        "Changes charge-code formulas (has # determinants) — gets a full settlement story."),
    "SETTLEMENT_RELEVANT": ("Settlement review", "sr",
                            "Affects settlement through prose/Tariff wording, not a numbered formula — gets a review task, not a full story."),
    "TARIFF_GOVERNANCE": ("Tariff / governance", "tg",
                          "Definitions, rates, or governance prose only — no charge-code impact, no story."),
    "": ("Unclassified", "un", "Not yet classified — no Recommendation Report has been parsed for this RR."),
}


def build_rr_control_rows(
    watched: list[dict[str, Any]],
    *,
    class_of: Callable[[str], str] | None = None,
    story_url_of: Callable[[str], str] | None = None,
    changes_of: Callable[[str], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """One display row per watched RR, newest-updated first within each status.

    ``class_of`` / ``story_url_of`` / ``changes_of`` map an RR number to its
    class, story link, and the generated story's per-determinant formula changes
    (before/after + markup-view page, as the Excel shows); any may be omitted
    (dashboard still renders, those cells show a fallback). A row's mention
    history is sorted oldest -> newest so the timeline reads down.
    """
    rows: list[dict[str, Any]] = []
    for w in watched:
        rr = str(w.get("rr_number", ""))
        rr_class = (class_of(rr) if class_of else "") or w.get("rr_class", "") or ""
        determinants = w.get("determinants", []) or []
        mp_impact = w.get("mp_impact")  # True / False / None (not yet classified)
        history = sorted(
            w.get("mentions_seen", []),
            key=lambda m: (m.get("meeting_date") or "", m.get("edition") or ""),
        )
        label, code, blurb = _CLASS_META.get(rr_class, _CLASS_META[""])
        # When no official initiative was named, surface the newest nearby
        # candidate effort as a hint (never the initiative itself).
        initiative = w.get("market_initiative", "")
        hint = ""
        if not initiative:
            for m in reversed(history):
                if m.get("candidate"):
                    hint = m["candidate"]
                    break
        rows.append(
            {
                "rr_number": rr,
                "title": w.get("title", "") or "(title not captured)",
                "rr_class": rr_class,
                "class_label": label,
                "class_code": code,
                "class_blurb": blurb,
                "status": w.get("status", "open"),
                "domain": w.get("domain", ""),
                "working_group": w.get("primary_working_group", ""),
                # Link to the RR itself: the synced Recommendation Report docx if
                # known, else the SPP RR search page. Rendered on the RR number.
                "rr_url": w.get("rr_doc_url", "") or w.get("search_url", ""),
                "determinants": determinants,
                "det_count": len(determinants),
                "changes": (changes_of(rr) if changes_of else []) or [],
                "mp_impact": mp_impact,
                # Out of the settlement team's scope: classified but doesn't touch
                # Market Protocols / SUG (e.g. RR773, Tariff-only). Shown muted.
                "out_of_scope": mp_impact is False and rr_class != "",
                "market_initiative": initiative,
                "market_initiative_citation": w.get("market_initiative_citation", ""),
                "initiative_hint": hint,
                "story_url": (story_url_of(rr) if story_url_of else "") or "",
                "last_updated": (w.get("last_seen") or "")[:10],
                "first_seen": (w.get("first_seen") or "")[:10],
                "mentions": [
                    {
                        "kind": m.get("kind", ""),
                        "label": m.get("label", ""),
                        "date": m.get("meeting_date", "") or "undated",
                        "initiative": m.get("initiative", ""),
                        "citation": m.get("initiative_citation", ""),
                        "candidate": m.get("candidate", ""),
                    }
                    for m in history
                ],
            }
        )
    # Open RRs on top (the active work), then closed; each newest-updated first.
    rows.sort(key=lambda r: (r["status"] != "open", _neg_date(r["last_updated"]), _rr_key(r["rr_number"])))
    return rows


def _rr_key(rr_number: str) -> int:
    return int(rr_number) if rr_number.isdigit() else 0


def _neg_date(date: str) -> str:
    # Sort descending by ISO date using a stable string transform (no reverse=).
    return "".join(chr(255 - ord(c)) for c in date)


def summarize(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Headline counts for the stat row."""
    return {
        "total": len(rows),
        "open": sum(1 for r in rows if r["status"] == "open"),
        "closed": sum(1 for r in rows if r["status"] != "open"),
        "settlement_calc": sum(1 for r in rows if r["rr_class"] == "SETTLEMENT_CALC"),
        "with_initiative": sum(1 for r in rows if r["market_initiative"]),
        "with_story": sum(1 for r in rows if r["story_url"]),
    }


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SPP RR Control</title>
<style>
  :root{
    --ink:#11161d; --ink-soft:#3a4350; --paper:#f7f8fa; --card:#ffffff;
    --line:#e2e6ec; --line-strong:#c6ccd6; --muted:#6b7585; --accent:#1f4e8c;
    --open:#1f7a4d; --open-bg:#e8f5ee; --closed:#6b7585; --closed-bg:#eef1f5;
    --sc:#1f4e8c; --sr:#b4630a; --tg:#6b7585; --un:#9a2b2b;
    --flag:#9a2b2b; --flag-bg:#fbecec; --init-bg:#f2f6fc;
  }
  *{box-sizing:border-box;}
  body{margin:0; background:var(--paper); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    line-height:1.5; font-size:15px;}
  .wrap{max-width:1080px; margin:0 auto; padding:0 22px 64px;}
  a{color:var(--accent); text-decoration:none; border-bottom:1px solid rgba(31,78,140,.32);}
  a:hover{border-bottom-color:var(--accent);}
  header.mast{border-top:5px solid var(--ink); background:var(--card);
    margin:0 -22px 0; padding:30px 22px 20px; border-bottom:1px solid var(--line);}
  .eyebrow{font-size:11.5px; letter-spacing:.16em; text-transform:uppercase; color:var(--muted); font-weight:700;}
  h1{font-size:29px; line-height:1.12; margin:8px 0 4px;}
  .mast .sub{color:var(--ink-soft); font-size:15px; margin-top:6px;}
  .mast .meta{display:flex; flex-wrap:wrap; gap:8px 18px; margin-top:16px; font-size:13px; color:var(--muted);}
  .mast .meta b{color:var(--ink); font-weight:600;}
  .stats{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:24px 0 8px;}
  .stat{background:var(--card); border:1px solid var(--line); border-top:3px solid var(--accent);
    border-radius:10px; padding:13px 15px;}
  .stat .n{font-size:26px; font-weight:700; line-height:1; font-variant-numeric:tabular-nums;}
  .stat .l{font-size:12px; color:var(--muted); margin-top:5px; text-transform:uppercase; letter-spacing:.05em;}
  .tabs{display:flex; gap:4px; margin:22px 0 0; border-bottom:2px solid var(--ink);}
  .tab{appearance:none; border:0; background:transparent; cursor:pointer; font:inherit; font-weight:600;
    font-size:14.5px; color:var(--muted); padding:12px 16px 10px; border-bottom:3px solid transparent; margin-bottom:-2px;}
  .tab:hover{color:var(--ink-soft);}
  .tab[aria-selected="true"]{color:var(--ink); border-bottom-color:var(--accent);}
  .tab:focus-visible{outline:2px solid var(--accent); outline-offset:2px; border-radius:4px;}
  .panel{display:none;} .panel.active{display:block;}
  .det-rr{margin-top:14px; border:1px solid var(--line); border-radius:10px; overflow:hidden;}
  .det-rr .rrhead{width:100%; display:flex; align-items:baseline; gap:10px; text-align:left;
    appearance:none; border:0; background:var(--card); cursor:pointer; font:inherit;
    padding:13px 15px; border-bottom:1px solid transparent;}
  .det-rr .rrhead:hover{background:#f9fbfd;}
  .det-rr.open .rrhead{border-bottom-color:var(--line);}
  .det-rr .rrhead .caret{color:var(--muted); transition:transform .12s; font-size:12px;}
  .det-rr.open .rrhead .caret{transform:rotate(90deg);}
  .det-rr h3{font-size:15.5px; margin:0;}
  .det-rr .rttl{color:var(--muted); font-size:13px; flex:1;}
  .det-rr .cnt{color:var(--muted); font-size:12px; white-space:nowrap;}
  .det-body{display:none; padding:0 15px 14px;}
  .det-rr.open .det-body{display:block;}
  .det-rr .meta2{font-size:12.5px; color:var(--muted); margin:12px 0 0;}
  .dtab{width:100%; border-collapse:collapse; margin-top:10px; background:var(--card); border:1px solid var(--line); border-radius:8px; overflow:hidden;}
  .dtab th{text-align:left; font-size:10.5px; letter-spacing:.04em; text-transform:uppercase; color:var(--muted); font-weight:700; padding:8px 10px; background:#fbfcfd; border-bottom:1px solid var(--line-strong);}
  .dtab td{padding:8px 10px; border-top:1px solid var(--line); font-size:13px; vertical-align:top;}
  .dtab td.pg{white-space:nowrap; font-variant-numeric:tabular-nums; color:var(--accent); font-weight:600;}
  .dtab td.det{white-space:nowrap;} .dtab td.num{color:var(--muted); font-variant-numeric:tabular-nums;}
  .dtab .sec{display:block; font-size:10.5px; color:var(--muted); margin-top:3px;}
  .fml{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:11.5px;
    color:var(--ink); white-space:pre-wrap; word-break:break-word; line-height:1.45;}
  .det-scroll{overflow-x:auto;}
  table{width:100%; border-collapse:collapse; margin-top:14px; background:var(--card);
    border:1px solid var(--line); border-radius:10px; overflow:hidden;}
  thead th{text-align:left; font-size:11.5px; letter-spacing:.05em; text-transform:uppercase;
    color:var(--muted); font-weight:700; padding:11px 12px; background:#fbfcfd; border-bottom:2px solid var(--ink);}
  tbody td{padding:12px; border-top:1px solid var(--line); font-size:14px; vertical-align:top;}
  tbody tr.rr-row{cursor:pointer;}
  tbody tr.rr-row:hover{background:#f9fbfd;}
  .rrid{font-weight:700; font-variant-numeric:tabular-nums; white-space:nowrap;}
  .rrid .dom{display:block; font-size:10.5px; color:var(--muted); font-weight:600; margin-top:2px;}
  .ttl{color:var(--ink); max-width:340px;}
  .ttl .wg{display:block; font-size:11.5px; color:var(--muted); margin-top:3px;}
  .pill{display:inline-block; font-size:11px; font-weight:700; padding:2px 8px; border-radius:20px; white-space:nowrap;}
  .st-open{background:var(--open-bg); color:var(--open);} .st-closed{background:var(--closed-bg); color:var(--closed);}
  .cls{display:inline-block; font-size:11px; font-weight:700; padding:2px 8px; border-radius:4px; white-space:nowrap;}
  .cls-sc{background:#e7eefa; color:var(--sc);} .cls-sr{background:#fbf0e2; color:var(--sr);}
  .cls-tg{background:#eef1f5; color:var(--tg);} .cls-un{background:#fbecec; color:var(--un);}
  .dets{display:block; font-size:11px; color:var(--muted); margin-top:3px;}
  .scope{display:inline-block; font-size:10px; font-weight:700; padding:1px 6px; border-radius:4px;
    background:var(--flag-bg); color:var(--flag); margin-top:4px;}
  tr.rr-row.oos td{background:#fcfcfd;} tr.rr-row.oos .ttl, tr.rr-row.oos .rrid{opacity:.62;}
  .detcode{display:inline-block; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
    font-size:11.5px; background:#eef2f7; color:var(--accent); border:1px solid var(--line);
    border-radius:4px; padding:1px 6px; margin:0 5px 5px 0; white-space:nowrap;}
  .init{color:var(--ink);} .init .cite{display:block; font-size:11px; color:var(--muted); margin-top:2px;}
  .blank{color:var(--muted); font-style:italic;}
  .hint{font-size:12.5px; color:var(--muted); margin:16px 0 0; display:flex; align-items:center; gap:6px;}
  .exp{border-top:0 !important;}
  .exp-inner{display:none; padding:2px 12px 16px;}
  tr.open .exp-inner{display:block;}
  .exp-inner h4{font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin:10px 0 8px;}
  .tl{border-left:2px solid var(--line-strong); margin:0 0 0 6px; padding:0;}
  .tl-row{display:grid; grid-template-columns:96px 74px 1fr; gap:12px; padding:8px 0 8px 16px;
    position:relative; border-bottom:1px solid var(--line); font-size:13.5px;}
  .tl-row:last-child{border-bottom:0;}
  .tl-row:before{content:""; position:absolute; left:-7px; top:12px; width:10px; height:10px;
    border-radius:50%; background:#fff; border:2px solid var(--accent);}
  .tl-date{font-weight:700; color:var(--ink); font-variant-numeric:tabular-nums;}
  .tl-kind{font-size:11px; font-weight:700; color:var(--muted);}
  .tl-init b{color:var(--ink);}
  .tl-init .cite{color:var(--muted); font-size:11.5px;}
  .caret{display:inline-block; width:12px; color:var(--muted); transition:transform .12s;}
  tr.open .caret{transform:rotate(90deg);}
  footer{margin-top:30px; padding-top:16px; border-top:2px solid var(--ink); font-size:12px; color:var(--muted);}
  @media (max-width:720px){ .ttl{max-width:none;} table{font-size:13px;} h1{font-size:23px;} }
</style>
</head>
<body>
<div class="wrap">
  <header class="mast">
    <div class="eyebrow">PCI Energy Solutions &middot; {{ meta.market }}</div>
    <h1>{{ meta.title }}</h1>
    <div class="sub">Every Revision Request the settlement team is tracking &mdash; open and recently closed &mdash; with its class, market initiative, and CUF/SUF mention history.</div>
    <div class="meta">
      <span><b>Generated:</b> {{ meta.generated }}</span>
      <span><b>Market:</b> {{ meta.market }}</span>
      {% if meta.state_note %}<span>{{ meta.state_note }}</span>{% endif %}
    </div>
  </header>

  <div class="stats">
    <div class="stat"><div class="n">{{ stats.total }}</div><div class="l">Watched RRs</div></div>
    <div class="stat"><div class="n">{{ stats.open }}</div><div class="l">Open</div></div>
    <div class="stat"><div class="n">{{ stats.settlement_calc }}</div><div class="l">Settlement calc</div></div>
    <div class="stat"><div class="n">{{ stats.with_initiative }}</div><div class="l">With initiative</div></div>
    <div class="stat"><div class="n">{{ stats.with_story }}</div><div class="l">With story</div></div>
  </div>

  <div class="tabs" role="tablist" aria-label="RR control views">
    <button class="tab" role="tab" id="tab-control" aria-controls="panel-control" aria-selected="true">Control</button>
    <button class="tab" role="tab" id="tab-dets" aria-controls="panel-dets" aria-selected="false">Determinants</button>
  </div>

  <div class="panel active" id="panel-control" role="tabpanel" aria-labelledby="tab-control">
  <p class="hint"><span class="caret" style="color:var(--accent);">&#9656;</span> Tap any row to see the CUF/SUF mention history behind its initiative. Charge-code determinants are on the <b>Determinants</b> tab.</p>

  <table>
    <thead>
      <tr>
        <th>RR</th><th>Title</th><th>Class / scope</th><th>Status</th><th>Market initiative</th><th>Story</th><th>Updated</th>
      </tr>
    </thead>
    <tbody>
      {% for r in rows %}
      <tr class="rr-row{{ ' oos' if r.out_of_scope }}" data-rr="{{ r.rr_number }}">
        <td class="rrid">{% if r.rr_url %}<a href="{{ r.rr_url }}" onclick="event.stopPropagation();">RR{{ r.rr_number }}</a>{% else %}RR{{ r.rr_number }}{% endif %}{% if r.domain %}<span class="dom">{{ r.domain }}</span>{% endif %}</td>
        <td class="ttl"><span class="caret">&#9656;</span> {{ r.title }}{% if r.working_group %}<span class="wg">{{ r.working_group }}</span>{% endif %}</td>
        <td>
          <span class="cls cls-{{ r.class_code }}" title="{{ r.class_blurb }}">{{ r.class_label }}</span>
          {% if r.out_of_scope %}<span class="scope" title="Does not check Market Protocols / Settlement User Guide — outside the settlement team's scope.">no MP impact</span>{% endif %}
          {% if r.det_count %}<span class="dets">{{ r.det_count }} charge code{{ 's' if r.det_count != 1 }}</span>{% endif %}
        </td>
        <td><span class="pill st-{{ 'open' if r.status == 'open' else 'closed' }}">{{ r.status }}</span></td>
        <td class="init">
          {% if r.market_initiative %}{{ r.market_initiative }}
            {% if r.market_initiative_citation %}<span class="cite">{{ r.market_initiative_citation }}</span>{% endif %}
          {% else %}<span class="blank">not named</span>
            {% if r.initiative_hint %}<span class="cite">nearby: {{ r.initiative_hint }} (hint, not confirmed)</span>{% endif %}
          {% endif %}
        </td>
        <td>{% if r.story_url %}<a href="{{ r.story_url }}">open</a>{% else %}<span class="blank">&mdash;</span>{% endif %}</td>
        <td style="white-space:nowrap; color:var(--muted); font-variant-numeric:tabular-nums;">{{ r.last_updated }}</td>
      </tr>
      <tr class="exp" data-exp="{{ r.rr_number }}">
        <td class="exp-inner" colspan="7">
          <h4>CUF/SUF mention history ({{ r.mentions|length }})</h4>
          {% if r.mentions %}
          <div class="tl">
            {% for m in r.mentions %}
            <div class="tl-row">
              <div class="tl-date">{{ m.date }}</div>
              <div class="tl-kind">{{ m.kind }}</div>
              <div class="tl-init">
                {% if m.initiative %}<b>{{ m.initiative }}</b>{% if m.citation %} <span class="cite">&middot; {{ m.citation }}</span>{% endif %}
                {% else %}<span class="blank">mentioned; no initiative named</span>{% if m.candidate %} <span class="cite">&middot; nearby: {{ m.candidate }}</span>{% endif %}{% endif %}
                {% if m.label %}<div class="cite">{{ m.label }}</div>{% endif %}
              </div>
            </div>
            {% endfor %}
          </div>
          {% else %}
          <p class="blank">No CUF/SUF mentions recorded yet (seeded from the ledger, or discovered via the master list).</p>
          {% endif %}
          <div style="margin-top:10px; font-size:12px; color:var(--muted);">First seen {{ r.first_seen or 'unknown' }}.</div>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="7" class="blank" style="padding:24px; text-align:center;">No RRs are being watched yet. Run <code>python main.py run</code> to seed the watch list.</td></tr>
      {% endfor %}
    </tbody>
  </table>
  </div>

  <div class="panel" id="panel-dets" role="tabpanel" aria-labelledby="tab-dets">
    <p class="hint">The charge-code changes each <b>Settlement calc</b> RR makes, with the Recommendation-Report page for each — the same per-item detail as the settlement Excel. (Tariff / no-MP RRs change no formulas, so they don't appear here.)</p>
    {% for r in rows if r.rr_class == 'SETTLEMENT_CALC' and not r.out_of_scope %}
    <div class="det-rr" data-det="{{ r.rr_number }}">
      <button class="rrhead" aria-expanded="false" aria-controls="detbody-{{ r.rr_number }}">
        <span class="caret">&#9656;</span>
        <h3>RR{{ r.rr_number }}</h3>
        <span class="rttl">{{ r.title }}</span>
        <span class="cnt">{{ r.det_count }} determinant{{ 's' if r.det_count != 1 }}</span>
      </button>
      <div class="det-body" id="detbody-{{ r.rr_number }}">
      <p class="meta2">
        {%- if r.market_initiative %}{{ r.market_initiative }}{% else %}initiative not named{% endif %}
        {%- if r.status != 'open' %} &middot; {{ r.status }}{% endif %}</p>
      {% if r.changes %}
      <div class="det-scroll">
      <table class="dtab">
        <thead><tr><th style="width:34px;">#</th><th style="width:150px;">Determinant</th><th>Formula before</th><th>Formula after</th><th style="width:52px;">Page</th></tr></thead>
        <tbody>
          {% for c in r.changes %}
          <tr>
            <td class="num">{{ loop.index }}</td>
            <td class="det"><span class="detcode">{{ c.determinant }}</span>{% if c.section %}<span class="sec">SUG {{ c.section }}</span>{% endif %}</td>
            <td>{% if c.formula_before %}<code class="fml">{{ c.formula_before }}</code>{% else %}<span class="blank">new</span>{% endif %}</td>
            <td>{% if c.formula_after %}<code class="fml">{{ c.formula_after }}</code>{% else %}<span class="blank">removed</span>{% endif %}</td>
            <td class="pg">{% if c.page is not none %}p.{{ c.page }}{% else %}&mdash;{% endif %}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      </div>
      {% elif r.determinants %}
      <div>{% for d in r.determinants %}<span class="detcode">{{ d }}</span>{% endfor %}</div>
      <p class="blank" style="margin-top:8px;">Determinant codes only — per-item pages appear here after a settlement-report run generates this RR's story.</p>
      {% else %}
      <p class="blank">No # determinant tokens detected — thin RR (e.g. CHILL); review the Recommendation Report directly.</p>
      {% endif %}
      </div>
    </div>
    {% else %}
    <p class="blank" style="padding:16px 0;">No in-scope Settlement-calc RRs yet (RRs that affect Market Protocols / SUG appear here).</p>
    {% endfor %}
  </div>

  <footer>
    SPP RR Control &mdash; persistent watch-list snapshot. Classes and initiatives are derived from the
    Recommendation Reports and CUF/SUF materials the tool has parsed; verify time-sensitive items against
    the SPP Revision Requests site. This snapshot accumulates: each generation is kept, never overwritten.
  </footer>
</div>
<script>
  (function(){
    var tabs = Array.prototype.slice.call(document.querySelectorAll('.tab'));
    function selectTab(tab){
      tabs.forEach(function(t){
        var on = t === tab;
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        document.getElementById(t.getAttribute('aria-controls')).classList.toggle('active', on);
      });
    }
    tabs.forEach(function(t, i){
      t.addEventListener('click', function(){ selectTab(t); });
      t.addEventListener('keydown', function(e){
        if(e.key==='ArrowRight'||e.key==='ArrowLeft'){
          e.preventDefault();
          var next = tabs[(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length];
          next.focus(); selectTab(next);
        }
      });
    });
    var rows = Array.prototype.slice.call(document.querySelectorAll('tr.rr-row'));
    rows.forEach(function(row){
      row.addEventListener('click', function(){
        var rr = row.getAttribute('data-rr');
        var exp = document.querySelector('tr.exp[data-exp="'+rr+'"]');
        var isOpen = row.classList.contains('open');
        row.classList.toggle('open', !isOpen);
        if(exp){ exp.classList.toggle('open', !isOpen); }
      });
    });
    var dets = Array.prototype.slice.call(document.querySelectorAll('.det-rr .rrhead'));
    dets.forEach(function(head){
      head.addEventListener('click', function(){
        var box = head.parentNode;
        var open = box.classList.toggle('open');
        head.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    });
  })();
</script>
</body>
</html>"""


def render_rr_control(rows: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    env = Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
    template = env.from_string(_TEMPLATE)
    return template.render(rows=rows, stats=summarize(rows), meta=meta)
