"""loop.py's non-trivial logic, isolated from the network: journal
round-trip (the load-bearing piece -- entries_today/filled_underlyings_today/
open-position/consecutive_exceptions derivation must survive a re-read),
HALT fail-closed behavior, the idempotent-submit branch, entry-window
boundaries, and exit attempt-number escalation. Not a full run_tick
rehearsal -- that needs a live/mocked broker+LLM boundary far beyond what a
lazy self-check owes; see the build report.
"""

import contextlib
import json
import subprocess
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

import alpaca
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
        result = loop._attempt_entry(plan, 1, "1030", "20260831", now, gov, "submission", False, [])
    submit_mock.assert_called_once()  # a rejected s0 ends the attempt -- no s1
    assert result == {"filled": False, "failed": True, "stage": "s0"}
    events = [(e["event"], e.get("stage")) for e in loop._read_journal()]
    assert ("entry_intent", "s0") in events and ("entry_intent", "s1") not in events
    assert [ev for ev, _ in events if ev in ("submit_failed", "entry_failed")] == ["submit_failed", "entry_failed"]


SHORT_C = spread.Contract(symbol="SPY260908P00700000", strike=700.0, delta=-0.20, iv=0.2, bid=1.50, ask=1.55, expiry="2026-09-08")
LONG_C = spread.Contract(symbol="SPY260908P00695000", strike=695.0, delta=-0.13, iv=0.2, bid=0.90, ask=0.95, expiry="2026-09-08")
PLAN = spread.SpreadPlan(underlying="SPY", direction="bull_put", expiry="2026-09-08", short=SHORT_C, long=LONG_C,
                         width=5, credit=0.60, qty=1, max_loss_dollars=440)
GOV = {"operational": {"order_poll_max_attempts": 60, "unfilled_order_cancel_after_seconds": 60}}
NOW = datetime(2026, 8, 31, 10, 31, tzinfo=ET)
ENTRY_REC = {"position_id": "tg-e-20260831-1030-spy", "underlying": "SPY", "_close_qty": 1, "trade_date": "20260831",
             "direction": "bull_put", "expiry": "2026-09-08", "width": 5, "credit": 0.60, "window": "1030"}


@contextlib.contextmanager
def _recording_broker(lookups, broker_calls):
    """Every submit/cancel lands in broker_calls in order; every poll answers canceled."""
    def submit(legs, limit_price, client_order_id, qty, dry_run, profile):
        broker_calls.append(("submit", client_order_id))
        return {"id": f"o-{client_order_id}", "status": "accepted", "filled_qty": "0", "client_order_id": client_order_id}

    def cancel(order_id, profile):
        broker_calls.append(("cancel", order_id))
        return {}

    with contextlib.ExitStack() as stack:
        for p in (
            patch("loop.alpaca.get_order_by_client_id", side_effect=lambda cid, profile: lookups[cid]),
            patch("loop.alpaca.submit_mleg", side_effect=submit),
            patch("loop.alpaca.cancel_order", side_effect=cancel),
            patch("loop.alpaca.poll_until_filled",
                  side_effect=lambda order_id, max_attempts, profile: {"id": order_id, "status": "canceled", "filled_qty": "0"}),
            patch("loop.alpaca.positions", return_value=[]),
            patch("loop.time.sleep", lambda s: None),
        ):
            stack.enter_context(p)
        yield


def test_attempt_entry_cancels_a_live_sibling_before_the_walk(tmp_path, monkeypatch):
    # Tick 1 submitted s0, canceled it, submitted s1, then died mid-poll: s1
    # is still a live DAY order. Tick 2's walk (s0 stale -> s0r2 -> 404 ->
    # submit) would otherwise put a second live entry order beside it.
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    base0, base1 = "tg-e-20260831-1030-spy-s0", "tg-e-20260831-1030-spy-s1"
    lookups = {base0: STALE_CANCELED, base0 + "r2": None,
               base1: {"id": "o-s1", "status": "canceled", "filled_qty": "0"}, base1 + "r2": None}
    open_orders = [{"id": "o-s1", "client_order_id": base1},
                   {"id": "o-qqq", "client_order_id": "tg-e-20260831-1030-qqq-s1"},   # other underlying -- untouched
                   {"id": "o-x", "client_order_id": "tg-x-20260831-1030-spy-s0"}]     # an exit order -- untouched
    broker_calls = []
    with _recording_broker(lookups, broker_calls):
        result = loop._attempt_entry(PLAN, 1, "1030", "20260831", NOW, GOV, "submission", False, open_orders)
    assert result == {"filled": False, "stage": "s1"}
    assert broker_calls[0] == ("cancel", "o-s1")
    assert [c for c in broker_calls if c[0] == "submit"] == [("submit", base0 + "r2"), ("submit", base1 + "r2")]
    assert ("cancel", "o-qqq") not in broker_calls and ("cancel", "o-x") not in broker_calls
    stale = [e["client_order_id"] for e in loop._read_journal() if e["event"] == "entry_stale_canceled"]
    assert stale == [base1]


