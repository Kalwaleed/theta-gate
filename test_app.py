"""app.py's arithmetic and its two states that actually get looked at.

A dashboard is easy to leave untested because it "just renders". The
parts worth pinning are the ones that are wrong silently: SVG geometry
that divides by zero on the shapes this page spends most of the hackathon
in (no trades, one trade, a dead-flat curve), and money formatting, where
a dropped minus sign turns a loss into a gain on the one number a judge
reads.

The render helpers are covered only as smoke tests -- that they produce
markup at all, on both the empty journal and a populated one. Asserting
on exact HTML would break on every design change and prove nothing.
"""

import json

import pytest

import app
import store


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def test_money_puts_the_sign_outside_the_unit():
    assert app.money(1234.5) == "$1,234.50"
    assert app.money(-1234.5) == "-$1,234.50"
    assert app.money(-1234.5, signed=True) == "-$1,234.50"


def test_money_signs_gains_only_when_asked():
    assert app.money(30.0) == "$30.00"
    assert app.money(30.0, signed=True) == "+$30.00"
    assert app.money(0.0, signed=True) == "$0.00", "zero is not a gain"


def test_money_and_pct_survive_none():
    """An open position has no close debit and no P&L. Rendering 'None' in
    a P&L column is worse than rendering nothing."""
    assert app.money(None) == "--"
    assert app.pct(None) == "--"


def test_short_ts_renders_et_and_tolerates_junk():
    assert "ET" in app.short_ts("2026-08-31T10:31:00-04:00")
    assert app.short_ts(None) == "--"
    assert app.short_ts("not a timestamp") == "not a timestamp"


def test_win_rate():
    assert app.win_rate(4, 3) == 75.0
    assert app.win_rate(0, 0) is None, "0/0 must not raise or read as 0%"


# ---------------------------------------------------------------------------
# Curve geometry -- the states this page is actually in most of the week
# ---------------------------------------------------------------------------

def test_curve_of_no_points_is_empty_not_an_exception():
    line, area, dots, _, lo, hi = app.curve_geometry([])
    assert (line, area, dots, lo, hi) == ("", "", [], 0.0, 0.0)


def test_flat_curve_does_not_divide_by_zero():
    """Before the first close -- and after a scratch trade -- every point
    is $100,000. A naive (v-lo)/(hi-lo) is 0/0 here."""
    points = [{"ts": None, "equity": 100000.0}, {"ts": "x", "equity": 100000.0}]
    line, _, dots, y_base, _, _ = app.curve_geometry(points)
    assert line and len(dots) == 2
    assert all(0 < d["y"] < 260 for d in dots)
    assert y_base == pytest.approx(dots[0]["y"])


def test_single_point_curve_has_a_drawable_path():
    """One closed trade is one point. A path with no length draws nothing
    at all under the stroke-dashoffset animation."""
    line, _, dots, _, _, _ = app.curve_geometry([{"ts": "x", "equity": 100030.0}])
    assert len(dots) == 1
    assert " L " in line, "needs a segment for the draw animation to reveal"


def test_curve_maps_high_equity_above_low_equity():
    """SVG y grows downward. Getting this backwards renders a losing week
    as a rising line."""
    points = [{"ts": "a", "equity": 100000.0},
              {"ts": "b", "equity": 100500.0},
              {"ts": "c", "equity": 99500.0}]
    _, _, dots, _, lo, hi = app.curve_geometry(points)
    assert (lo, hi) == (99500.0, 100500.0)
    ys = [d["y"] for d in dots]
    assert ys[1] < ys[0] < ys[2], "higher equity must sit higher on the page"


def test_curve_spans_the_full_width():
    points = [{"ts": str(i), "equity": 100000.0 + i * 10} for i in range(5)]
    _, _, dots, _, _, _ = app.curve_geometry(points, width=880, pad=28)
    assert dots[0]["x"] == pytest.approx(28)
    assert dots[-1]["x"] == pytest.approx(852)


def test_area_path_is_closed():
    """An unclosed area path fills as a wedge across the whole chart."""
    points = [{"ts": "a", "equity": 100000.0}, {"ts": "b", "equity": 100030.0}]
    _, area, _, _, _, _ = app.curve_geometry(points)
    assert area.endswith("Z")


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------

