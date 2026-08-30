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


def test_lookup_or_submit_adopts_without_resubmitting():
    existing = {"id": "order-1", "status": "new"}
    with patch("loop.alpaca.get_order_by_client_id", return_value=existing) as get_mock, \
         patch("loop.alpaca.submit_mleg", side_effect=AssertionError("must not resubmit a found order")) as submit_mock:
        order, action = loop._lookup_or_submit("tg-e-x", [], "-0.60", 1, "submission", False)
    assert action == "adopted" and order is existing
    get_mock.assert_called_once()
    submit_mock.assert_not_called()


def test_lookup_or_submit_distinguishes_dry_run_echo_from_real_submit():
    with patch("loop.alpaca.get_order_by_client_id", return_value=None), \
         patch("loop.alpaca.submit_mleg", return_value={"legs": [], "limit_price": "-0.60"}):  # dry-run echo: no "id"
        _, action = loop._lookup_or_submit("tg-e-x", [], "-0.60", 1, "submission", True)
    assert action == "dry_run"

    with patch("loop.alpaca.get_order_by_client_id", return_value=None), \
         patch("loop.alpaca.submit_mleg", return_value={"id": "order-2", "status": "new"}):
        _, action = loop._lookup_or_submit("tg-e-x", [], "-0.60", 1, "submission", False)
    assert action == "submitted"


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