def test_attempt_entry_cancels_a_live_order_from_an_earlier_window(tmp_path, monkeypatch):
    # The 10:40 tick died with s1 live (a DAY order); nothing revisits the
    # 10:30 window, and filled_underlyings_today counts fills only, so the
    # 13:30 tick proposes SPY again. Its guard must clear the 10:30 order
    # before the 13:30 ladder submits beside it.
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    orphan = "tg-e-20260831-1030-spy-s1"
    s0, s1 = "tg-e-20260831-1330-spy-s0", "tg-e-20260831-1330-spy-s1"
    open_orders = [{"id": "o-1030", "client_order_id": orphan},
                   {"id": "o-qqq", "client_order_id": "tg-e-20260831-1030-qqq-s1"}]   # other underlying -- untouched
    broker_calls = []
    with _recording_broker({s0: None, s1: None}, broker_calls):
        result = loop._attempt_entry(PLAN, 1, "1330", "20260831", datetime(2026, 8, 31, 13, 31, tzinfo=ET),
                                     GOV, "submission", False, open_orders)
    assert result == {"filled": False, "stage": "s1"}
    assert broker_calls[0] == ("cancel", "o-1030")
    assert [c for c in broker_calls if c[0] == "submit"] == [("submit", s0), ("submit", s1)]
    assert ("cancel", "o-qqq") not in broker_calls
    stale = [e["client_order_id"] for e in loop._read_journal() if e["event"] == "entry_stale_canceled"]
    assert stale == [orphan]


def test_attempt_entry_journals_a_stale_sibling_that_filled_under_the_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    base1 = "tg-e-20260831-1030-spy-s1"
    filled = {"id": "o-s1", "status": "filled", "filled_qty": "1", "filled_avg_price": "-0.55", "client_order_id": base1}
    with patch("loop.alpaca.cancel_order", return_value={}), \
         patch("loop.alpaca.poll_until_filled", return_value=filled), \
         patch("loop.alpaca.get_order_by_client_id", side_effect=AssertionError("must not start the walk")), \
         patch("loop.alpaca.submit_mleg", side_effect=AssertionError("must not submit")):
        result = loop._attempt_entry(PLAN, 1, "1030", "20260831", NOW, GOV, "submission", False,
                                     [{"id": "o-s1", "client_order_id": base1}])
    assert result["filled"] is True and result["order_id"] == "o-s1" and result["stage"] == "s1"
    events = loop._read_journal()
    assert [e["event"] for e in events] == ["entry_filled"]
    assert events[0]["credit"] == 0.55 and events[0]["client_order_id"] == base1


