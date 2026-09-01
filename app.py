"""The Streamlit dashboard -- the hackathon's hosted-demo deliverable.

Two constraints shape every decision in this file.

**It must work with the market shut and with no credentials.** Judges
review off-hours, and Streamlit Community Cloud gets no Alpaca keys and
no Anthropic key -- deliberately, since a public dashboard holding a
broker credential would undo the argument the rest of the repo makes.
So this file makes zero network calls. It reads `data/journal.jsonl`
through `store.py` and nothing else. Everything shown here is history the
agent committed to git itself.

**The primary view is history, not live state.** A live-state dashboard
is blank at 3am on a Sunday, which is exactly when it gets looked at.

Design: pure CSS animation and inline SVG, no `<script>` -- Streamlit
strips script tags from `st.markdown`, and `components.html` would sandbox
each block in its own fixed-height iframe. Everything here animates with
keyframes, `stroke-dashoffset`, and staggered `animation-delay`, which
degrades to a static, still-legible page if a browser refuses any of it.

Palette and type match `docs/diagrams/*.html` so the deck, the diagrams
and the demo read as one artifact.
"""

import html
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

import store

ET = ZoneInfo("America/New_York")
GOVERNANCE_PATH = "governance.json"

# Lifted from docs/diagrams/architecture.html so the three artifacts match.
INK = "#0B0D0F"
PAPER = "#F5F5F5"
ACCENT = "#3F2AC1"
MUTED = "#5B5B5B"
SOFT = "#838BA0"
WIN = "#1F7A5C"
LOSS = "#B3261E"


# ---------------------------------------------------------------------------
# Pure helpers -- no Streamlit, no I/O. test_app.py covers these.
# ---------------------------------------------------------------------------

def esc(value):
    """HTML-escape anything journal-derived before it reaches the page.

    app.py renders through `st.markdown(unsafe_allow_html=True)`, so any
    string interpolated into that markup is live HTML. Most journal
    strings are code-controlled gate messages, but two are not: the
    proposer's `thesis` and `invalidation` are free text written by a
    language model, and broker responses supply symbols and reasons. A
    thesis containing a bare `<` renders broken; one containing a tag
    executes, on a page that will be public and anonymous.

    brain.py already screens proposals for prompt injection, which is the
    right guard at that boundary and the wrong one at this boundary --
    escaping here is what makes the rendering safe regardless of what
    upstream let through. Quotes are escaped too, since several call
    sites interpolate into `title="..."`.
    """
    return html.escape("" if value is None else str(value), quote=True)


def money(value, signed=False):
    """`-$1,234.50`, not `$-1234.5`. The minus belongs outside the unit."""
    if value is None:
        return "--"
    sign = "-" if value < 0 else ("+" if signed and value > 0 else "")
    return f"{sign}${abs(value):,.2f}"


def pct(value, digits=1):
    return "--" if value is None else f"{value:.{digits}f}%"


def short_ts(ts):
    """Journal timestamps are ET-offset ISO strings. Judges read dates, not
    offsets."""
    if not ts:
        return "--"
    try:
        return datetime.fromisoformat(ts).astimezone(ET).strftime("%a %d %b, %H:%M ET")
    except (TypeError, ValueError):
        return str(ts)


