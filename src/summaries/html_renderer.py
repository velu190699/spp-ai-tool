"""Render a validated ReportData into the self-contained two-tab HTML report.

The engine only ever produces structured data; all layout lives here so the HTML
is identical across runs and testable against a fixed fixture. Output is clean
UTF-8 (no mojibake) and autoescaped.
"""
from __future__ import annotations

from jinja2 import Environment

from src.summaries.report_model import ReportData

# Map area keys to the short CSS codes used by the stylesheet.
_AREA_CODE = {
    "market_systems": "ms",
    "asset_operations": "ao",
    "transmissions": "tx",
    "etrm": "et",
    "optimization": "op",
}

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SPP Market Changes Summary</title>
<style>
  :root{
    --ink:#11161d; --ink-soft:#3a4350; --paper:#f7f8fa; --card:#ffffff;
    --line:#e2e6ec; --line-strong:#c6ccd6; --muted:#6b7585; --accent:#1f4e8c;
    --c-ms:#1f4e8c; --c-ao:#1f7a4d; --c-tx:#b4630a; --c-et:#6b3fa0; --c-op:#0f7c86;
    --impact:#b4630a; --impact-bg:#fff6e8; --flag:#9a2b2b; --flag-bg:#fbecec;
  }
  *{box-sizing:border-box;}
  body{margin:0; background:var(--paper); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    line-height:1.55; font-size:15.5px;}
  .wrap{max-width:960px; margin:0 auto; padding:0 22px 64px;}
  a{color:var(--accent); text-decoration:none; border-bottom:1px solid rgba(31,78,140,.32);}
  a:hover{border-bottom-color:var(--accent);}
  header.mast{border-top:5px solid var(--ink); background:var(--card);
    margin:0 -22px 0; padding:30px 22px 20px; border-bottom:1px solid var(--line);}
  .eyebrow{font-size:11.5px; letter-spacing:.16em; text-transform:uppercase; color:var(--muted); font-weight:700;}
  h1{font-size:30px; line-height:1.12; margin:8px 0 4px;}
  .mast .sub{color:var(--ink-soft); font-size:15px; margin-top:6px;}
  .mast .meta{display:flex; flex-wrap:wrap; gap:8px 18px; margin-top:16px; font-size:13px; color:var(--muted);}
  .mast .meta b{color:var(--ink); font-weight:600;}
  .provenance{margin:0 -22px; padding:13px 22px; background:var(--flag-bg);
    border-bottom:1px solid #f0d4d4; font-size:13px; color:#5e1f1f;}
  .provenance b{color:var(--flag);}
  .tabs{position:sticky; top:0; z-index:5; display:flex; gap:4px; margin:0 -22px;
    padding:0 22px; background:var(--paper); border-bottom:2px solid var(--ink);}
  .tab{appearance:none; border:0; background:transparent; cursor:pointer; font:inherit;
    font-weight:600; font-size:14.5px; color:var(--muted); padding:14px 16px 12px;
    border-bottom:3px solid transparent; margin-bottom:-2px;}
  .tab:hover{color:var(--ink-soft);}
  .tab[aria-selected="true"]{color:var(--ink); border-bottom-color:var(--accent);}
  .tab:focus-visible{outline:2px solid var(--accent); outline-offset:2px; border-radius:4px;}
  .panel{display:none;} .panel.active{display:block;}
  section{margin-top:26px;}
  .sec-head{display:flex; align-items:baseline; gap:12px; border-bottom:2px solid var(--ink); padding-bottom:7px; margin-bottom:6px;}
  .sec-head h2{font-size:20px; margin:0;}
  .sec-note{color:var(--ink-soft); font-size:14px; margin:8px 0 16px;}
  .glance{display:grid; grid-template-columns:repeat(auto-fit,minmax(270px,1fr)); gap:14px; margin:14px 0 0;}
  .gcard{position:relative; text-align:left; background:var(--card); border:1px solid var(--line);
    border-top:3px solid var(--accent); border-radius:10px; padding:15px 17px 40px; cursor:pointer;
    font:inherit; color:inherit; transition:box-shadow .15s, border-color .15s; width:100%;}
  .gcard:hover{box-shadow:0 3px 12px rgba(17,22,29,.08);}
  .gcard:focus-visible{outline:2px solid var(--accent); outline-offset:2px;}
  .gcard.g-ms{border-top-color:var(--c-ms);} .gcard.g-ao{border-top-color:var(--c-ao);}
  .gcard.g-tx{border-top-color:var(--c-tx);} .gcard.g-et{border-top-color:var(--c-et);}
  .gcard.g-op{border-top-color:var(--c-op);}
  .gcard h3{font-size:15px; margin:0 0 7px; display:flex; align-items:center; gap:8px;}
  .gdot{width:9px; height:9px; border-radius:50%; flex:0 0 auto;}
  .g-ms .gdot{background:var(--c-ms);} .g-ao .gdot{background:var(--c-ao);}
  .g-tx .gdot{background:var(--c-tx);} .g-et .gdot{background:var(--c-et);} .g-op .gdot{background:var(--c-op);}
  .gcard p{font-size:13.5px; color:var(--ink-soft); margin:0 0 9px;}
  .gk{font-size:12.5px; color:var(--muted); display:flex; gap:6px; padding:3px 0; border-top:1px solid var(--line);}
  .gk:first-of-type{border-top:0;}
  .gk b{color:var(--ink); font-weight:700; white-space:nowrap;}
  .gcard .more{position:absolute; left:17px; bottom:12px; font-size:12px; font-weight:700; color:var(--accent);}
  .detail{display:none; margin-top:16px; border:1px solid var(--line); border-left:4px solid var(--accent);
    border-radius:6px; background:var(--card); padding:16px 20px 14px;}
  .detail.active{display:block;}
  .detail.d-ms{border-left-color:var(--c-ms);} .detail.d-ao{border-left-color:var(--c-ao);}
  .detail.d-tx{border-left-color:var(--c-tx);} .detail.d-et{border-left-color:var(--c-et);} .detail.d-op{border-left-color:var(--c-op);}
  .detail h3{font-size:16px; margin:0 0 4px;}
  .detail .dsub{font-size:12.5px; color:var(--muted); margin:0 0 10px;}
  .detail ul{list-style:none; margin:0; padding:0;}
  .detail li{padding:10px 0; border-top:1px solid var(--line); font-size:14px;}
  .detail li:first-child{border-top:0;}
  .ftag{display:inline-block; font-size:10px; font-weight:700; letter-spacing:.03em; padding:1px 6px;
    border-radius:4px; background:#eef1f5; color:var(--muted); margin-right:6px; white-space:nowrap;}
  .src{display:block; font-size:11.5px; color:var(--muted); margin-top:3px;}
  .narr{font-size:15px; color:#2c3744; line-height:1.62;}
  .narr h4{font-size:16px; color:var(--ink); margin:20px 0 6px;}
  .narr h4:first-of-type{margin-top:6px;}
  .narr p{margin:0 0 10px;}
  .impact{font-size:12.5px; background:var(--impact-bg); border-left:3px solid var(--impact);
    padding:6px 10px; border-radius:0 4px 4px 0; margin:4px 0 12px; color:#5b4708;}
  .impact b{color:var(--impact);}
  .narr .src{font-size:12px; margin-top:-2px; margin-bottom:12px;}
  .timeline{border-left:2px solid var(--line-strong); margin:14px 0 0 6px;}
  .tl-row{display:grid; grid-template-columns:120px 1fr; gap:14px; padding:9px 0 9px 16px; position:relative; border-bottom:1px solid var(--line);}
  .tl-row:before{content:""; position:absolute; left:-7px; top:15px; width:10px; height:10px; border-radius:50%; background:#fff; border:2px solid var(--accent);}
  .tl-row.past:before{background:var(--line-strong); border-color:var(--line-strong);}
  .tl-date{font-weight:700; font-size:13px; color:var(--ink); font-variant-numeric:tabular-nums;}
  .tl-what{font-size:14px; color:#2c3744;}
  footer{margin-top:30px; padding-top:16px; border-top:2px solid var(--ink); font-size:12px; color:var(--muted);}
  @media (max-width:560px){ h1{font-size:24px;} .tabs{overflow-x:auto;} .tab{white-space:nowrap;} }
</style>
</head>
<body>
<div class="wrap">
  <header class="mast">
    <div class="eyebrow">PCI Energy Solutions &middot; SPP Market Intelligence</div>
    <h1>SPP Market Changes Summary</h1>
    <div class="sub">What's changing in the SPPIM market this cycle &mdash; for all PCI teams</div>
    <div class="meta">
      <span><b>Generated:</b> {{ meta.generated }}</span>
      <span><b>Sources:</b>
        {%- if meta.cuf_url or meta.suf_url %}
          {%- if meta.cuf_url %} <a href="{{ meta.cuf_url }}">CUF{% if meta.cuf_date %} {{ meta.cuf_date }}{% endif %}</a>{% elif meta.cuf_date %} CUF {{ meta.cuf_date }}{% endif %}
          {%- if (meta.cuf_url or meta.cuf_date) and (meta.suf_url or meta.suf_date) %} &middot;{% endif %}
          {%- if meta.suf_url %} <a href="{{ meta.suf_url }}">SUF{% if meta.suf_date %} {{ meta.suf_date }}{% endif %}</a>{% elif meta.suf_date %} SUF {{ meta.suf_date }}{% endif %}
        {%- else %} {{ meta.sources_line }}{% endif %}
      </span>
    </div>
  </header>

  <div class="provenance">
    <b>Provenance.</b>
    Read this cycle: {{ meta.files_read|join(', ') if meta.files_read else 'see sources' }}.
    {% if meta.files_skipped %}Not read:
      {% for f in meta.files_skipped %}{{ f.name }} ({{ f.reason }}){{ ", " if not loop.last }}{% endfor %}.
    {% endif %}
  </div>

  <div class="tabs" role="tablist" aria-label="Report sections">
    <button class="tab" role="tab" id="tab-exec" aria-controls="panel-exec" aria-selected="true">Executive Overview</button>
    <button class="tab" role="tab" id="tab-full" aria-controls="panel-full" aria-selected="false">Full Summary</button>
  </div>

  <div class="panel active" id="panel-exec" role="tabpanel" aria-labelledby="tab-exec">
    <section>
      <div class="sec-head"><h2>Changes at a Glance</h2></div>
      <p class="sec-note">A quick read of what's coming, by area. <b>Tap any card</b> to open that area's detail below.</p>
      <div class="glance">
        {% for area in areas %}
        <button class="gcard g-{{ codes[area.key] }}" data-area="{{ codes[area.key] }}" aria-expanded="false" aria-controls="detail-{{ codes[area.key] }}">
          <h3><span class="gdot"></span>{{ area.name }}</h3>
          <p>{{ area.summary }}</p>
          {% set ns = namespace(count=0) %}
          {% for item in area.items %}{% for d in item.dates %}{% if ns.count < 3 %}
          <div class="gk"><b>{{ d.label or item.title }}:</b> {{ d.value }}</div>
          {% set ns.count = ns.count + 1 %}{% endif %}{% endfor %}{% endfor %}
          <span class="more">View detail</span>
        </button>
        {% endfor %}
      </div>

      {% for area in areas %}
      <div class="detail d-{{ codes[area.key] }}" id="detail-{{ codes[area.key] }}">
        <h3>{{ area.name }} &mdash; detail</h3>
        <p class="dsub">All items tagged to this area this cycle.</p>
        <ul>
          {% for item in area.items %}
          <li>
            {% if item.tag %}<span class="ftag">{{ item.tag }}</span>{% endif %}
            <strong>{{ item.title }}</strong>{% if item.detail %} &mdash; {{ item.detail }}{% endif %}
            {% for s in item.sources %}
            <span class="src">Source: {% if s.url %}<a href="{{ s.url }}">{{ s.label }}</a>{% else %}{{ s.label }}{% endif %}</span>
            {% endfor %}
          </li>
          {% else %}
          <li>No items reported for this area this cycle.</li>
          {% endfor %}
        </ul>
      </div>
      {% endfor %}

      <div class="sec-head" style="margin-top:30px;"><h2>Key Dates &amp; Deadlines</h2></div>
      <div class="timeline">
        {% for row in timeline %}
        <div class="tl-row{{ ' past' if row.past }}">
          <div class="tl-date">{{ row.date }}</div>
          <div class="tl-what">{{ row.label }}</div>
        </div>
        {% endfor %}
      </div>
    </section>
  </div>

  <div class="panel" id="panel-full" role="tabpanel" aria-labelledby="tab-full">
    <section>
      <div class="sec-head"><h2>Full Summary</h2></div>
      <p class="sec-note">Everything reported this cycle from the CUF and SUF, read top to bottom. Items with a direct PCI consequence carry an <b style="color:var(--impact)">Impactful</b> line.</p>
      <div class="narr">
        {% for sec in narrative %}
        <h4>{{ sec.heading }}</h4>
        {% for p in sec.paragraphs %}<p>{{ p }}</p>{% endfor %}
        {% if sec.impact %}<div class="impact"><b>Impactful:</b> {{ sec.impact|replace('Impactful:', '')|trim }}</div>{% endif %}
        {% for s in sec.sources %}
        <p class="src">Source: {% if s.url %}<a href="{{ s.url }}">{{ s.label }}</a>{% else %}{{ s.label }}{% endif %}</p>
        {% endfor %}
        {% endfor %}
      </div>
    </section>
  </div>

  <footer>
    SPP Market Changes Summary. Sources: {{ meta.sources_line }}. Dates and RR statuses are subject to SPP revision;
    verify time-sensitive items against the SPP Revision Requests site and live settlement calendars.
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
          var dir = e.key==='ArrowRight'?1:-1;
          var next = tabs[(i+dir+tabs.length)%tabs.length];
          next.focus(); selectTab(next);
        }
      });
    });
    var cards = Array.prototype.slice.call(document.querySelectorAll('.gcard'));
    var details = Array.prototype.slice.call(document.querySelectorAll('.detail'));
    cards.forEach(function(card){
      card.addEventListener('click', function(){
        var area = card.getAttribute('data-area');
        var target = document.getElementById('detail-'+area);
        var isOpen = card.getAttribute('aria-expanded')==='true';
        cards.forEach(function(c){ c.setAttribute('aria-expanded','false'); c.querySelector('.more').textContent='View detail'; });
        details.forEach(function(d){ d.classList.remove('active'); });
        if(!isOpen){
          card.setAttribute('aria-expanded','true');
          card.querySelector('.more').textContent='Hide detail';
          target.classList.add('active');
          target.scrollIntoView({behavior:'smooth', block:'nearest'});
        }
      });
    });
  })();
</script>
</body>
</html>"""


def render_report(report: ReportData) -> str:
    env = Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
    template = env.from_string(_TEMPLATE)
    return template.render(
        meta=report.meta,
        areas=report.areas,
        timeline=report.timeline,
        narrative=report.narrative,
        codes=_AREA_CODE,
    )