def test_attempt_exit_cancels_a_live_sibling_before_the_walk(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    monkeypatch.setattr(loop, "HALT_PATH", str(tmp_path / "HALT.json"))
    base0, base1 = "tg-x-20260831-1030-spy-s0", "tg-x-20260831-1030-spy-s1"
    lookups = {base0: STALE_CANCELED, base0 + "r2": None,
               base1: {"id": "o-x-s1", "status": "canceled", "filled_qty": "0"}, base1 + "r2": None}
    open_orders = [{"id": "o-x-s1", "client_order_id": base1},
                   {"id": "o-force", "client_order_id": "tg-x-20260831-force09031430-spy-s0"},  # force rung -- not this ladder's
                   {"id": "o-e", "client_order_id": "tg-e-20260831-1030-spy-s1"}]              # an entry order -- untouched
    broker_calls = []
    with _recording_broker(lookups, broker_calls):
        result = loop._attempt_exit(ENTRY_REC, "take_profit", SHORT_C, LONG_C, GOV, NOW, "submission", False, [], open_orders)
    assert result == {"filled": False}
    assert broker_calls[0] == ("cancel", "o-x-s1")
    assert [c for c in broker_calls if c[0] == "submit"] == [("submit", base0 + "r2"), ("submit", base1 + "r2")]
    assert ("cancel", "o-force") not in broker_calls and ("cancel", "o-e") not in broker_calls


def test_attempt_force_close_cancels_a_live_window_ladder_exit_first(tmp_path, monkeypatch):
    # force_close is sticky by clock (risk.exit_signal), so a stop/tp exit
    # order left live by a crash in the 14:25 tick is never revisited by
    # _attempt_exit -- only the force ladder can clear it. Its prefix used
    # to be `tg-x-<date>-force`, which walked straight past it.
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    with open(loop.GOVERNANCE_PATH, encoding="utf-8") as f:
        gov = {**GOV, "exit": json.load(f)["exit"]}
    own = "tg-x-20260831-force09031430-spy-s0"
    open_orders = [{"id": "o-x-s1", "client_order_id": "tg-x-20260831-1030-spy-s1"},          # crashed window ladder
                   {"id": "o-own", "client_order_id": own},                                   # this rung's own -- adopted
                   {"id": "o-qqq", "client_order_id": "tg-x-20260831-1030-qqq-s1"}]          # other underlying -- untouched
    broker_calls = []
    with _recording_broker({own: {"id": "o-own", "status": "accepted", "filled_qty": "0"}}, broker_calls):
        result = loop._attempt_force_close(ENTRY_REC, SHORT_C, LONG_C, gov, datetime(2026, 9, 3, 14, 31, tzinfo=ET),
                                           "submission", False, open_orders)
    assert result == {"filled": False, "rung": "force09031430", "order_id": "o-own"}
    assert broker_calls == [("cancel", "o-x-s1")]


NOT_FOUND_404 = lambda cid: json.dumps({"code": 40410000, "error": f"order not found for {cid}", "status": 404})
SERVER_500 = json.dumps({"code": 50010000, "error": "internal server error", "status": 500})


class _FakeCLI:
    """alpaca.subprocess.run with the verified 30 Aug 2026 order contract
    (stdout JSON rc 0; a 404/500 body on stderr, empty stdout, rc 1) and a
    persistent order book, so a second "tick" sees what the first left
    behind. Records which orders were still live at every submit."""

    def __init__(self):
        self.orders, self.live_at_submit, self.n, self.crash_s1_polls = {}, [], 0, False

    def _by_id(self, oid):
        return next((o for o in self.orders.values() if o["id"] == oid), None)

    def live(self):
        return sorted(c for c, o in self.orders.items() if o["status"] == "accepted")

    def __call__(self, cmd, **kw):
        a = cmd[1:]
        ok = lambda body: subprocess.CompletedProcess(cmd, 0, json.dumps(body), "")
        err = lambda body: subprocess.CompletedProcess(cmd, 1, "", body)
        if a[:2] == ["order", "get-by-client-id"]:
            cid = a[a.index("--client-order-id") + 1]
            return ok(self.orders[cid]) if cid in self.orders else err(NOT_FOUND_404(cid))
        if a[:2] == ["order", "submit"]:
            cid = a[a.index("--client-order-id") + 1]
            self.live_at_submit.append((cid, self.live()))
            self.n += 1
            self.orders[cid] = {"id": f"oid-{self.n}", "client_order_id": cid, "status": "accepted", "filled_qty": "0"}
            return ok(self.orders[cid])
        if a[:2] == ["order", "get"]:
            o = self._by_id(a[a.index("--order-id") + 1])
            if self.crash_s1_polls and o["client_order_id"].endswith("-s1"):
                return err(SERVER_500)  # a transient 500 during s1's wait -> AlpacaCLIError -> tick_exception
            return ok(o)
        if a[:2] == ["order", "cancel"]:
            self._by_id(a[a.index("--order-id") + 1])["status"] = "canceled"
            return ok({})
        if a[:2] == ["order", "list"]:
            return ok([o for o in self.orders.values() if o["status"] == "accepted"])
        if a[:2] == ["position", "list"]:
            return ok([])
        raise AssertionError(f"unexpected {cmd}")


@contextlib.contextmanager
def _fake_cli(monkeypatch, tmp_path):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    monkeypatch.setattr(loop, "HALT_PATH", str(tmp_path / "HALT.json"))
    cli = _FakeCLI()
    with patch.object(alpaca, "assert_paper", lambda profile="submission": None), \
         patch("alpaca.subprocess.run", cli), patch("alpaca.time.sleep", lambda s: None):
        yield cli


def test_attempt_entry_crash_mid_s1_then_next_tick_never_submits_beside_a_live_order(tmp_path, monkeypatch):
    # The review's repro, end to end through the real alpaca._run parse and
    # the real tick-start alpaca.list_orders fetch: tick 1 dies in s1's
    # wait and leaves s1 live; tick 2 must clear it before s0r2 goes out.
    with _fake_cli(monkeypatch, tmp_path) as cli:
        cli.crash_s1_polls = True
        with pytest.raises(alpaca.AlpacaCLIError):
            loop._attempt_entry(PLAN, 1, "1030", "20260831", NOW, GOV, "submission", False, alpaca.list_orders(status="open"))
        assert cli.live() == ["tg-e-20260831-1030-spy-s1"]
        cli.crash_s1_polls = False
        next_tick = datetime(2026, 8, 31, 10, 36, tzinfo=ET)
        result = loop._attempt_entry(PLAN, 1, "1030", "20260831", next_tick, GOV, "submission", False,
                                     alpaca.list_orders(status="open"))
    assert result == {"filled": False, "stage": "s1"}
    assert [cid for cid, _ in cli.live_at_submit] == ["tg-e-20260831-1030-spy-s0", "tg-e-20260831-1030-spy-s1",
                                                       "tg-e-20260831-1030-spy-s0r2", "tg-e-20260831-1030-spy-s1r2"]
    assert all(live == [] for _, live in cli.live_at_submit), cli.live_at_submit
    assert cli.live() == []


def test_attempt_exit_crash_mid_s1_then_next_tick_never_submits_beside_a_live_order(tmp_path, monkeypatch):
    with _fake_cli(monkeypatch, tmp_path) as cli:
        cli.crash_s1_polls = True
        with pytest.raises(alpaca.AlpacaCLIError):
            loop._attempt_exit(ENTRY_REC, "stop_loss", SHORT_C, LONG_C, GOV, NOW, "submission", False, [],
                               alpaca.list_orders(status="open"))
        assert cli.live() == ["tg-x-20260831-1030-spy-s1"]
        cli.crash_s1_polls = False
        result = loop._attempt_exit(ENTRY_REC, "stop_loss", SHORT_C, LONG_C, GOV, NOW, "submission", False,
                                    loop._read_journal(), alpaca.list_orders(status="open"))
    assert result == {"filled": False}
    assert all(live == [] for _, live in cli.live_at_submit), cli.live_at_submit
    assert cli.live() == []


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


# --- 30 Aug 2026 review hardening ------------------------------------------

def test_fresh_close_quotes_tolerates_zero_bid_long_leg():
    snaps = {
        "SPY260908P00700000": {"latestQuote": {"bp": 0.40, "ap": 0.50, "t": "2026-09-03T18:30:00Z"}, "greeks": {"delta": -0.1}},
        "SPY260908P00695000": {"latestQuote": {"bp": 0, "ap": 0.05, "t": "2026-09-03T18:30:00Z"}, "greeks": {"delta": -0.05}},
    }
    with patch("loop.alpaca.option_chain", return_value={"snapshots": snaps}):
        short_c, long_c = loop._fresh_close_quotes("SPY", "2026-09-08", "SPY260908P00700000", "SPY260908P00695000", "submission")
    assert short_c.mid == 0.45 and long_c.bid == 0.0 and long_c.ask == 0.05


def test_run_tick_guarded_marks_git_exception_as_publish_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    now = datetime(2026, 8, 31, 10, 31, tzinfo=ET)
    with patch("loop._run_tick_body", return_value={"ok": True, "now": now.isoformat()}), \
         patch("loop._git_publish", return_value={"committed": False, "error": "TimeoutExpired: git push"}):
        summary = loop._run_tick_guarded(now, False, "submission")
    assert summary["ok"] is False
    assert any(e["event"] == "journal_publish_failed" for e in loop._read_journal())


# --- 30 Aug 2026 re-verify: a swept sibling must be PROVABLY dead before the ladder submits ---

def _sweep_case(tmp_path, monkeypatch, sibling_after_cancel):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    monkeypatch.setattr(loop, "HALT_PATH", str(tmp_path / "HALT.json"))
    base1 = "tg-e-20260831-1030-spy-s1"
    with patch("loop.alpaca.cancel_order", return_value={}), \
         patch("loop.alpaca.poll_until_filled", return_value={"id": "o-s1", "client_order_id": base1, **sibling_after_cancel}), \
         patch("loop.alpaca.get_order", return_value={"id": "o-s1", "client_order_id": base1, **sibling_after_cancel}), \
         patch("loop.alpaca.positions", return_value=[]), \
         patch("loop.alpaca.get_order_by_client_id", side_effect=AssertionError("must not start the walk")), \
         patch("loop.alpaca.submit_mleg", side_effect=AssertionError("must not submit beside a live/partial sibling")):
        result = loop._attempt_entry(PLAN, 1, "1030", "20260831", NOW, GOV, "submission", False,
                                     [{"id": "o-s1", "client_order_id": base1}])
    return result, [e["event"] for e in loop._read_journal()]


def test_entry_sweep_gives_up_on_a_partially_filled_sibling(tmp_path, monkeypatch):
    result, events = _sweep_case(tmp_path, monkeypatch, {"status": "canceled", "filled_qty": "1"})
    assert result["failed"] is True and result["stale_unresolved"] == "tg-e-20260831-1030-spy-s1"
    assert events == ["entry_stale_unresolved"]


def test_entry_sweep_gives_up_when_the_cancel_is_still_pending(tmp_path, monkeypatch):
    for status in ("pending_cancel", "accepted"):
        result, events = _sweep_case(tmp_path, monkeypatch, {"status": status, "filled_qty": "0"})
        assert result["failed"] is True and events[-1] == "entry_stale_unresolved"


def test_exit_sweep_gives_up_when_the_cancel_is_still_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    monkeypatch.setattr(loop, "HALT_PATH", str(tmp_path / "HALT.json"))
    base1 = "tg-x-20260831-1030-spy-s1"
    with patch("loop.alpaca.cancel_order", return_value={}), \
         patch("loop.alpaca.poll_until_filled", return_value={"id": "o-x-s1", "status": "pending_cancel", "filled_qty": "0"}), \
         patch("loop.alpaca.positions", return_value=[]), \
         patch("loop.alpaca.get_order_by_client_id", side_effect=AssertionError("must not start the walk")), \
         patch("loop.alpaca.submit_mleg", side_effect=AssertionError("must not submit")):
        result = loop._attempt_exit(ENTRY_REC, "take_profit", SHORT_C, LONG_C, GOV, NOW, "submission", False, [],
                                    [{"id": "o-x-s1", "client_order_id": base1}])
    assert result["failed"] is True
    assert [e["event"] for e in loop._read_journal()] == ["exit_stale_unresolved"]


def test_exit_ladder_floors_a_worthless_spread_at_one_cent(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    dead_short = spread.Contract(symbol=SHORT_C.symbol, strike=700.0, delta=-0.01, iv=0.2, bid=0.0, ask=0.01, expiry="2026-09-08")
    dead_long = spread.Contract(symbol=LONG_C.symbol, strike=695.0, delta=-0.01, iv=0.2, bid=0.0, ask=0.01, expiry="2026-09-08")
    calls = []
    with _recording_broker({"tg-x-20260831-1030-spy-s0": None, "tg-x-20260831-1030-spy-s1": None}, calls):
        loop._attempt_exit(ENTRY_REC, "take_profit", dead_short, dead_long, GOV, NOW, "submission", False, [], [])
    intents = [e for e in loop._read_journal() if e["event"] == "exit_intent"]
    assert intents and all(e["limit_price"] >= 0.01 for e in intents)


def test_main_refuses_a_live_tick_outside_github_actions():
    import os, subprocess, sys
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
    proc = subprocess.run([sys.executable, "loop.py", "--once"], capture_output=True, text=True, env=env)
    assert proc.returncode != 0 and "refusing a live tick" in proc.stderr


# ---------------------------------------------------------------------------
# available_underlyings pre-filter (ANALYSIS strategy-pnl-2, 31 Aug 2026):
# the brain must not be asked to pick from a book that is already full, and
# an at-cap book must not bill a model call at all.
# ---------------------------------------------------------------------------

CAP_GOV = {
    "strategy": {"underlyings": ["SPY", "QQQ"], "dte_min": 6, "dte_max": 9},
    "risk": {"max_concurrent_positions": 2, "max_positions_per_underlying": 1,
             "max_filled_entries_per_underlying_per_session": 1},
    "entry": {"max_new_entries_per_session": 2, "event_calendar_path": "unused"},
    "regime": {"vix_source_url_template": "unused"},
    "vrp": {"realised_vol_lookback_days": 10},
}


def test_available_underlyings_reflects_every_cap():
    assert loop._available_underlyings(CAP_GOV, NOW, [], 0, []) == ["SPY", "QQQ"]
    spy_open = [{"underlying": "SPY"}]
    assert loop._available_underlyings(CAP_GOV, NOW, spy_open, 1, ["SPY"]) == ["QQQ"]
    # a closed SPY round trip still blocks a same-day SPY re-entry (daily fill cap)
    assert loop._available_underlyings(CAP_GOV, NOW, [], 1, ["SPY"]) == ["QQQ"]
    both_open = [{"underlying": "SPY"}, {"underlying": "QQQ"}]
    assert loop._available_underlyings(CAP_GOV, NOW, both_open, 2, ["SPY", "QQQ"]) == []
    # the session entry cap alone empties the list
    assert loop._available_underlyings(CAP_GOV, NOW, [], 2, []) == []


def test_pipeline_skips_the_model_call_when_every_underlying_is_at_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    with patch("loop.market.build_regime_state", side_effect=AssertionError("must not fetch")), \
         patch("loop.brain.propose", side_effect=AssertionError("must not call the model")):
        result = loop._attempt_entry_pipeline(
            "1030", NOW, CAP_GOV, "submission", False, {},
            [{"underlying": "SPY"}, {"underlying": "QQQ"}], 2, ["SPY", "QQQ"], 0, False, [])
    assert result == {"attempted": True, "filled": False, "reason": "all_underlyings_at_cap"}
    assert [e["reason"] for e in loop._read_journal()] == ["all_underlyings_at_cap"]


def test_pipeline_backstops_a_pick_outside_available(tmp_path, monkeypatch):
    # SPY is open; only QQQ is fetched and offered. The model picks SPY
    # anyway -> deterministic no_trade before any chain is priced.
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    import brain
    regime = {"vix": 14.0, "vix9d": 12.0, "vix3m": 17.0, "event_blackouts": []}
    qqq_state = {"spot": 570.0, "realised_vol": 0.10, "prior_close": 569.0,
                 "intraday_move_pct": 0.001, "contracts": []}
    pr = brain.ProposeResult(
        proposal=brain.Proposal("SPY", "neutral", 0.6, "thesis", "invalidation"),
        schema_version="brain-v1", model="m", latency_seconds=0.1, raw_response="{}")
    with patch("loop.market.build_regime_state", return_value=regime), \
         patch("loop.market.build_underlying_state", return_value=qqq_state) as bus, \
         patch("loop.brain.propose", return_value=pr) as propose, \
         patch("loop.spread.rank_candidates", side_effect=AssertionError("must not price a chain")):
        result = loop._attempt_entry_pipeline(
            "1030", NOW, CAP_GOV, "submission", False, {},
            [{"underlying": "SPY"}], 1, ["SPY"], 0, False, [])
    assert result == {"attempted": True, "filled": False, "reason": "underlying_unavailable"}
    assert bus.call_count == 1 and bus.call_args.args[0] == "QQQ"
    assert propose.call_args.args[0]["available_underlyings"] == ["QQQ"]
    no_trades = [e for e in loop._read_journal() if e["event"] == "no_trade"]
    assert no_trades[-1]["reason"] == "underlying_unavailable" and no_trades[-1]["underlying"] == "SPY"
# Thursday's force-close ladder
# ---------------------------------------------------------------------------
#
# This is the highest-stakes untested code in the repo. As of 31 Aug the
# agent has opened a position and NEVER closed one -- exit_intent,
# exit_filled and exit_unfilled are all zero across every session, so the
# entire close-out path has only ever run in tests. On Thursday 3 Sep it
# becomes mandatory: it is what decides whether the book is flat and the
# reported P&L is a settled number.
#
# There was no way to rehearse it against the live broker (the ladder is
# date-triggered and the credentials are not local), so it is exercised
# here at each rung instead, with the real governance.json.

import json as _json  # noqa: E402

FC_GOV = _json.load(open("governance.json"))


def _fc_contracts():
    short = spread.Contract(symbol="SPY260909P00754000", strike=754.0, delta=-0.20, iv=0.11,
                            bid=1.00, ask=1.10, expiry="2026-09-09")
    long_ = spread.Contract(symbol="SPY260909P00749000", strike=749.0, delta=-0.12, iv=0.12,
                            bid=0.50, ask=0.60, expiry="2026-09-09")
    return short, long_


def _fc_entry():
    return {"position_id": "tg-e-20260831-1030-spy", "underlying": "SPY", "direction": "bull_put",
            "expiry": "2026-09-09", "width": 5.0, "credit": 0.61, "qty": 1, "_close_qty": 1,
            "trade_date": "20260831", "short_symbol": "SPY260909P00754000",
            "long_symbol": "SPY260909P00749000", "window": "1030"}


def _fc_no_broker(monkeypatch):
    """Stub the one call that reaches the broker. dry_run alone is not
    enough: _lookup_or_submit runs alpaca.assert_paper first, by design --
    paper is re-proved before every order path, so it needs the CLI even
    when the write itself is held back. The ladder's own logic (rung,
    price, id, cancel-first) is what these tests are about."""
    monkeypatch.setattr(loop, "_lookup_or_submit",
                        lambda cid, legs, limit, qty, profile, dry_run: ({}, "dry_run", cid))


def _fc_run(at, monkeypatch, tmp_path, open_orders=None, submitted=None):
    """Drive one rung. dry_run=True so no broker write is attempted; the
    intent journal row still records the price the ladder chose."""
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "j.jsonl"))
    _fc_no_broker(monkeypatch)
    short, long_ = _fc_contracts()
    now = datetime.fromisoformat(f"2026-09-03T{at}:00").replace(tzinfo=ET)
    result = loop._attempt_force_close(_fc_entry(), short, long_, FC_GOV, now,
                                       "submission", True, open_orders or [])
    return result, loop._read_journal()