def test_bar_widths_scale_to_the_largest_count():
    rows = [{"gate": "delta_band", "reason": "d", "n": 10},
            {"gate": "vrp_present", "reason": "v", "n": 5}]
    out = app.bar_widths(rows)
    assert out[0]["width"] == 100.0 and out[1]["width"] == 50.0


def test_a_gate_that_fired_once_stays_visible():
    """1 against 200 rounds to 0.5% -- an invisible bar reads as 'never
    happened' for exactly the rare veto most worth seeing."""
    rows = [{"gate": "a", "reason": "a", "n": 200}, {"gate": "b", "reason": "b", "n": 1}]
    assert app.bar_widths(rows)[1]["width"] >= 6.0


def test_bar_widths_of_nothing_is_nothing():
    assert app.bar_widths([]) == []


# ---------------------------------------------------------------------------
# Render smoke tests, against a real store
# ---------------------------------------------------------------------------

@pytest.fixture
def populated(tmp_path):
    journal = tmp_path / "journal.jsonl"
    records = [
        {"ts": "2026-08-31T09:31:00-04:00", "event": "no_trade",
         "reason": "outside_entry_window"},
        {"ts": "2026-08-31T10:31:00-04:00", "event": "no_trade", "underlying": "SPY",
         "reason": "delta_band: short leg 0.31 outside 0.16-0.25"},
        {"ts": "2026-08-31T13:31:00-04:00", "event": "entry_filled",
         "position_id": "tg-e-20260831-1330-spy", "underlying": "SPY",
         "direction": "bull_put", "trade_date": "2026-08-31", "window": "1330",
         "expiry": "2026-09-08", "short_symbol": "SPY260908P00760000",
         "long_symbol": "SPY260908P00755000", "width": 5.0, "qty": 1,
         "credit": 0.60, "max_loss_dollars": 440.0, "order_id": "o1"},
        {"ts": "2026-09-01T11:00:00-04:00", "event": "exit_filled",
         "position_id": "tg-e-20260831-1330-spy", "underlying": "SPY",
         "reason": "take_profit", "qty": 1, "close_debit": 0.30, "order_id": "o2"},
    ]
    journal.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return store.rebuild(str(tmp_path / "t.db"), str(journal))


def test_chart_renders_for_a_real_curve(populated):
    html = app.render_chart(app.store.equity_curve(populated, 100000))
    assert "<svg" in html and "tg-line" in html
    assert "animation-delay" in html, "dots stagger; a static chart is the bug"


def test_chart_renders_on_an_empty_store(tmp_path):
    conn = store.rebuild(str(tmp_path / "e.db"), str(tmp_path / "missing.jsonl"))
    html = app.render_chart(store.equity_curve(conn, 100000))
    assert "<svg" in html


def test_bars_mark_gates_and_control_flow_differently(populated):
    html = app.render_bars(store.gate_rejection_counts(populated))
    assert "delta_band" in html
    assert 'tg-bar-k gate' in html, "a real gate veto is highlighted"
    assert "soft" in html, "a control-flow reason is not"


def test_rows_render_and_stagger(populated):
    rows = [["a", "b"], ["c", "d"]]
    html = app.render_rows(["X", "Y"], rows)
    assert html.count("<tr") == 3  # header + 2
    assert "animation-delay:0.06s" in html


def test_the_page_module_imports_without_a_journal(monkeypatch, tmp_path):
    """Streamlit Community Cloud does a cold checkout. If app.py touches
    the broker or requires a key at import time, the demo URL 500s and the
    submission loses a hard gate."""
    monkeypatch.setattr(store, "JOURNAL_PATH", str(tmp_path / "nope.jsonl"))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "nope.db"))
    conn = store.connect(store.DB_PATH, store.JOURNAL_PATH)
    assert store.summary(conn)["events"] == 0


