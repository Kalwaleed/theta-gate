"""store.py: the SQLite read model.

The tests that matter most here are the parity ones. store.py duplicates
four journal scans that loop.py already implements in plain Python, and
loop.py's versions are the ones that decide trades. A SQL rewrite that
silently disagrees -- on ET-vs-UTC session boundaries, on a missing `ok`
field, on which entry_filled wins after a replay -- would be a trading
bug wearing a reporting bug's clothes. So every query function is
asserted against loop.py's answer on the same journal, including the
awkward inputs (torn lines, a UTC-vs-ET date straddle, a re-journaled
position, an exit for a position that never opened).
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import loop
import store

ET = ZoneInfo("America/New_York")


@pytest.fixture
def journal(tmp_path, monkeypatch):
    """A journal path both modules read, so parity assertions compare the
    two implementations on identical bytes."""
    path = tmp_path / "journal.jsonl"
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(path))
    return path


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "theta_gate.db")


def write(path, *records):
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def entry(pid, underlying, ts, credit=0.60, qty=1, width=5.0, **extra):
    return {
        "ts": ts, "event": "entry_filled", "position_id": pid, "underlying": underlying,
        "direction": "bull_put", "trade_date": ts[:10], "window": "1030", "expiry": "2026-09-04",
        "short_symbol": f"{underlying}260904P00760000", "long_symbol": f"{underlying}260904P00755000",
        "width": width, "qty": qty, "credit": credit,
        "max_loss_dollars": round((width - credit) * 100 * qty, 2),
        "order_id": f"ord-{pid}", "client_order_id": f"tg-e-{pid}", "stage": "s0",
        **extra,
    }


def exit_(pid, underlying, ts, debit=0.30, reason="take_profit", **extra):
    return {
        "ts": ts, "event": "exit_filled", "position_id": pid, "underlying": underlying,
        "reason": reason, "qty": 1, "close_debit": debit, "order_id": f"ord-x-{pid}",
        "legs_confirmed_closed": True, **extra,
    }


# ---------------------------------------------------------------------------
# Parity with loop.py -- the reference implementation for every trading read
# ---------------------------------------------------------------------------

def test_open_positions_matches_loop(journal, db):
    write(journal,
          entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00"),
          entry("tg-e-20260831-1330-qqq", "QQQ", "2026-08-31T13:31:00-04:00"),
          exit_("tg-e-20260831-1030-spy", "SPY", "2026-09-01T11:00:00-04:00"))

    conn = store.rebuild(db, str(journal))
    expected = loop._open_positions(loop._read_journal())

    got = store.open_positions(conn)
    assert [p["position_id"] for p in got] == [p["position_id"] for p in expected]
    assert got == expected


def test_open_positions_ignores_exit_for_unknown_position(journal, db):
    """An exit_filled naming a position with no entry_filled must not
    invent a row. loop.py's set-difference shrugs this off; a JOIN-based
    rewrite could easily not."""
    write(journal,
          entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00"),
          exit_("tg-e-19700101-0000-xyz", "XYZ", "2026-08-31T11:00:00-04:00"))

    conn = store.rebuild(db, str(journal))
    assert store.open_positions(conn) == loop._open_positions(loop._read_journal())
    assert conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 1


def test_repeated_entry_filled_yields_one_position(journal, db):
    """A crash-and-replay can journal entry_filled twice for the same
    deterministic client_order_id after the order is adopted. loop.py
    keeps the last one; so must this."""
    write(journal,
          entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00", credit=0.60),
          entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:36:00-04:00", credit=0.62))

    conn = store.rebuild(db, str(journal))
    expected = loop._open_positions(loop._read_journal())
    got = store.open_positions(conn)

    assert len(got) == 1
    assert got == expected
    assert got[0]["credit"] == 0.62


def test_entries_today_matches_loop_across_utc_date_straddle(journal, db):
    """20:30 UTC on 31 Aug is 16:30 ET the same day; 01:00 UTC on 1 Sep is
    21:00 ET on 31 Aug. Both belong to the 31 Aug session. A naive UTC
    date column gets the second one wrong."""
    write(journal,
          entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T20:30:00+00:00"),
          entry("tg-e-20260831-1330-qqq", "QQQ", "2026-09-01T01:00:00+00:00"),
          entry("tg-e-20260901-1030-spy", "SPY", "2026-09-01T14:31:00-04:00"))

    conn = store.rebuild(db, str(journal))
    now = datetime(2026, 8, 31, 15, 0, tzinfo=ET)

    assert store.entries_today(conn, now) == loop._entries_today(loop._read_journal(), now)
    assert store.entries_today(conn, now) == (2, ["SPY", "QQQ"])


def test_consecutive_exceptions_matches_loop(journal, db):
    write(journal,
          {"ts": "2026-08-31T10:00:00-04:00", "event": "tick_completed", "ok": True},
          {"ts": "2026-08-31T10:05:00-04:00", "event": "tick_completed", "ok": False},
          {"ts": "2026-08-31T10:10:00-04:00", "event": "no_trade", "reason": "halt_active"},
          {"ts": "2026-08-31T10:15:00-04:00", "event": "tick_completed", "ok": False})

    conn = store.rebuild(db, str(journal))
    assert store.consecutive_exceptions(conn) == loop._consecutive_exceptions(loop._read_journal()) == 2


def test_consecutive_exceptions_treats_missing_ok_as_true(journal, db):
    """loop.py reads `ok` with a default of True, so a tick_completed
    written without the field breaks the failure run rather than
    extending it. SQL NULL must behave the same way, not be counted as
    falsey."""
    write(journal,
          {"ts": "2026-08-31T10:00:00-04:00", "event": "tick_completed", "ok": False},
          {"ts": "2026-08-31T10:05:00-04:00", "event": "tick_completed"},
          {"ts": "2026-08-31T10:10:00-04:00", "event": "tick_completed", "ok": False})

    conn = store.rebuild(db, str(journal))
    assert store.consecutive_exceptions(conn) == loop._consecutive_exceptions(loop._read_journal()) == 1


def test_exit_attempt_number_matches_loop(journal, db):
    pid = "tg-e-20260831-1030-spy"
    write(journal, entry(pid, "SPY", "2026-08-31T10:31:00-04:00"))
    conn = store.rebuild(db, str(journal))
    assert store.exit_attempt_number(conn, pid) == loop._exit_attempt_number(loop._read_journal(), pid) == 1

    write(journal,
          {"ts": "2026-09-01T11:00:00-04:00", "event": "exit_unfilled", "position_id": pid},
          {"ts": "2026-09-01T11:05:00-04:00", "event": "exit_unfilled", "position_id": "other"})
    conn = store.rebuild(db, str(journal))
    assert store.exit_attempt_number(conn, pid) == loop._exit_attempt_number(loop._read_journal(), pid) == 2


def test_torn_and_blank_lines_skipped_identically(journal, db):
    """A crash mid-append leaves a half-written line. Both readers must
    drop exactly the same lines, or every parity test above is comparing
    two different journals."""
    with open(journal, "w", encoding="utf-8") as f:
        f.write(json.dumps(entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00")) + "\n")
        f.write("\n")
        f.write('{"ts": "2026-08-31T10:32:00-04:00", "event": "entry_fil')  # torn
        f.write("\n")
        f.write(json.dumps({"ts": "2026-08-31T10:33:00-04:00", "event": "tick_completed", "ok": True}) + "\n")

    conn = store.rebuild(db, str(journal))
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == len(loop._read_journal()) == 2
    assert store.open_positions(conn) == loop._open_positions(loop._read_journal())


# ---------------------------------------------------------------------------
# Derived positions and P&L
# ---------------------------------------------------------------------------

def test_realised_pnl_arithmetic(journal, db):
    """Credit received minus debit paid, per contract, x100. A $0.60
    credit closed at $0.30 is +$30 on one contract -- not +$0.30, and not
    the max-loss number."""
    write(journal,
          entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00", credit=0.60, qty=1),
          exit_("tg-e-20260831-1030-spy", "SPY", "2026-09-01T11:00:00-04:00", debit=0.30))

    conn = store.rebuild(db, str(journal))
    row = conn.execute("SELECT * FROM positions").fetchone()
    assert row["status"] == "closed"
    assert row["realised_pnl_dollars"] == 30.0
    assert row["exit_reason"] == "take_profit"


def test_realised_pnl_is_negative_on_a_stopped_trade(journal, db):
    """The 2x-credit stop closes at a debit above the credit received.
    Sign matters: this is the number the write-up reports."""
    write(journal,
          entry("tg-e-20260831-1030-qqq", "QQQ", "2026-08-31T10:31:00-04:00", credit=0.60),
          exit_("tg-e-20260831-1030-qqq", "QQQ", "2026-09-01T14:00:00-04:00",
                debit=1.20, reason="stop_loss"))

    conn = store.rebuild(db, str(journal))
    assert conn.execute("SELECT realised_pnl_dollars FROM positions").fetchone()[0] == -60.0


def test_open_position_has_no_pnl(journal, db):
    write(journal, entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00"))
    conn = store.rebuild(db, str(journal))
    row = conn.execute("SELECT * FROM positions").fetchone()
    assert row["status"] == "open" and row["realised_pnl_dollars"] is None


def test_equity_curve_starts_flat_and_compounds_in_close_order(journal, db):
    write(journal,
          entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00", credit=0.60),
          entry("tg-e-20260831-1330-qqq", "QQQ", "2026-08-31T13:31:00-04:00", credit=0.50),
          exit_("tg-e-20260831-1030-spy", "SPY", "2026-09-01T11:00:00-04:00", debit=0.30),
          exit_("tg-e-20260831-1330-qqq", "QQQ", "2026-09-02T11:00:00-04:00",
                debit=1.00, reason="stop_loss"))

    conn = store.rebuild(db, str(journal))
    curve = store.equity_curve(conn, starting_equity=100000)
    assert [p["equity"] for p in curve] == [100000.0, 100030.0, 99980.0]


# ---------------------------------------------------------------------------
# Gate attribution -- the "why no trade" panel
# ---------------------------------------------------------------------------

def test_gate_veto_is_attributed_to_its_gate(journal, db):
    write(journal,
          {"ts": "2026-08-31T10:31:00-04:00", "event": "no_trade", "underlying": "SPY",
           "reason": "delta_band: short leg 0.31 outside 0.16-0.25"},
          {"ts": "2026-08-31T10:31:01-04:00", "event": "no_trade", "underlying": "QQQ",
           "reason": "delta_band: short leg 0.09 outside 0.16-0.25"},
          {"ts": "2026-08-31T13:31:00-04:00", "event": "no_trade", "underlying": "SPY",
           "reason": "vrp_present: IV-RV 0.8 below 2.0 points"})

    conn = store.rebuild(db, str(journal))
    by_gate = {}
    for row in store.gate_rejection_counts(conn):
        by_gate[row["gate"]] = by_gate.get(row["gate"], 0) + row["n"]
    assert by_gate == {"delta_band": 2, "vrp_present": 1}


def test_control_flow_reasons_are_not_mistaken_for_gates(journal, db):
    """`outside_entry_window` is loop.py deciding not to look, not a risk
    gate firing. Counting it as a gate would overstate how often the guard
    vetoed a real candidate -- exactly the number a judge reads."""
    write(journal, *[
        {"ts": "2026-08-31T09:31:00-04:00", "event": "no_trade", "reason": r}
        for r in sorted(store.NON_GATE_NO_TRADE_REASONS)
    ])

    conn = store.rebuild(db, str(journal))
    assert all(r["gate"] == "other" for r in store.gate_rejection_counts(conn))


def test_non_gate_reason_vocabulary_matches_loop():
    """store.py splits a no_trade reason on ':' to name the gate that
    vetoed. That works only while loop.py's own control-flow reasons stay
    colon-free -- the moment someone adds `reason="stale_data: 12m old"`,
    the dashboard invents a gate called `stale_data` and the "how often
    did the guard fire" number silently inflates.

    So pin the vocabulary to loop.py's source. A new bare reason fails
    here, pointing at the parser, instead of failing quietly in a panel
    nobody diffs.
    """
    import re
    from pathlib import Path

    source = Path(loop.__file__).read_text(encoding="utf-8")
    literals = set(re.findall(r'_journal\("no_trade",\s*reason="([^"]+)"', source))

    assert literals, "no literal no_trade reasons found -- did the call shape change?"
    assert literals == store.NON_GATE_NO_TRADE_REASONS, (
        "loop.py's bare no_trade reasons drifted from store.NON_GATE_NO_TRADE_REASONS; "
        f"only in loop.py: {sorted(literals - store.NON_GATE_NO_TRADE_REASONS)}; "
        f"only in store.py: {sorted(store.NON_GATE_NO_TRADE_REASONS - literals)}"
    )
    assert not [r for r in literals if ":" in r], (
        "a control-flow reason now contains ':' and will be parsed as a gate name"
    )


def test_gate_counts_filter_by_session(journal, db):
    write(journal,
          {"ts": "2026-08-31T10:31:00-04:00", "event": "no_trade",
           "reason": "delta_band: short leg 0.31 outside 0.16-0.25"},
          {"ts": "2026-09-01T10:31:00-04:00", "event": "no_trade",
           "reason": "quote_sanity: bid 0.00 not positive"})

    conn = store.rebuild(db, str(journal))
    rows = store.gate_rejection_counts(conn, session_date="2026-09-01")
    assert len(rows) == 1 and rows[0]["gate"] == "quote_sanity"


# ---------------------------------------------------------------------------
# Integrity and rebuild semantics
# ---------------------------------------------------------------------------

def test_chain_is_intact_after_rebuild(journal, db):
    write(journal, *[entry(f"tg-e-2026083{i}-1030-spy", "SPY", f"2026-08-3{i}T10:31:00-04:00")
                     for i in range(1, 2)])
    conn = store.rebuild(db, str(journal))
    assert store.verify_chain(conn) == (True, None)


def test_chain_detects_an_edited_row(journal, db):
    """Rewriting history in the database -- turning a loss into a win --
    has to be detectable, or the artifact a judge queries proves nothing."""
    write(journal,
          entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00"),
          exit_("tg-e-20260831-1030-spy", "SPY", "2026-09-01T11:00:00-04:00", debit=1.20,
                reason="stop_loss"))

    conn = store.rebuild(db, str(journal))
    assert store.verify_chain(conn)[0] is True

    tampered = json.dumps({"ts": "2026-09-01T11:00:00-04:00", "event": "exit_filled",
                           "close_debit": 0.10}, sort_keys=True)
    conn.execute("UPDATE events SET payload=?, line_sha256=? WHERE seq=2",
                 (tampered, "0" * 64))
    conn.commit()

    ok, seq = store.verify_chain(conn)
    assert ok is False and seq == 2


def test_rebuild_is_deterministic(journal, db, tmp_path):
    write(journal,
          entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00"),
          exit_("tg-e-20260831-1030-spy", "SPY", "2026-09-01T11:00:00-04:00"))

    first = store.rebuild(db, str(journal))
    second = store.rebuild(str(tmp_path / "again.db"), str(journal))

    head = "SELECT value FROM meta WHERE key='chain_head'"
    assert first.execute(head).fetchone()[0] == second.execute(head).fetchone()[0]
    assert (first.execute("SELECT * FROM positions").fetchall()
            == second.execute("SELECT * FROM positions").fetchall())


def test_rebuild_drops_stale_rows(journal, db):
    """The database is a function of the journal. Truncating the journal
    and rebuilding must not leave yesterday's positions behind."""
    write(journal, entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00"))
    store.rebuild(db, str(journal))

    journal.write_text("", encoding="utf-8")
    conn = store.rebuild(db, str(journal))
    assert conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_connect_rebuilds_when_the_journal_has_grown(journal, db):
    write(journal, entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00"))
    store.connect(db, str(journal))

    write(journal, entry("tg-e-20260831-1330-qqq", "QQQ", "2026-08-31T13:31:00-04:00"))
    conn = store.connect(db, str(journal))
    assert len(store.open_positions(conn)) == 2


def test_connect_handles_a_missing_journal(journal, db):
    conn = store.connect(db, str(journal))  # never written
    assert store.open_positions(conn) == []
    assert store.summary(conn)["events"] == 0


def test_connect_recovers_from_a_corrupt_database(journal, db):
    """A truncated .db from a killed process must not take the dashboard
    down -- it is disposable by design."""
    write(journal, entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00"))
    store.rebuild(db, str(journal))
    with open(db, "wb") as f:
        f.write(b"not a database")

    conn = store.connect(db, str(journal))
    assert len(store.open_positions(conn)) == 1


def test_summary_reports_positions_and_realised_pnl(journal, db):
    write(journal,
          entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00", credit=0.60),
          entry("tg-e-20260831-1330-qqq", "QQQ", "2026-08-31T13:31:00-04:00", credit=0.50),
          exit_("tg-e-20260831-1030-spy", "SPY", "2026-09-01T11:00:00-04:00", debit=0.30))

    conn = store.rebuild(db, str(journal))
    s = store.summary(conn, starting_equity=100000)
    assert s["positions_total"] == 2
    assert s["positions_open"] == 1 and s["positions_closed"] == 1
    assert s["wins"] == 1
    assert s["realised_pnl_dollars"] == 30.0 and s["equity"] == 100030.0
    assert s["chain_intact"] is True


def test_decision_log_is_newest_first_and_parsed(journal, db):
    write(journal,
          {"ts": "2026-08-31T09:31:00-04:00", "event": "no_trade",
           "reason": "delta_band: 0.31 outside 0.16-0.25"},
          entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00"))

    conn = store.rebuild(db, str(journal))
    log = store.decision_log(conn)
    assert [r["event"] for r in log] == ["entry_filled", "no_trade"]
    assert log[0]["payload"]["credit"] == 0.60


def test_decision_log_excludes_routine_tick_noise(journal, db):
    """tick_completed fires every five minutes all session. In the log a
    judge reads, it is noise that buries the two decisions that matter."""
    write(journal,
          {"ts": "2026-08-31T09:31:00-04:00", "event": "tick_completed", "ok": True},
          entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00"))

    conn = store.rebuild(db, str(journal))
    assert [r["event"] for r in store.decision_log(conn)] == ["entry_filled"]


def test_cli_rebuild_against_the_real_journal(tmp_path, capsys):
    """The committed journal is real input -- if its actual shape breaks
    the parser, that is worth failing on."""
    assert store.main(["--rebuild", "--db", str(tmp_path / "cli.db"),
                       "--journal", store.JOURNAL_PATH]) == 0
    out = capsys.readouterr().out
    assert "chain: intact" in out
    assert json.loads(out.split("\n", 1)[1])["chain_intact"] is True


def test_open_positions_survives_a_same_timestamp_replay(journal, db):
    """A replay after an adopted order can journal the same position_id
    twice with an identical ts. positions is keyed by position_id so it
    held one row, but open_positions() joined back to events on ts and
    matched both -- returning two open positions where loop.py returns
    one. That is a parity break in the direction that matters: the
    dashboard would show a phantom position, and any future caller that
    trusted this over loop.py would double-count open risk.

    The join is on events.seq now, which is unique by construction.
    """
    rec = entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00")
    write(journal, rec, rec)

    conn = store.rebuild(db, str(journal))
    expected = loop._open_positions(loop._read_journal())

    assert len(expected) == 1
    assert store.open_positions(conn) == expected


def test_proposal_events_reach_the_decision_log(journal, db):
    """brain.py's thesis is the only human-readable trace of the model's
    contribution, and loop.py journals it as a `proposal` event. It was
    filtered out of the decision log, so the dashboard showed an empty
    Detail column on exactly the rows where the AI is visible."""
    write(journal,
          {"ts": "2026-08-31T10:30:00-04:00", "event": "proposal", "model": "claude-opus-5",
           "proposal": {"underlying": "SPY", "direction": "bullish", "confidence": 0.6,
                        "thesis": "contango holds and IV sits above realised",
                        "invalidation": "VIX9D crosses VIX3M"}},
          entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00"))

    conn = store.rebuild(db, str(journal))
    events = [e["event"] for e in store.decision_log(conn)]
    assert "proposal" in events

    row = next(e for e in store.decision_log(conn) if e["event"] == "proposal")
    assert row["payload"]["proposal"]["thesis"].startswith("contango")
# ---------------------------------------------------------------------------
# Concurrency -- the dashboard serves sessions on threads
# ---------------------------------------------------------------------------

def test_concurrent_cold_loads_all_succeed(tmp_path):
    """Streamlit runs concurrent sessions on separate threads, so several
    first-visitors land in rebuild() at once. Build-in-place made them
    stamp on each other mid-DDL: 10 of 12 failed with `disk I/O error`,
    `attempt to write a readonly database` and `table meta already
    exists`. On the public demo URL that is a blank page in front of a
    judge -- and showErrorDetails="none" means it would not even say why.

    Build-then-os.replace makes the race benign: every builder does
    identical deterministic work from the same journal, so whoever lands
    last wins and all of them are correct.
    """
    import concurrent.futures as cf

    journal = tmp_path / "journal.jsonl"
    write(journal, *[entry(f"p{i}", "SPY", f"2026-08-31T10:{i:02d}:00-04:00") for i in range(6)])
    db = str(tmp_path / "race.db")

    def load(_):
        return store.summary(store.connect(db, str(journal)))["events"]

    with cf.ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(load, range(16)))

    assert results == [6] * 16
    assert not list(tmp_path.glob("*.building.*")), "staging databases must not survive"


def test_rebuild_leaves_no_staging_file_behind(tmp_path):
    journal = tmp_path / "journal.jsonl"
    write(journal, entry("p1", "SPY", "2026-08-31T10:00:00-04:00"))
    store.rebuild(str(tmp_path / "x.db"), str(journal))
    assert not list(tmp_path.glob("*.building.*"))


def test_connect_survives_a_database_replaced_underneath_it(tmp_path):
    """A reader can open the file microseconds before another thread's
    os.replace swaps a new inode in. Rebuilding from the journal is always
    the safe answer, and the journal is the source of truth anyway."""
    journal = tmp_path / "journal.jsonl"
    write(journal, entry("p1", "SPY", "2026-08-31T10:00:00-04:00"))
    db = tmp_path / "swap.db"
    store.rebuild(str(db), str(journal))

    db.write_bytes(b"garbage where a database used to be")
    conn = store.connect(str(db), str(journal))
    assert len(store.open_positions(conn)) == 1


def test_every_event_loop_can_emit_reaches_the_decision_log(journal, db):
    """The filter was an ALLOWLIST and it rotted: loop.py emits 30 event
    types, the log named 12, so 9 of the events an operator most needs
    were invisible -- assignment_detected, untracked_broker_position,
    submit_failed, journal_publish_failed, exit_fill_leg_mismatch,
    force_close_unresolved and the *_stale_unresolved family. `proposal`
    had already gone missing the same way.

    Reads loop.py's source so a newly-added event type fails HERE rather
    than being quietly absent from the page nobody diffs.
    """
    import re
    from pathlib import Path

    emitted = set(re.findall(r'_append_journal\(\s*"([a-z_]+)"',
                             Path(loop.__file__).read_text(encoding="utf-8")))
    assert emitted, "no journal events found -- did the call shape change?"

    NOISE = {"tick_completed", "exit_evaluated"}
    write(journal, *[{"ts": f"2026-08-31T10:{i:02d}:00-04:00", "event": e,
                      "reason": "something happened"}
                     for i, e in enumerate(sorted(emitted))])

    conn = store.rebuild(db, str(journal))
    shown = {r["event"] for r in store.decision_log(conn, limit=500)}
    missing = (emitted - NOISE) - shown
    assert not missing, f"loop.py can emit these but the dashboard hides them: {sorted(missing)}"


def test_the_highest_stakes_failure_is_visible(journal, db):
    """force_close_unresolved fires when Thursday's mandatory flatten
    fails to close a position. It is the single most important event of
    the week and the old allowlist did not include it."""
    write(journal, {"ts": "2026-09-03T15:45:00-04:00", "event": "force_close_unresolved",
                    "level": "critical", "position_id": "tg-e-20260831-1030-spy"})
    conn = store.rebuild(db, str(journal))
    assert [r["event"] for r in store.decision_log(conn)] == ["force_close_unresolved"]


def test_per_tick_noise_stays_out(journal, db):
    """40 tick_completed and 26 exit_evaluated rows in one session would
    bury the two decisions that matter."""
    write(journal,
          {"ts": "2026-08-31T10:00:00-04:00", "event": "tick_completed", "ok": True},
          {"ts": "2026-08-31T10:05:00-04:00", "event": "exit_evaluated",
           "position_id": "p1", "signal": "hold"},
          {"ts": "2026-08-31T10:06:00-04:00", "event": "no_trade",
           "reason": "outside_entry_window"},
          entry("p1", "SPY", "2026-08-31T10:31:00-04:00"))

    conn = store.rebuild(db, str(journal))
    assert [r["event"] for r in store.decision_log(conn)] == ["entry_filled"]


def test_a_real_gate_veto_is_never_treated_as_noise(journal, db):
    """Only outside_entry_window is dropped. Every other no_trade reason,
    gate vetoes included, is a decision about a real candidate."""
    write(journal,
          {"ts": "2026-08-31T10:31:00-04:00", "event": "no_trade",
           "reason": "vrp_present: IV-RV 0.8 below the 1.0 floor"},
          {"ts": "2026-08-31T10:32:00-04:00", "event": "no_trade",
           "reason": "all_underlyings_at_cap"})
    conn = store.rebuild(db, str(journal))
    assert len(store.decision_log(conn)) == 2


def test_realised_pnl_sums_partial_exit_debits(journal, db):
    """X1 (31 Aug 2026): a qty-2 position can close in pieces. Entry credit
    0.60 x 2; one contract closed at 0.31 via exit_partial_fill, the last
    at 0.29 via exit_filled -> pnl = 120 - 31 - 29 = +$60. Ignoring the
    partial's debit would overstate P&L by $31."""
    write(journal,
          entry("tg-e-20260901-1030-spy", "SPY", "2026-09-01T10:31:00-04:00", credit=0.60, qty=2),
          {"ts": "2026-09-02T11:00:00-04:00", "event": "exit_partial_fill",
           "position_id": "tg-e-20260901-1030-spy", "reason": "take_profit",
           "qty": 1, "close_debit": 0.31, "client_order_id": "tg-x-20260901-1030-spy-s0"},
          exit_("tg-e-20260901-1030-spy", "SPY", "2026-09-02T11:10:00-04:00", debit=0.29, qty=1))

    conn = store.rebuild(db, str(journal))
    row = conn.execute("SELECT * FROM positions").fetchone()
    assert row["status"] == "closed"
    assert row["realised_pnl_dollars"] == pytest.approx(0.60 * 200 - 31.0 - 29.0)


def test_pre_x1_rows_without_exit_qty_still_compute_pnl(journal, db):
    """Backward compatibility: the open 31 Aug qty-1 position's eventual
    exit_filled may carry no qty field in older fixtures -- the entry qty
    is the fallback."""
    write(journal,
          entry("tg-e-20260831-1030-spy", "SPY", "2026-08-31T10:31:00-04:00", credit=0.61, qty=1),
          {k: v for k, v in exit_("tg-e-20260831-1030-spy", "SPY",
                                   "2026-09-03T14:35:00-04:00", debit=0.50).items() if k != "qty"})
    conn = store.rebuild(db, str(journal))
    assert conn.execute("SELECT realised_pnl_dollars FROM positions").fetchone()[0] == pytest.approx(11.0)