@pytest.mark.parametrize("at,action,price", [
    # mid = 1.05 - 0.55 = 0.50 ; natural = ask - bid = 1.10 - 0.50 = 0.60
    ("14:30", "limit_at_mid", 0.50),
    ("15:00", "cross_the_spread", 0.60),
    ("15:30", "market_mleg", 0.65),          # natural + 0.05
])
def test_each_force_close_rung_picks_its_action_and_price(at, action, price, monkeypatch, tmp_path):
    """governance.exit.force_close_ladder escalates 14:30 -> 15:00 -> 15:30.
    Getting the price wrong per rung means either never filling (too
    passive at 15:30) or overpaying from the first attempt."""
    result, events = _fc_run(at, monkeypatch, tmp_path)
    intent = [e for e in events if e["event"] == "exit_intent"][0]
    assert intent["action"] == action
    assert intent["limit_price"] == pytest.approx(price)
    assert intent["reason"] == "force_close"
    assert result["filled"] is False and result["dry_run"] is True


def test_the_final_rung_alerts_instead_of_ordering(monkeypatch, tmp_path):
    """15:45 is reconcile_and_alert. It must NOT submit -- 15 minutes
    before the close, a fresh order that half-fills leaves a naked leg
    overnight with nobody watching. It journals CRITICAL and stops."""
    result, events = _fc_run("15:45", monkeypatch, tmp_path)
    assert result["filled"] is False
    assert not [e for e in events if e["event"] == "exit_intent"], "must not order at the final rung"
    alert = [e for e in events if e["event"] == "force_close_unresolved"]
    assert len(alert) == 1 and alert[0]["level"] == "critical"