def curve_geometry(points, width=880, height=260, pad=28):
    """Map an equity curve onto SVG coordinates.

    Returns (line_d, area_d, dots, y_baseline, lo, hi). Kept pure and
    separate from rendering because the awkward cases are arithmetic, not
    presentation: a single point has no x-range to divide by, and a
    perfectly flat curve has no y-range -- both of which are the *normal*
    state of this dashboard until the first trade closes.
    """
    if not points:
        return "", "", [], height / 2, 0.0, 0.0

    values = [p["equity"] for p in points]
    lo, hi = min(values), max(values)
    span = hi - lo
    if span <= 0:
        # Flat line: centre it rather than dividing by zero. A curve at a
        # constant $100,000 is what a judge sees before the first close.
        span, lo = 1.0, lo - 0.5

    inner_w, inner_h = width - 2 * pad, height - 2 * pad
    n = len(points)

    def x_of(i):
        return pad if n == 1 else pad + (i / (n - 1)) * inner_w

    def y_of(v):
        return pad + inner_h - ((v - lo) / span) * inner_h

    coords = [(x_of(i), y_of(v)) for i, v in enumerate(values)]
    line_d = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in coords)
    if n == 1:
        # One point is a dot, not a line -- give it a hairline so the draw
        # animation has something to reveal.
        line_d = f"M {coords[0][0]:.2f} {coords[0][1]:.2f} L {coords[0][0] + 0.01:.2f} {coords[0][1]:.2f}"

    area_d = (f"{line_d} L {coords[-1][0]:.2f} {height - pad:.2f}"
              f" L {coords[0][0]:.2f} {height - pad:.2f} Z")

    dots = [
        {"x": x, "y": y, "point": p}
        for (x, y), p in zip(coords, points)
    ]
    return line_d, area_d, dots, y_of(values[0]), lo, hi


def bar_widths(rows, minimum=6.0):
    """Normalise gate-rejection counts to percentage bar widths. The
    minimum keeps a count of 1 visible next to a count of 200 -- a gate
    that fired once is still a gate that fired."""
    if not rows:
        return []
    top = max(r["n"] for r in rows) or 1
    return [
        {**r, "width": max(minimum, round(100 * r["n"] / top, 2))}
        for r in rows
    ]


def win_rate(closed, wins):
    return None if not closed else round(100 * wins / closed, 1)


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');

:root {
  --ink:#0B0D0F; --paper:#F5F5F5; --accent:#3F2AC1; --muted:#5B5B5B;
  --soft:#838BA0; --rule:rgba(11,13,15,0.10); --win:#1F7A5C; --loss:#B3261E;
  --sans:'IBM Plex Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  --mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
}

/* Strip Streamlit's chrome. The page should not look like a Streamlit app. */
#MainMenu, footer, header[data-testid="stHeader"] {visibility:hidden; height:0;}
.stDeployButton {display:none;}
.block-container {padding:3.5rem 2rem 5rem; max-width:1120px;}
html, body, [class*="css"] {font-family:var(--sans);}
.stApp {background:var(--paper);}

@keyframes rise {
  from {opacity:0; transform:translateY(14px);}
  to   {opacity:1; transform:translateY(0);}
}
@keyframes draw   {to {stroke-dashoffset:0;}}
@keyframes pop    {from {opacity:0; transform:scale(0);} to {opacity:1; transform:scale(1);}}
@keyframes grow   {from {width:0;}}
@keyframes fade   {from {opacity:0;} to {opacity:1;}}
@keyframes pulse  {
  0%,100% {opacity:1; transform:scale(1);}
  50%     {opacity:.35; transform:scale(.82);}
}

.tg-rise {animation:rise .62s cubic-bezier(.22,.9,.28,1) both;}

/* Masthead ------------------------------------------------------------- */
.tg-mast {display:flex; align-items:baseline; gap:16px; flex-wrap:wrap;
  border-bottom:1px solid var(--rule); padding-bottom:20px; margin-bottom:38px;}
.tg-word {font-family:var(--mono); font-size:13px; letter-spacing:.42em;
  text-transform:uppercase; color:var(--ink); font-weight:500;}
