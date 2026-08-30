"""loop.py's non-trivial logic, isolated from the network: journal
round-trip (the load-bearing piece -- entries_today/filled_underlyings_today/
open-position/consecutive_exceptions derivation must survive a re-read),
HALT fail-closed behavior, the idempotent-submit branch, entry-window
boundaries, and exit attempt-number escalation. Not a full run_tick
rehearsal -- that needs a live/mocked broker+LLM boundary far beyond what a
lazy self-check owes; see the build report.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import loop
import spread

ET = ZoneInfo("America/New_York")


def test_journal_round_trip_positions_and_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))

    loop._append_journal("entry_filled", position_id="tg-e-20260831-1030-spy", underlying="SPY",
                          credit=0.60, max_loss_dollars=440)
    events = loop._read_journal()
    open_positions = loop._open_positions(events)
    assert len(open_positions) == 1 and open_positions[0]["position_id"] == "tg-e-20260831-1030-spy"

    now = datetime.now(ET)
    count, filled = loop._entries_today(events, now)
    assert count == 1 and filled == ["SPY"]

    loop._append_journal("exit_filled", position_id="tg-e-20260831-1030-spy", underlying="SPY", reason="take_profit")
    events = loop._read_journal()
    assert loop._open_positions(events) == []

    loop._append_journal("tick_completed", ok=True)
    loop._append_journal("tick_completed", ok=False)
    loop._append_journal("tick_completed", ok=False)
    events = loop._read_journal()
    assert loop._consecutive_exceptions(events) == 2


def test_journal_skips_torn_lines(tmp_path, monkeypatch):
    path = tmp_path / "journal.jsonl"
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(path))
    loop._append_journal("tick_completed", ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"ts": "not valid json\n')  # simulates a crash mid-write
    events = loop._read_journal()  # must not raise
    assert len(events) == 1


def test_check_halt_creates_default_and_fails_closed_on_corrupt(tmp_path, monkeypatch):
    halt_path = tmp_path / "HALT.json"
    monkeypatch.setattr(loop, "HALT_PATH", str(halt_path))

    active, info = loop._check_halt()
    assert active is False and halt_path.exists()

    halt_path.write_text("not json")
    active, info = loop._check_halt()
    assert active is True  # corrupt HALT file must fail closed, never silently "not halted"


STALE_CANCELED = {"id": "o1", "status": "canceled", "filled_qty": "0"}
REJECTED_422 = {"code": 40010001, "error": "client_order_id must be unique", "status": 422}


def test_lookup_or_submit_adopts_live_order():
    existing = {"id": "order-1", "status": "accepted", "filled_qty": "0"}
    with patch("loop.alpaca.get_order_by_client_id", return_value=existing) as get_mock, \
         patch("loop.alpaca.submit_mleg", side_effect=AssertionError("must not resubmit a found order")) as submit_mock:
        order, action, cid = loop._lookup_or_submit("tg-e-x", [], "-0.60", 1, "submission", False)
    assert (action, cid) == ("adopted", "tg-e-x") and order is existing
    get_mock.assert_called_once()
    submit_mock.assert_not_called()


def test_lookup_or_submit_skips_terminal_unfilled_and_walks_to_r2(tmp_path, monkeypatch):
    # Verified live 30 Aug 2026: get-by-client-id returns a canceled order
    # forever, so adopting it gave a window exactly one attempt.
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    lookups = {"tg-e-x": STALE_CANCELED, "tg-e-xr2": None}
    with patch("loop.alpaca.get_order_by_client_id", side_effect=lambda cid, profile: lookups[cid]), \
         patch("loop.alpaca.submit_mleg", return_value={"id": "o2", "status": "accepted", "filled_qty": "0"}) as submit_mock:
        order, action, cid = loop._lookup_or_submit("tg-e-x", [], "-0.60", 1, "submission", False)
    assert (order["id"], action, cid) == ("o2", "submitted", "tg-e-xr2")
    submit_mock.assert_called_once()
    assert submit_mock.call_args.kwargs["client_order_id"] == "tg-e-xr2"
    skipped = [e for e in loop._read_journal() if e["event"] == "stale_order_skipped"]
    assert [e["client_order_id"] for e in skipped] == ["tg-e-x"]


def test_lookup_or_submit_adopts_partially_filled_canceled_order():
    partial = {"id": "o1", "status": "canceled", "filled_qty": "1"}
    with patch("loop.alpaca.get_order_by_client_id", return_value=partial), \
         patch("loop.alpaca.submit_mleg", side_effect=AssertionError("must not resubmit")) as submit_mock:
        order, action, cid = loop._lookup_or_submit("tg-e-x", [], "-0.60", 1, "submission", False)
    assert (action, cid) == ("adopted", "tg-e-x") and order is partial
    submit_mock.assert_not_called()


def test_lookup_or_submit_journals_rejection_as_failed_not_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    with patch("loop.alpaca.get_order_by_client_id", return_value=None), \
         patch("loop.alpaca.submit_mleg", return_value=dict(REJECTED_422)):
        response, action, cid = loop._lookup_or_submit("tg-e-x", [], "-0.60", 1, "submission", False)
    assert (action, cid) == ("failed", "tg-e-x") and response["error"] == "client_order_id must be unique"
    events = loop._read_journal()
    failed = [e for e in events if e["event"] == "submit_failed"]
    assert len(failed) == 1 and failed[0]["level"] == "critical" and "40010001" in failed[0]["response"]
    assert not [e for e in events if e["event"].endswith("_dry_run")]


def test_lookup_or_submit_dry_run_echo(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    with patch("loop.alpaca.get_order_by_client_id", return_value=None), \
         patch("loop.alpaca.submit_mleg", return_value={"legs": [], "limit_price": "-0.60"}):  # dry-run echo: no "id"
        _, action, _ = loop._lookup_or_submit("tg-e-x", [], "-0.60", 1, "submission", True)
    assert action == "dry_run"

    with patch("loop.alpaca.get_order_by_client_id", return_value=None), \
         patch("loop.alpaca.submit_mleg", return_value={"id": "order-2", "status": "new"}):
        _, action, _ = loop._lookup_or_submit("tg-e-x", [], "-0.60", 1, "submission", False)
    assert action == "submitted"

    with patch("loop.alpaca.get_order_by_client_id", return_value=None), \
         patch("loop.alpaca.submit_mleg", return_value=dict(REJECTED_422)):  # a rejection under --dry-run is still a rejection
        _, action, _ = loop._lookup_or_submit("tg-e-x", [], "-0.60", 1, "submission", True)
    assert action == "failed"


def test_lookup_or_submit_gives_up_after_six_stale_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    with patch("loop.alpaca.get_order_by_client_id", return_value=STALE_CANCELED) as get_mock, \
         patch("loop.alpaca.submit_mleg", side_effect=AssertionError("must not submit")) as submit_mock:
        result = loop._lookup_or_submit("tg-e-x", [], "-0.60", 1, "submission", False)
    assert result == ({}, "failed", "tg-e-x")
    submit_mock.assert_not_called()
    assert get_mock.call_count == 6
    events = loop._read_journal()
    skipped = [e["client_order_id"] for e in events if e["event"] == "stale_order_skipped"]
    assert skipped == ["tg-e-x"] + [f"tg-e-xr{n}" for n in range(2, 7)]
    assert events[-1]["event"] == "submit_failed" and events[-1]["level"] == "critical"


def test_current_entry_window_15_minutes_wide():
    gov = {"entry": {"windows_et": ["10:30", "13:30"]}}
    at = lambda h, m: datetime(2026, 9, 1, h, m, tzinfo=ET)  # a Tuesday
    assert loop._current_entry_window(at(10, 30), gov) == "1030"
    assert loop._current_entry_window(at(10, 44), gov) == "1030"
    assert loop._current_entry_window(at(10, 45), gov) is None
    assert loop._current_entry_window(at(13, 29), gov) is None
    assert loop._current_entry_window(at(13, 30), gov) == "1330"


def test_current_entry_window_is_none_on_a_weekend():
    # The cron schedule is weekday-only, but a manual workflow_dispatch
    # is not -- without this, triggering a rehearsal at 10:35 on a
    # Saturday runs the full entry pipeline, including a real billed
    # brain.propose call, against stale weekend quotes.
    gov = {"entry": {"windows_et": ["10:30", "13:30"]}}
    assert loop._current_entry_window(datetime(2026, 8, 29, 10, 35, tzinfo=ET), gov) is None  # Saturday
    assert loop._current_entry_window(datetime(2026, 8, 30, 10, 35, tzinfo=ET), gov) is None  # Sunday
    assert loop._current_entry_window(datetime(2026, 8, 31, 10, 35, tzinfo=ET), gov) == "1030"  # Monday


def test_exit_attempt_number_counts_by_position_not_reason():
    # Keying by (position_id, rung) let a reason-flip (stop_loss this tick,
    # time_exit the next -- exit_signal recomputes fresh every tick) reset
    # the count and change the client_order_id's window slot, orphaning any
    # order still outstanding under the old reason's id. Counting by
    # position_id alone survives the flip.
    events = [
        {"event": "exit_unfilled", "position_id": "p1", "rung": "stop"},
        {"event": "exit_unfilled", "position_id": "p1", "rung": "stop"},
        {"event": "exit_unfilled", "position_id": "p1", "rung": "tp"},  # different rung, still counts
    ]
    assert loop._exit_attempt_number(events, "p1") == 4
    assert loop._exit_attempt_number(events, "p2") == 1


def test_cancel_and_confirm_dry_run_never_cancels_for_real():
    gov = {"operational": {"order_poll_max_attempts": 5}}
    with patch("loop.alpaca.cancel_order", side_effect=AssertionError("must not cancel for real under dry_run")), \
         patch("loop.alpaca.get_order", return_value={"id": "order-1", "status": "new"}) as get_mock:
        order = loop._cancel_and_confirm("order-1", "submission", gov, dry_run=True)
    get_mock.assert_called_once()
    assert order == {"id": "order-1", "status": "new"}


def test_cancel_and_confirm_live_cancels_for_real():
    gov = {"operational": {"order_poll_max_attempts": 5}}
    with patch("loop.alpaca.cancel_order", return_value={}) as cancel_mock, \
         patch("loop.alpaca.poll_until_filled", return_value={"id": "order-1", "status": "canceled"}):
        order = loop._cancel_and_confirm("order-1", "submission", gov, dry_run=False)
    cancel_mock.assert_called_once()
    assert order["status"] == "canceled"


def test_trigger_halt_first_reason_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "HALT_PATH", str(tmp_path / "HALT.json"))
    loop._trigger_halt("first problem")
    loop._trigger_halt("second problem")
    active, info = loop._check_halt()
    assert active is True and info["reason"] == "first problem"


def test_check_leg_symmetry_detects_naked_leg_and_halts(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "HALT_PATH", str(tmp_path / "HALT.json"))
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    with patch("loop.alpaca.positions", return_value=[{"symbol": "SHORT_SYM"}]):
        symmetric = loop._check_leg_symmetry("SHORT_SYM", "LONG_SYM", "submission", "p1", context="test")
    assert symmetric is False
    active, info = loop._check_halt()
    assert active is True and "naked leg" in info["reason"]
    assert any(e["event"] == "naked_leg_detected" for e in loop._read_journal())


def test_check_leg_symmetry_both_open_or_both_closed_is_fine(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "HALT_PATH", str(tmp_path / "HALT.json"))
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    with patch("loop.alpaca.positions", return_value=[]):
        assert loop._check_leg_symmetry("S", "L", "submission", "p1", context="test") is True
    with patch("loop.alpaca.positions", return_value=[{"symbol": "S"}, {"symbol": "L"}]):
        assert loop._check_leg_symmetry("S", "L", "submission", "p1", context="test") is True
    assert loop._check_halt()[0] is False


def test_fresh_close_quotes_windows_the_chain_to_the_legs():
    # Verified live 30 Aug 2026: an unwindowed --limit 100 page could omit
    # a leg, and the resulting MarketDataError made the exit (Thursday's
    # flatten included) silently skip as exit_quote_unavailable.
    snapshots = {
        "SPY260908P00700000": {"latestQuote": {"bp": 1.50, "ap": 1.55, "t": "2026-09-01T15:00:00Z"}, "greeks": {"delta": -0.2}},
        "SPY260908P00695000": {"latestQuote": {"bp": 0.90, "ap": 0.95, "t": "2026-09-01T15:00:00Z"}, "greeks": {"delta": -0.13}},
    }
    chain_mock = MagicMock(return_value={"snapshots": snapshots})
    with patch("loop.alpaca.option_chain", chain_mock):
        short_c, long_c = loop._fresh_close_quotes("SPY", "2026-09-08", "SPY260908P00700000", "SPY260908P00695000", "submission")

    kwargs = chain_mock.call_args.kwargs
    assert kwargs["expiration_date"] == "2026-09-08"
    assert kwargs["strike_gte"] == 694.5 and kwargs["strike_lte"] == 700.5
    assert short_c.symbol == "SPY260908P00700000" and long_c.symbol == "SPY260908P00695000"


def test_force_rung_tag_is_date_stamped():
    thu, fri = datetime(2026, 9, 3, 14, 30, tzinfo=ET), datetime(2026, 9, 4, 14, 30, tzinfo=ET)
    assert loop._force_rung_tag(thu, "14:30") == "force09031430"
    assert loop._force_rung_tag(fri, "14:30") == "force09041430"
    assert loop._force_rung_tag(thu, "14:30") != loop._force_rung_tag(fri, "14:30")


def test_attempt_entry_stops_after_failed_submit(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    short_c = spread.Contract(symbol="SPY260908P00700000", strike=700.0, delta=-0.20, iv=0.2, bid=1.50, ask=1.55, expiry="2026-09-08")
    long_c = spread.Contract(symbol="SPY260908P00695000", strike=695.0, delta=-0.13, iv=0.2, bid=0.90, ask=0.95, expiry="2026-09-08")
    plan = spread.SpreadPlan(underlying="SPY", direction="bull_put", expiry="2026-09-08", short=short_c, long=long_c,
                             width=5, credit=0.60, qty=1, max_loss_dollars=440)
    gov = {"operational": {"order_poll_max_attempts": 60, "unfilled_order_cancel_after_seconds": 60}}
    now = datetime(2026, 8, 31, 10, 31, tzinfo=ET)
    with patch("loop.alpaca.get_order_by_client_id", return_value=None), \
         patch("loop.alpaca.submit_mleg", return_value=dict(REJECTED_422)) as submit_mock, \
         patch("loop.alpaca.positions", return_value=[]):
        result = loop._attempt_entry(plan, 1, "1030", "20260831", now, gov, "submission", False)
    submit_mock.assert_called_once()  # a rejected s0 ends the attempt -- no s1
    assert result == {"filled": False, "failed": True, "stage": "s0"}
    events = [(e["event"], e.get("stage")) for e in loop._read_journal()]
    assert ("entry_intent", "s0") in events and ("entry_intent", "s1") not in events
    assert [ev for ev, _ in events if ev in ("submit_failed", "entry_failed")] == ["submit_failed", "entry_failed"]


def test_run_tick_guarded_publishes_once_on_success():
    with patch("loop._run_tick_body", return_value={"ok": True, "now": "x"}), \
         patch("loop._git_publish", MagicMock(return_value={"committed": False, "reason": "nothing to commit"})) as pub:
        summary = loop._run_tick_guarded(datetime(2026, 8, 31, 10, 31, tzinfo=ET), False, "submission")
    pub.assert_called_once()
    assert summary["ok"] is True and summary["git"] is pub.return_value


def test_run_tick_guarded_publishes_after_exception(tmp_path, monkeypatch):
    # Until 30 Aug 2026 the publish lived in the body's happy path, so a
    # raising tick left tick_exception/tick_completed ok=False (and any
    # HALT.json or entry_submitted before the crash) on the ephemeral
    # runner -- the three-strike halt could never trip on CI.
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    with patch("loop._run_tick_body", side_effect=RuntimeError("boom")), \
         patch("loop._git_publish", MagicMock(return_value={"committed": True, "pushed": True, "push_error": None})) as pub:
        summary = loop._run_tick_guarded(datetime(2026, 8, 31, 10, 31, tzinfo=ET), False, "submission")
    pub.assert_called_once()
    assert summary["ok"] is False and summary["error"] == "boom" and summary["git"] is pub.return_value
    events = loop._read_journal()
    assert any(e["event"] == "tick_exception" for e in events)
    assert [e for e in events if e["event"] == "tick_completed"][-1]["ok"] is False


def test_run_tick_guarded_marks_publish_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    with patch("loop._run_tick_body", return_value={"ok": True, "now": "x"}), \
         patch("loop._git_publish", MagicMock(return_value={"committed": True, "pushed": False, "push_error": "x"})):
        summary = loop._run_tick_guarded(datetime(2026, 8, 31, 10, 31, tzinfo=ET), False, "submission")
    assert summary["ok"] is False
    assert any(e["event"] == "journal_publish_failed" for e in loop._read_journal())


def test_run_tick_guarded_publishes_on_not_paper_abort():
    with patch("loop._run_tick_body", return_value={"ok": False, "aborted_at": "assert_paper"}), \
         patch("loop._git_publish", MagicMock(return_value={"committed": True, "pushed": True, "push_error": None})) as pub:
        summary = loop._run_tick_guarded(datetime(2026, 8, 31, 10, 31, tzinfo=ET), False, "submission")
    pub.assert_called_once()
    assert summary["ok"] is False and summary["aborted_at"] == "assert_paper"