def test_the_market_rung_never_pays_more_than_the_spread_is_worth(monkeypatch, tmp_path):
    """market_mleg is natural + 0.05, bounded by width - 0.01. On a $5
    spread, paying $5 to close guarantees the full loss with certainty --
    worse than letting it expire."""
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "j.jsonl"))
    _fc_no_broker(monkeypatch)
    # A blown-out quote: natural debit would be 4.99 + 0.05 = 5.04 > width.
    short = spread.Contract(symbol="SPY260909P00754000", strike=754.0, delta=-0.9, iv=0.4,
                            bid=4.90, ask=5.00, expiry="2026-09-09")
    long_ = spread.Contract(symbol="SPY260909P00749000", strike=749.0, delta=-0.7, iv=0.4,
                            bid=0.01, ask=0.10, expiry="2026-09-09")
    now = datetime.fromisoformat("2026-09-03T15:30:00").replace(tzinfo=ET)
    loop._attempt_force_close(_fc_entry(), short, long_, FC_GOV, now, "submission", True, [])
    intent = [e for e in loop._read_journal() if e["event"] == "exit_intent"][0]
    assert intent["limit_price"] == pytest.approx(4.99)
    assert intent["limit_price"] < _fc_entry()["width"]


def test_the_rung_tag_carries_the_date(monkeypatch, tmp_path):
    """The client_order_id's date slot is the POSITION's trade_date, not
    today's. Without the date in the rung tag, a position still open on
    Friday computes exactly Thursday's ids and adopts Thursday's stale
    cancelled orders -- found in review 30 Aug."""
    _, thu = _fc_run("14:30", monkeypatch, tmp_path)
    thu_id = [e for e in thu if e["event"] == "exit_intent"][0]["client_order_id"]
    assert "force0903" in thu_id, thu_id

    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "friday.jsonl"))
    _fc_no_broker(monkeypatch)
    short, long_ = _fc_contracts()
    friday = datetime.fromisoformat("2026-09-04T14:30:00").replace(tzinfo=ET)
    loop._attempt_force_close(_fc_entry(), short, long_, FC_GOV, friday, "submission", True, [])
    fri_id = [e for e in loop._read_journal() if e["event"] == "exit_intent"][0]["client_order_id"]
    assert "force0904" in fri_id
    assert fri_id != thu_id, "Friday must not reuse Thursday's order id"