.tg-tag {font-size:13px; color:var(--muted); flex:1; min-width:220px; line-height:1.5;}
.tg-pill {display:inline-flex; align-items:center; gap:7px; font-family:var(--mono);
  font-size:10.5px; letter-spacing:.12em; text-transform:uppercase;
  padding:5px 11px; border-radius:999px; border:1px solid var(--rule);
  background:#fff; color:var(--muted); white-space:nowrap;}
.tg-dot {width:6px; height:6px; border-radius:50%; background:var(--win);
  animation:pulse 2.4s ease-in-out infinite;}
.tg-dot.bad {background:var(--loss);}

/* Metric row ----------------------------------------------------------- */
.tg-metrics {display:grid; grid-template-columns:repeat(auto-fit,minmax(168px,1fr));
  gap:1px; background:var(--rule); border:1px solid var(--rule); margin-bottom:44px;}
.tg-metric {background:#fff; padding:22px 20px 20px; transition:background .25s ease;}
.tg-metric:hover {background:#FCFCFD;}
.tg-metric .k {font-family:var(--mono); font-size:9.5px; letter-spacing:.15em;
  text-transform:uppercase; color:var(--soft); margin-bottom:11px;}
.tg-metric .v {font-size:27px; font-weight:300; letter-spacing:-.02em;
  color:var(--ink); font-variant-numeric:tabular-nums; line-height:1.1;}
.tg-metric .v.win {color:var(--win);} .tg-metric .v.loss {color:var(--loss);}
.tg-metric .s {font-size:11.5px; color:var(--soft); margin-top:7px;}

/* Section headers ------------------------------------------------------ */
.tg-h {font-family:var(--mono); font-size:10.5px; letter-spacing:.2em;
  text-transform:uppercase; color:var(--ink); margin:0 0 6px;}
.tg-sub {font-size:12.5px; color:var(--muted); margin:0 0 18px; line-height:1.55; max-width:70ch;}
.tg-section {margin-bottom:52px;}

/* Chart ---------------------------------------------------------------- */
.tg-chart {background:#fff; border:1px solid var(--rule); padding:8px 6px 4px;}
.tg-chart svg {display:block; width:100%; height:auto;}
.tg-line {fill:none; stroke:var(--accent); stroke-width:1.75;
  stroke-linecap:round; stroke-linejoin:round;
  stroke-dasharray:3000; stroke-dashoffset:3000;
  animation:draw 1.9s cubic-bezier(.22,.9,.28,1) .25s forwards;}
.tg-area {fill:url(#tgGrad); opacity:0; animation:fade 1.1s ease 1.1s forwards;}
.tg-base {stroke:var(--soft); stroke-width:1; stroke-dasharray:2 5; opacity:.55;}
.tg-dot-m {fill:#fff; stroke:var(--accent); stroke-width:1.75;
  opacity:0; animation:pop .42s cubic-bezier(.34,1.56,.64,1) forwards;}
.tg-axis {font-family:var(--mono); font-size:9.5px; fill:var(--soft);}

/* Bars ----------------------------------------------------------------- */
.tg-bar-row {display:grid; grid-template-columns:minmax(150px,210px) 1fr 46px;
  gap:14px; align-items:center; padding:9px 0; border-bottom:1px solid var(--rule);}
.tg-bar-row:last-child {border-bottom:none;}
.tg-bar-k {font-family:var(--mono); font-size:11px; color:var(--ink);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.tg-bar-k.gate {color:var(--accent);}
.tg-bar-track {height:5px; background:rgba(11,13,15,.05); border-radius:3px; overflow:hidden;}
.tg-bar-fill {height:100%; background:var(--accent); border-radius:3px; opacity:.82;
  animation:grow .95s cubic-bezier(.22,.9,.28,1) both;}
.tg-bar-fill.soft {background:var(--soft);}
.tg-bar-n {font-family:var(--mono); font-size:11.5px; color:var(--muted);
  text-align:right; font-variant-numeric:tabular-nums;}

/* Tables --------------------------------------------------------------- */
.tg-tbl {width:100%; border-collapse:collapse; background:#fff;
  border:1px solid var(--rule); font-size:12.5px;}
.tg-tbl th {font-family:var(--mono); font-size:9.5px; letter-spacing:.13em;
  text-transform:uppercase; color:var(--soft); text-align:left; font-weight:400;
  padding:12px 14px; border-bottom:1px solid var(--rule); white-space:nowrap;}
.tg-tbl td {padding:12px 14px; border-bottom:1px solid var(--rule);
  color:var(--ink); vertical-align:top;}
.tg-tbl tbody tr {animation:rise .5s cubic-bezier(.22,.9,.28,1) both;
  transition:background .18s ease;}
.tg-tbl tbody tr:hover {background:#FBFBFD;}
.tg-tbl tbody tr:last-child td {border-bottom:none;}
.tg-num {font-family:var(--mono); font-variant-numeric:tabular-nums; white-space:nowrap;}
.tg-win {color:var(--win);} .tg-loss {color:var(--loss);}
.tg-sym {font-family:var(--mono); font-size:11px; color:var(--muted);}
.tg-tag-s {display:inline-block; font-family:var(--mono); font-size:9.5px;
  letter-spacing:.09em; text-transform:uppercase; padding:2.5px 7px;
  border:1px solid var(--rule); border-radius:3px; color:var(--muted); white-space:nowrap;}
.tg-tag-s.acc {color:var(--accent); border-color:rgba(63,42,193,.3);}
.tg-tag-s.bad {color:var(--loss); border-color:rgba(179,38,30,.3);}

/* Empty state ---------------------------------------------------------- */
.tg-empty {background:#fff; border:1px solid var(--rule); padding:44px 34px; text-align:center;}
.tg-empty .t {font-size:15px; color:var(--ink); margin-bottom:9px; font-weight:400;}
.tg-empty .d {font-size:12.5px; color:var(--muted); max-width:56ch;
  margin:0 auto; line-height:1.65;}

/* Footer --------------------------------------------------------------- */
.tg-foot {border-top:1px solid var(--rule); padding-top:22px; margin-top:14px;
  font-size:11.5px; color:var(--soft); line-height:1.7;}
.tg-foot b {color:var(--muted); font-weight:500;}

/* Streamlit expander, de-Streamlit-ified */
div[data-testid="stExpander"] {border:1px solid var(--rule); border-radius:0; background:#fff;}
div[data-testid="stExpander"] summary {font-family:var(--mono); font-size:10.5px;
  letter-spacing:.14em; text-transform:uppercase; color:var(--ink);}
</style>
"""


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_chart(points):
    line_d, area_d, dots, y_base, lo, hi = curve_geometry(points)
    dot_svg = "".join(
        f'<circle class="tg-dot-m" cx="{d["x"]:.2f}" cy="{d["y"]:.2f}" r="3.6"'
        f' style="animation-delay:{1.25 + i * 0.11:.2f}s"><title>'
        f'{esc(short_ts(d["point"]["ts"]) if d["point"]["ts"] else "session start")} -- '
        f'{money(d["point"]["equity"])}</title></circle>'
        for i, d in enumerate(dots)
    )
    return f"""
<div class="tg-chart tg-rise" style="animation-delay:.1s">
  <svg viewBox="0 0 880 260" preserveAspectRatio="none" role="img"
       aria-label="Realised equity curve">
    <defs><linearGradient id="tgGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{ACCENT}" stop-opacity=".13"/>
      <stop offset="100%" stop-color="{ACCENT}" stop-opacity="0"/>
    </linearGradient></defs>
    <line class="tg-base" x1="28" y1="{y_base:.2f}" x2="852" y2="{y_base:.2f}"/>
    <path class="tg-area" d="{area_d}"/>
    <path class="tg-line" d="{line_d}"/>
    {dot_svg}
    <text class="tg-axis" x="28" y="16">{money(hi)}</text>
    <text class="tg-axis" x="28" y="254">{money(lo)}</text>
  </svg>
</div>"""


def render_bars(rows, accent_gates=True):
    out = []
    for i, r in enumerate(bar_widths(rows)):
        is_gate = r.get("gate") and r["gate"] != "other"
        label = r["gate"] if is_gate else r["reason"]
        detail = r["reason"] if is_gate else ""
        out.append(f"""
<div class="tg-bar-row">
  <div class="tg-bar-k {'gate' if is_gate and accent_gates else ''}" title="{esc(detail or label)}">{esc(label)}</div>
  <div class="tg-bar-track"><div class="tg-bar-fill {'' if is_gate else 'soft'}"
       style="width:{r['width']}%; animation-delay:{0.15 + i * 0.07:.2f}s"></div></div>
  <div class="tg-bar-n">{r['n']}</div>
</div>""")
    return f'<div class="tg-rise" style="animation-delay:.12s">{"".join(out)}</div>'


def render_rows(headers, rows):
    """One table renderer for positions and the decision log. `rows` is a
    list of lists of pre-formatted HTML cells."""
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join(
        f'<tr style="animation-delay:{0.06 * i:.2f}s">'
        + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
        for i, row in enumerate(rows)
    )
    return f'<table class="tg-tbl tg-rise"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def decision_detail(event, reason, payload):
    """The one human-readable line for a journal event.

    `proposal` is the only place the model's own words appear anywhere in
    this system, so it gets the thesis. loop.py nests it under a
    `proposal` key (it journals `dataclasses.asdict(proposal)`), not at
    the top level -- reading `payload["thesis"]` directly, as an earlier
    version did, silently found nothing and left the column blank on
    exactly the rows where the AI is visible.

    A failed proposal has `proposal: null`, which is a real outcome worth
    showing rather than an empty cell: it means the model returned
    something malformed and the loop declined to trade on it.
    """
    if event == "proposal":
        p = payload.get("proposal")
        if not p:
            return "model returned nothing usable — no trade"
        thesis = p.get("thesis") or ""
        conf = p.get("confidence")
        head = f'{p.get("underlying", "?")} {p.get("direction", "?")}'
        if isinstance(conf, (int, float)):
            head += f' ({conf:.0%} confidence)'
        return f"{head} — {thesis}" if thesis else head
    return reason or payload.get("note") or ""


def decision_row(event_row, payload, tag_cls):
    """Build one escaped decision-log row. Every interpolated value here
    is journal-derived and therefore untrusted at render time."""
    detail = decision_detail(event_row["event"], event_row["reason"], payload)
    clipped = detail[:88] + ("..." if len(detail) > 88 else "")
    price = payload.get("credit", payload.get("close_debit"))
    return [
        f'<span class="tg-sym">{esc(short_ts(event_row["ts"]))}</span>',
        f'<span class="tg-tag-s {tag_cls}">{esc(event_row["event"].replace("_", " "))}</span>',
        esc(event_row["underlying"] or "--"),
        f'<span title="{esc(detail)}">{esc(clipped)}</span>',
        f'<span class="tg-num">{money(price) if isinstance(price, (int, float)) else ""}</span>',
    ]


def section(title, subtitle=""):
    sub = f'<p class="tg-sub">{subtitle}</p>' if subtitle else ""
    st.markdown(f'<div class="tg-section"><p class="tg-h">{title}</p>{sub}',
                unsafe_allow_html=True)


def end_section():
    st.markdown("</div>", unsafe_allow_html=True)


def empty(title, detail):
    st.markdown(f'<div class="tg-empty tg-rise"><div class="t">{title}</div>'
                f'<div class="d">{detail}</div></div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def load(journal_mtime):
    """Cached on the journal's mtime, so a pushed tick refreshes the page
    on next load but a judge clicking around doesn't rebuild every time.
    The argument is the cache key -- it is intentionally unused."""
    conn = store.connect()
    gov = json.loads(Path(GOVERNANCE_PATH).read_text(encoding="utf-8"))
    start = gov["risk"]["starting_equity_dollars"]
    return {
        "summary": store.summary(conn, starting_equity=start),
        "curve": store.equity_curve(conn, starting_equity=start),
        "gates": store.gate_rejection_counts(conn),
        "log": store.decision_log(conn, limit=120),
        "positions": [dict(r) for r in conn.execute(
            "SELECT * FROM positions ORDER BY entry_ts DESC")],
        "gov": gov,
        "start": start,
    }


def main():
    st.set_page_config(page_title="Theta Gate", page_icon="Θ", layout="wide",
                       initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)

    journal = Path(store.JOURNAL_PATH)
    mtime = journal.stat().st_mtime if journal.exists() else 0
    d = load(mtime)
    s, gov = d["summary"], d["gov"]

    # A corrupt or half-written HALT.json must not take the page down: the
    # file is rewritten by loop.py mid-tick and read here from a separate
    # process, so a torn read is reachable in normal operation. Unreadable
    # is treated as halted -- same fail-closed rule loop.py._check_halt
    # uses, and the safer way to be wrong in front of judges.
    halted = False
    halt_file = Path("data/HALT.json")
    if halt_file.exists():
        try:
            halted = bool(json.loads(halt_file.read_text(encoding="utf-8")).get("active"))
        except (OSError, ValueError):
            halted = True
    ok = s["chain_intact"] and not halted
    status = "halted" if halted else ("history verified" if s["chain_intact"] else "chain broken")

    # Masthead ---------------------------------------------------------------
    st.markdown(f"""
<div class="tg-mast tg-rise">
  <div class="tg-word">Theta&nbsp;Gate</div>
  <div class="tg-tag">An autonomous options agent on Alpaca paper. The model proposes a
    direction and nothing else &mdash; every strike, size and exit is deterministic Python,
    and a pure-function risk guard has the last word.</div>
  <div class="tg-pill"><span class="tg-dot {'' if ok else 'bad'}"></span>{status}</div>
</div>""", unsafe_allow_html=True)

    # Metrics ----------------------------------------------------------------
    realised = s["realised_pnl_dollars"]
    wr = win_rate(s["positions_closed"], s["wins"])
    tone = "win" if realised > 0 else ("loss" if realised < 0 else "")
    cards = [
        ("Equity", money(s["equity"]), f"from {money(d['start'])} start", ""),
        ("Realised P&L", money(realised, signed=True),
         f"{s['positions_closed']} closed", tone),
        ("Unrealised", money(s["unrealised_pnl_dollars"], signed=True),
         f"{s['positions_open']} open, marked to last tick",
         "win" if s["unrealised_pnl_dollars"] > 0 else ("loss" if s["unrealised_pnl_dollars"] < 0 else "")),
        ("Open now", str(s["positions_open"]),
         f"cap {gov['risk']['max_concurrent_positions']}", ""),
        ("Win rate", pct(wr), f"{s['wins']} of {s['positions_closed']}"
         if s["positions_closed"] else "no closes yet", ""),
        ("Sessions", str(len(s["sessions"])), "of six", ""),
        ("Journal", f"{s['events']:,}", "events, hash-chained", ""),
    ]
    st.markdown('<div class="tg-metrics tg-rise" style="animation-delay:.06s">' + "".join(
        f'<div class="tg-metric"><div class="k">{k}</div>'
        f'<div class="v {t}">{v}</div><div class="s">{sub}</div></div>'
        for k, v, sub, t in cards) + "</div>", unsafe_allow_html=True)

    # Equity -----------------------------------------------------------------
    section("Equity", "Realised only, one point per closed position. Deliberately not "
            "marked to market: Alpaca posts paper non-trade activity the next day, so an "
            "intraday unrealised number built from this journal would be quietly wrong.")
    if len(d["curve"]) > 1:
        st.markdown(render_chart(d["curve"]), unsafe_allow_html=True)
    else:
        empty("Nothing has closed yet",
              "The curve starts once the first spread is closed. Until then the honest "
              "number is the starting balance, and drawing a line through one point would "
              "imply a track record that does not exist.")
    end_section()

    # Positions --------------------------------------------------------------
    open_pos = [p for p in d["positions"] if p["status"] == "open"]
    closed = [p for p in d["positions"] if p["status"] == "closed"]

    section("Positions", "Every spread the agent opened, with the credit it actually "
            "received rather than the one it quoted for.")
    if d["positions"]:
        rows = []
        for p in open_pos + closed:
            # An open position has no realised P&L but does have a mark:
            # loop.py journals exit_evaluated every tick it holds one.
            # Showing "--" there hid a number the journal already had.
            live = p["status"] == "open"
            pnl = p["unrealised_pnl_dollars"] if live else p["realised_pnl_dollars"]
            debit = p["latest_mark"] if live else p["close_debit"]
            cls = "tg-win" if (pnl or 0) > 0 else ("tg-loss" if (pnl or 0) < 0 else "")
            state = ('<span class="tg-tag-s acc">open</span>' if p["status"] == "open"
                     else f'<span class="tg-tag-s">'
                          f'{esc((p["exit_reason"] or "closed").replace("_", " "))}</span>')
            rows.append([
                f'<b>{esc(p["underlying"])}</b><div class="tg-sym">{esc(p["direction"] or "")}</div>',
                f'{esc(short_ts(p["entry_ts"]))}<div class="tg-sym">exp {esc(p["expiry"] or "--")}</div>',
                f'<span class="tg-num">{esc(str(p["qty"] if p["qty"] is not None else "--"))}</span>',
                f'<span class="tg-num">{money(p["credit"])}</span>',
                f'<span class="tg-num">{money(debit)}</span>'
                + ('<div class="tg-sym">mark</div>' if live and debit is not None else ''),
                f'<span class="tg-num">{money(p["max_loss_dollars"])}</span>',
                state,
                f'<span class="tg-num {cls}">{money(pnl, signed=True)}</span>'
                + ('<div class="tg-sym">unrealised</div>' if live and pnl is not None else ''),
            ])
        st.markdown(render_rows(
            ["Underlying", "Entered", "Qty", "Credit", "Close debit", "Max loss", "State", "P&L"],
            rows), unsafe_allow_html=True)
    else:
        empty("No positions yet",
              "The agent has not found a spread that clears every gate. The panel below "
              "shows which gate stopped each candidate -- that is the system working, not "
              "the system idle.")
    end_section()

    # Why no trade -----------------------------------------------------------
    section("Why no trade",
            "Every rejection the agent journaled, counted. Indigo rows are risk-guard "
            "vetoes on a real candidate; grey rows are the loop declining to look at all "
            "&mdash; outside an entry window, already at the daily cap, halted.")
    if d["gates"]:
        st.markdown(render_bars(d["gates"]), unsafe_allow_html=True)
    else:
        empty("Nothing rejected yet", "No no-trade decision has been journaled.")
    end_section()

    # Decision log -----------------------------------------------------------
    section("Decision log", "Newest first. Routine tick heartbeats are filtered out; "
            "everything that changed a position, or declined to, is here.")
    if d["log"]:
        rows = []
        for e in d["log"][:60]:
            payload = e["payload"]
            tag_cls = "bad" if e["level"] in ("critical", "warning") else (
                "acc" if e["event"].endswith("_filled") else "")
            rows.append(decision_row(e, payload, tag_cls))
        st.markdown(render_rows(["When", "Event", "Symbol", "Detail", "Price"], rows),
                    unsafe_allow_html=True)
    else:
        empty("The journal is empty", "No ticks have been recorded yet.")
    end_section()

    # Governance -------------------------------------------------------------
    section("Governance", "Every risk number the agent enforces, rendered verbatim from "
            "governance.json. No LLM can write to this file &mdash; brain.py cannot import "
            "the broker, the store, or json.dump against this path, and it runs with no "
            "tools at all.")
    with st.expander("governance.json"):
        st.json(gov, expanded=False)
    end_section()

    n = s["positions_closed"]
    st.markdown(f"""
<div class="tg-foot">
  <b>Sample size: {n} closed trade{'' if n == 1 else 's'} across {len(s['sessions'])}
  session{'' if len(s['sessions']) == 1 else 's'}.</b> That is not enough to demonstrate
  edge, and this page does not claim any. The strategy harvests a documented structural
  premium &mdash; index implied vol has historically exceeded realised &mdash; under a hard,
  defined loss cap. Over six sessions the result is noise around that thesis, and the
  number worth judging is whether the risk guard held, not the sign of the P&amp;L.<br/>
  Paper trading only. Read from the agent's own committed journal
  (<span class="tg-sym">data/journal.jsonl</span>, {s['events']:,} events,
  chain {'intact' if s['chain_intact'] else f"BROKEN at {s['chain_first_bad_seq']}"}).
  This page makes no broker calls and holds no credentials.
</div>""", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