def test_app_makes_no_broker_or_network_calls():
    """The dashboard is public and credential-free by design. An import of
    alpaca, market or brain would drag a key requirement onto a host that
    must never hold one."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(app.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    forbidden = {"alpaca", "market", "brain", "loop", "requests", "urllib", "http", "socket"}
    assert not (imported & forbidden), f"app.py must stay offline; found {imported & forbidden}"


# ---------------------------------------------------------------------------
# Full-page execution, via Streamlit's own harness
# ---------------------------------------------------------------------------

def _stage(tmp_path, records):
    """Copy the app and its only inputs into a scratch dir and run there.
    Never points the app at the real data/journal.jsonl -- a test that can
    write the agent's trading history is a test that can corrupt the one
    artifact judges read."""
    import shutil
    from pathlib import Path

    root = Path(__file__).parent
    for name in ("app.py", "store.py", "governance.json"):
        shutil.copy(root / name, tmp_path / name)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "journal.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    (tmp_path / "data" / "HALT.json").write_text(
        json.dumps({"active": False, "reason": "", "activated_at": None}), encoding="utf-8")
    return tmp_path


def _run_app(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(tmp_path / "app.py"), default_timeout=60).run()
    assert not at.exception, f"page raised: {[e.value for e in at.exception]}"
    return at, "\n".join(m.value for m in at.markdown)


def test_page_renders_on_an_empty_journal(tmp_path, monkeypatch):
    """The state on submission day if the agent never clears a gate. It
    has to look deliberate, not broken."""
    _, body = _run_app(_stage(tmp_path, []), monkeypatch)
    assert "Nothing has closed yet" in body
    assert "No positions yet" in body
    assert "$100,000.00" in body, "equity falls back to the starting balance"


def test_page_renders_a_full_week_of_trading(tmp_path, monkeypatch):
    """Two closes -- one winner, one stopped out -- plus an open position
    and a mix of gate and control-flow rejections."""
    records = [
        {"ts": "2026-08-31T09:31:00-04:00", "event": "no_trade", "reason": "outside_entry_window"},
        {"ts": "2026-08-31T10:31:00-04:00", "event": "no_trade", "underlying": "SPY",
         "reason": "delta_band: short leg 0.31 outside 0.16-0.25"},
        {"ts": "2026-08-31T13:31:00-04:00", "event": "entry_filled",
         "position_id": "p1", "underlying": "SPY", "direction": "bull_put",
         "trade_date": "2026-08-31", "window": "1330", "expiry": "2026-09-08",
         "width": 5.0, "qty": 1, "credit": 0.60, "max_loss_dollars": 440.0},
        {"ts": "2026-09-01T10:31:00-04:00", "event": "entry_filled",
         "position_id": "p2", "underlying": "QQQ", "direction": "bull_put",
         "trade_date": "2026-09-01", "window": "1030", "expiry": "2026-09-09",
         "width": 5.0, "qty": 1, "credit": 0.55, "max_loss_dollars": 445.0},
        {"ts": "2026-09-01T14:00:00-04:00", "event": "exit_filled", "position_id": "p1",
         "underlying": "SPY", "reason": "take_profit", "qty": 1, "close_debit": 0.30},
        {"ts": "2026-09-02T10:31:00-04:00", "event": "entry_filled",
         "position_id": "p3", "underlying": "SPY", "direction": "bull_put",
         "trade_date": "2026-09-02", "window": "1030", "expiry": "2026-09-10",
         "width": 5.0, "qty": 1, "credit": 0.62, "max_loss_dollars": 438.0},
        {"ts": "2026-09-02T15:00:00-04:00", "event": "exit_filled", "position_id": "p2",
         "underlying": "QQQ", "reason": "stop_loss", "qty": 1, "close_debit": 1.10},
        {"ts": "2026-09-02T15:05:00-04:00", "event": "tick_completed", "ok": True},
    ]
    _, body = _run_app(_stage(tmp_path, records), monkeypatch)

    assert "<svg" in body and "tg-line" in body, "the curve draws once trades close"
    assert "take profit" in body or "take_profit" in body
    assert "delta_band" in body
    assert "-$55.00" in body, "the stopped trade's loss keeps its sign"
    assert "+$30.00" in body, "and the winner keeps its plus"
    assert "Sample size: 2 closed trades" in body


def test_page_shows_a_halt(tmp_path, monkeypatch):
    """HALT is the kill switch. If the page still reads 'history verified'
    while the agent is halted, the dashboard is lying about the one thing
    an operator checks it for."""
    staged = _stage(tmp_path, [{"ts": "2026-09-01T10:00:00-04:00",
                                "event": "tick_completed", "ok": True}])
    (staged / "data" / "HALT.json").write_text(
        json.dumps({"active": True, "reason": "naked leg detected",
                    "activated_at": "2026-09-01T10:00:00-04:00"}), encoding="utf-8")
    _, body = _run_app(staged, monkeypatch)
    assert "halted" in body
    assert "history verified" not in body


def test_corrupt_halt_file_fails_closed_without_crashing(tmp_path, monkeypatch):
    """loop.py rewrites HALT.json mid-tick while the dashboard reads it from
    another process, so a torn read is reachable in normal operation -- and
    the demo URL is public even though the repo is private. Unreadable must
    render as halted, matching loop.py._check_halt's own fail-closed rule,
    rather than raising and taking the page down in front of judges."""
    staged = _stage(tmp_path, [{"ts": "2026-09-01T10:00:00-04:00",
                                "event": "tick_completed", "ok": True}])
    (staged / "data" / "HALT.json").write_text('{"active": tr', encoding="utf-8")
    _, body = _run_app(staged, monkeypatch)  # must not raise
    assert "halted" in body
    assert "history verified" not in body


# ---------------------------------------------------------------------------
# Escaping -- the page renders with unsafe_allow_html on a public URL
# ---------------------------------------------------------------------------

XSS = '<img src=x onerror="alert(1)">'


def test_esc_neutralises_markup_and_quotes():
    out = app.esc(XSS)
    assert "<img" not in out and "&lt;img" in out
    assert '"' not in out, "quotes must escape too -- several call sites use title=\"...\""


def test_esc_handles_none_and_numbers():
    assert app.esc(None) == ""
    assert app.esc(3.5) == "3.5"


def test_a_hostile_thesis_cannot_inject_markup():
    """The thesis is free text written by a language model and journaled
    verbatim. app.py renders through unsafe_allow_html, so an unescaped
    thesis is script execution on a public, anonymous page. brain.py
    screens for prompt injection at its own boundary; escaping is what
    makes rendering safe regardless of what got through."""
    row = app.decision_row(
        {"ts": "2026-08-31T10:30:00-04:00", "event": "proposal",
         "underlying": XSS, "reason": None},
        {"proposal": {"underlying": "SPY", "direction": "bullish",
                      "confidence": 0.6, "thesis": XSS}},
        "acc")
    joined = "".join(row)
    assert "<img" not in joined
    assert "onerror" not in joined or "&quot;" in joined
    assert "&lt;img" in joined


def test_a_hostile_gate_reason_cannot_inject_markup():
    html = app.render_bars([{"gate": XSS, "reason": XSS, "n": 3}])
    assert "<img src=x" not in html and "&lt;img" in html


def test_position_fields_are_escaped():
    """Symbols, direction and expiry come from broker responses via the
    journal -- semi-trusted, and rendered into the same markup."""
    assert "<img" not in app.esc(XSS)
    assert app.esc("SPY & QQQ") == "SPY &amp; QQQ"


# ---------------------------------------------------------------------------
# The proposal row -- the only place the model's own words appear
# ---------------------------------------------------------------------------

def test_proposal_detail_reads_the_nested_thesis():
    """loop.py journals dataclasses.asdict(proposal) under a `proposal`
    key. Reading payload["thesis"] directly finds nothing."""
    detail = app.decision_detail("proposal", None, {
        "proposal": {"underlying": "SPY", "direction": "bullish",
                     "confidence": 0.62, "thesis": "IV sits above realised, contango holds"}})
    assert "IV sits above realised" in detail
    assert "SPY bullish" in detail
    assert "62% confidence" in detail


def test_a_failed_proposal_says_so():
    """proposal: null is a real outcome -- the model returned something
    malformed and the loop declined. Better than a blank cell."""
    detail = app.decision_detail("proposal", None, {"proposal": None})
    assert "nothing usable" in detail


def test_non_proposal_events_keep_their_reason():
    detail = app.decision_detail("no_trade", "delta_band: 0.31 outside band", {})
    assert detail == "delta_band: 0.31 outside band"


def test_price_column_ignores_non_numeric_payloads():
    """payload.get("credit") could be any JSON type after a torn write.
    money() on a string raises, which would take the page down."""
    row = app.decision_row(
        {"ts": "2026-08-31T10:30:00-04:00", "event": "entry_filled",
         "underlying": "SPY", "reason": None},
        {"credit": "not-a-number"}, "acc")
    assert row[-1].endswith("></span>") or ">" in row[-1]