def test_an_earlier_rungs_order_is_cancelled_before_the_next_is_sent(monkeypatch, tmp_path):
    """Two live closing orders on one position can both fill and leave a
    reversed position. Each rung cancels any other exit order for this
    underlying first."""
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "j.jsonl"))
    cancelled = []
    monkeypatch.setattr(loop, "_cancel_and_confirm",
                        lambda oid, p, g, d: (cancelled.append(oid), {"status": "canceled"})[1])
    monkeypatch.setattr(loop, "_stale_cancel_settled", lambda o: True)
    monkeypatch.setattr(loop, "_check_leg_symmetry", lambda *a, **k: True)
    _fc_no_broker(monkeypatch)

    stale = [{"id": "ord-1430", "client_order_id": "tg-x-20260831-force09031430-spy-s0"}]
    short, long_ = _fc_contracts()
    now = datetime.fromisoformat("2026-09-03T15:00:00").replace(tzinfo=ET)
    loop._attempt_force_close(_fc_entry(), short, long_, FC_GOV, now, "submission", True, stale)

    assert cancelled == ["ord-1430"], "the 14:30 order must be cancelled before the 15:00 rung"
    events = loop._read_journal()
    assert any(e["event"] == "force_close_stale_canceled" for e in events)


def test_a_stale_order_that_wins_the_race_is_reported_not_re_ordered(monkeypatch, tmp_path):
    """Alpaca does not guarantee a cancel beats a fill in flight. If the
    earlier rung actually filled, the position is closed -- submitting the
    next rung on top would open a new one in the opposite direction."""
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "j.jsonl"))
    monkeypatch.setattr(loop, "_cancel_and_confirm",
                        lambda oid, p, g, d: {"status": "filled", "id": oid,
                                              "filled_avg_price": "0.50", "client_order_id": "x"})
    monkeypatch.setattr(loop, "_confirm_flat", lambda *a, **k: True)

    stale = [{"id": "ord-1430", "client_order_id": "tg-x-20260831-force09031430-spy-s0"}]
    short, long_ = _fc_contracts()
    now = datetime.fromisoformat("2026-09-03T15:00:00").replace(tzinfo=ET)
    result = loop._attempt_force_close(_fc_entry(), short, long_, FC_GOV, now, "submission", True, stale)

    assert result["filled"] is True and result.get("raced_stale_fill") is True
    events = loop._read_journal()
    assert any(e["event"] == "exit_filled" for e in events)
    assert not [e for e in events if e["event"] == "exit_intent"], "must not order on top of a fill"
