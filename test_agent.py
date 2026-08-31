"""All tests, one file, inline fixtures. The chain data below is not
synthetic — it's the real SPY 7-DTE (2026-09-02 expiry) put chain captured
live on 26 Aug 2026, the same chain that produced the real fill proving the
mleg body shape. See docs in the plan for the probe.
"""

import math
import statistics
import subprocess
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

import alpaca
import market
import risk
import spread

ET = ZoneInfo("America/New_York")

GOV = {
    "strategy": {
        "underlyings": ["SPY", "QQQ"], "structure": "vertical", "legs": 2,
        "width_dollars": 5, "dte_min": 6, "dte_max": 9,
        "short_delta_min": 0.16, "short_delta_max": 0.25,
        "credit_quality_expected_ratio": 0.8, "credit_quality_max_deviation": 0.40,
        "min_credit_pct_of_width": 0.10, "fixed_quantity": 1,
    },
    "entry": {
        "windows_et": ["10:30", "13:30"], "max_new_entries_per_session": 2,
        "no_entries_after_date": "2026-09-02", "no_entries_after_time_et": "10:45",
    },
    "exit": {
        "take_profit_pct_of_credit": 0.50, "stop_close_debit_multiple": 2.0,
        "time_exit_dte": 2, "force_close_start_date": "2026-09-03",
        "force_close_start_time_et": "14:30",
        "force_close_ladder": [
            {"at_et": "14:30", "action": "limit_at_mid"},
            {"at_et": "15:00", "action": "cross_the_spread"},
            {"at_et": "15:30", "action": "market_mleg"},
            {"at_et": "15:45", "action": "reconcile_and_alert"},
        ],
    },
    "risk": {
        "max_loss_per_trade_dollars": 1000, "max_total_open_risk_dollars": 3000,
        "max_concurrent_positions": 2, "max_positions_per_underlying": 1,
        "max_filled_entries_per_underlying_per_session": 1,
        "options_buying_power_floor_dollars": 25000,
        "options_buying_power_floor_multiple_of_max_loss": 5,
        "daily_drawdown_halt_pct": -0.01,
        "cumulative_drawdown_halt_equity_dollars": 98000,
        "starting_equity_dollars": 100000,
    },
    "quote_sanity": {"min_bid_dollars": 0.01, "max_spread_pct_of_mid": 0.15, "max_quote_age_seconds": 60},
    "regime": {
        "vix_max_exclusive": 30.0, "require_vix9d_lt_vix3m": True,
        "intraday_move_abs_max_exclusive": 0.020,
    },
    "vrp": {"realised_vol_lookback_days": 20, "require_atm_iv_gte_realised_vol": True, "min_vrp_points": 2.0},
    "environment": {
        "paper_flag_true_values": ["true", "1", "yes"],
        "required_endpoint": "https://paper-api.alpaca.markets",
        "required_account_status": ["ACTIVE", "PAPER_ONLY"],
        "required_effective_options_level": 3,
    },
    "operational": {
        "unfilled_order_cancel_after_seconds": 60, "order_poll_max_attempts": 60,
        "no_bulk_operations": True, "max_loop_exceptions_before_halt": 3,
    },
}

# Real SPY put chain, 2026-09-02 expiry, captured live 26 Aug 2026. `NOW`
# below is set to that same capture date — 7 calendar DTE, inside the 6-9
# window — rather than an arbitrary later date, since this is the actual
# instant the quotes (and their timestamps) were observed.
_CAPTURE_QUOTE_TS = datetime(2026, 8, 26, 11, 0, tzinfo=ET).timestamp()
REAL_CHAIN_SNAPSHOTS = {
    "SPY260902P00749000": {"latestQuote": {"bp": 0.98, "ap": 1.01, "t": "2026-08-26T15:00:00Z"}, "greeks": {"delta": -0.1279}, "impliedVolatility": 0.145},
    "SPY260902P00752000": {"latestQuote": {"bp": 1.29, "ap": 1.33, "t": "2026-08-26T15:00:00Z"}, "greeks": {"delta": -0.1658}, "impliedVolatility": 0.144},
    "SPY260902P00753000": {"latestQuote": {"bp": 1.42, "ap": 1.46, "t": "2026-08-26T15:00:00Z"}, "greeks": {"delta": -0.1806}, "impliedVolatility": 0.144},
    "SPY260902P00754000": {"latestQuote": {"bp": 1.57, "ap": 1.61, "t": "2026-08-26T15:00:00Z"}, "greeks": {"delta": -0.1969}, "impliedVolatility": 0.144},
    "SPY260902P00755000": {"latestQuote": {"bp": 1.73, "ap": 1.76, "t": "2026-08-26T15:00:00Z"}, "greeks": {"delta": -0.2140}, "impliedVolatility": 0.143},
    "SPY260902P00756000": {"latestQuote": {"bp": 1.90, "ap": 1.95, "t": "2026-08-26T15:00:00Z"}, "greeks": {"delta": -0.2329}, "impliedVolatility": 0.143},
}


def base_state(**overrides):
    state = {
        "paper_verified": True,
        "halt_active": False,
        "account_status": "ACTIVE",
        "trading_blocked": False,
        "options_approved_level": 3,
        "options_configured_max_level": 3,
        "open_positions": [],
        "entries_today": 0,
        "equity": 100000,
        "session_start_equity": 100000,
        "options_buying_power": 100000,
        "consecutive_exceptions": 0,
        "atm_iv": 0.15,
        "realised_vol_20d": 0.12,
        # Real Cboe close values, 27 Aug 2026 (verified live in an earlier
        # session) — a genuine passing regime, not an arbitrary fixture.
        "vix": 14.51,
        "vix9d": 12.10,
        "vix3m": 17.56,
        "intraday_move_pct": 0.004,
        "filled_underlyings_today": [],
        "event_blackouts": [],
    }
    state.update(overrides)
    return state


def real_plan():
    contracts = spread.parse_chain(REAL_CHAIN_SNAPSHOTS)
    plan = spread.pick_spread(
        contracts, direction="bull_put", width=5,
        delta_min=GOV["strategy"]["short_delta_min"], delta_max=GOV["strategy"]["short_delta_max"],
    )
    return spread.SpreadPlan(
        underlying="SPY", direction=plan.direction, expiry="2026-09-02",
        short=plan.short, long=plan.long, width=plan.width, credit=plan.credit,
        qty=0, max_loss_dollars=plan.max_loss_dollars,
    )


NOW = datetime(2026, 8, 26, 11, 0, tzinfo=ET)


# ---------------------------------------------------------------------------
# spread.py
# ---------------------------------------------------------------------------

def test_pick_spread_matches_the_real_traded_strikes():
    """This must reproduce the exact trade proven live on 26 Aug 2026:
    short 754 (delta -0.1969), long 749, credit 0.60."""
    plan = real_plan()
    assert plan.short.symbol == "SPY260902P00754000"
    assert plan.long.symbol == "SPY260902P00749000"
    assert plan.credit == pytest.approx(0.60, abs=0.01)


def test_pick_spread_returns_none_when_no_strike_qualifies():
    contracts = spread.parse_chain(REAL_CHAIN_SNAPSHOTS)
    result = spread.pick_spread(contracts, direction="bull_put", width=5, delta_min=0.90, delta_max=0.99)
    assert result is None


def test_mleg_body_shape():
    plan = real_plan()
    body = spread.mleg_body(plan, qty=2)

    assert body["order_class"] == "mleg"
    assert float(body["limit_price"]) < 0, "credit spread must have a NEGATIVE limit_price"
    assert body["qty"] == "2"
    assert "symbol" not in body
    assert "side" not in body
    assert len(body["legs"]) == 2

    short_leg = next(l for l in body["legs"] if l["symbol"] == plan.short.symbol)
    long_leg = next(l for l in body["legs"] if l["symbol"] == plan.long.symbol)
    assert short_leg["side"] == "sell"
    assert short_leg["position_intent"] == "sell_to_open"
    assert long_leg["side"] == "buy"
    assert long_leg["position_intent"] == "buy_to_open"


def test_ratio_qty_gcd_one():
    plan = real_plan()
    body = spread.mleg_body(plan, qty=1)
    for leg in body["legs"]:
        assert leg["ratio_qty"] == "1"


def test_parse_chain_extracts_expiry_from_occ_symbol():
    contracts = spread.parse_chain(REAL_CHAIN_SNAPSHOTS)
    assert all(c.expiry == "2026-09-02" for c in contracts)


def test_rank_candidates_never_crosses_expiries():
    """A second, synthetic expiry (2026-09-09) reuses the exact same
    strikes as the real chain. pick_spread must never pair a short leg
    from one expiry with a same-strike long leg from the OTHER expiry —
    that would silently build a calendar spread while claiming to be a
    same-expiry vertical."""
    later_expiry_snapshots = {
        sym.replace("260902", "260909"): snap
        for sym, snap in REAL_CHAIN_SNAPSHOTS.items()
    }
    contracts = spread.parse_chain(REAL_CHAIN_SNAPSHOTS) + spread.parse_chain(later_expiry_snapshots)
    assert {c.expiry for c in contracts} == {"2026-09-02", "2026-09-09"}

    ranked = spread.rank_candidates(
        contracts, direction="bull_put", width=5,
        delta_min=GOV["strategy"]["short_delta_min"], delta_max=GOV["strategy"]["short_delta_max"],
        now=NOW,
    )
    assert len(ranked) == 2
    for plan in ranked:
        assert plan.short.expiry == plan.long.expiry == plan.expiry


def test_client_order_id_deterministic():
    """The entire no-DB idempotency design leans on this: same inputs must
    always produce the same id, so a crashed-and-retried tick recomputes it
    and looks it up instead of resubmitting. Verified live 29 Aug 2026 that
    Alpaca rejects a resubmitted duplicate id (422) rather than duplicating
    the order."""
    a = spread.client_order_id("e", "20260831", "1030", "SPY", "s0")
    b = spread.client_order_id("e", "20260831", "1030", "SPY", "s0")
    assert a == b
    assert a == "tg-e-20260831-1030-spy-s0"

    different_window = spread.client_order_id("e", "20260831", "1330", "SPY", "s0")
    assert different_window != a


# ---------------------------------------------------------------------------
# risk.py — sizing
# ---------------------------------------------------------------------------

def test_fixed_quantity_sizing():
    """Canonical plan Sec 2.12: exactly one contract, always — not computed
    from a max-loss budget. gate_max_loss_per_trade independently rejects
    any hand-built qty that would breach the cap regardless of what
    size_position returned, so a qty of 3 must still be rejected."""
    plan = real_plan()
    qty = risk.size_position(plan, GOV)
    assert qty == 1

    state = base_state()
    reason = risk.gate_max_loss_per_trade(state, plan, GOV, NOW, qty=3)
    assert reason is not None
    assert "max_loss_per_trade" in reason


def test_size_position_returns_zero_when_even_one_contract_breaches_cap():
    plan = real_plan()
    tight_gov = {**GOV, "risk": {**GOV["risk"], "max_loss_per_trade_dollars": 100}}
    assert risk.size_position(plan, tight_gov) == 0


def test_buying_power_floor_uses_width_not_max_loss():
    """Verified live: margin held is width x 100 x qty, not max loss."""
    plan = real_plan()
    qty = 2
    margin_required = plan.width * 100 * qty  # $1000, not (5-0.6)*100*2=$880
    state = base_state(options_buying_power=margin_required + 24000)  # just under the $25k floor after
    reason = risk.gate_buying_power_floor(state, plan, GOV, NOW, qty)
    assert reason is not None
    assert "buying_power_floor" in reason


# ---------------------------------------------------------------------------
# risk.py — gates
# ---------------------------------------------------------------------------

def test_rejects_missing_greeks():
    good = spread.parse_chain(REAL_CHAIN_SNAPSHOTS)
    plan = real_plan()
    naked_short = spread.Contract(symbol="SPY260828P00754000", strike=754, delta=None, iv=None, bid=1.0, ask=1.1)
    broken_plan = spread.SpreadPlan(
        underlying="SPY", direction="bull_put", expiry="2026-09-02",
        short=naked_short, long=plan.long, width=5, credit=0.5, qty=0, max_loss_dollars=450,
    )
    reason = risk.gate_greeks_present(base_state(), broken_plan, GOV, NOW)
    assert reason is not None
    assert "greeks_present" in reason


def test_credit_quality_relative_band():
    """Verified live: ratio ~= 0.8 x |delta|. The real trade's ratio (0.12)
    should pass; a wildly off ratio should not."""
    plan = real_plan()
    reason = risk.gate_credit_quality(base_state(), plan, GOV, NOW)
    assert reason is None

    bad_plan = spread.SpreadPlan(
        underlying="SPY", direction="bull_put", expiry="2026-09-02",
        short=plan.short, long=plan.long, width=5, credit=4.50, qty=0, max_loss_dollars=50,
    )
    reason = risk.gate_credit_quality(base_state(), bad_plan, GOV, NOW)
    assert reason is not None


def test_minimum_credit_floor():
    """Fable 5 review: the real trade's ratio (0.12) clears the 0.10 floor;
    a thin quote at the low-delta end of the band must not."""
    plan = real_plan()
    reason = risk.gate_minimum_credit(base_state(), plan, GOV, NOW)
    assert reason is None

    thin_plan = spread.SpreadPlan(
        underlying="SPY", direction="bull_put", expiry="2026-09-02",
        short=plan.short, long=plan.long, width=5, credit=0.40, qty=0, max_loss_dollars=460,
    )
    reason = risk.gate_minimum_credit(base_state(), thin_plan, GOV, NOW)
    assert reason is not None
    assert "minimum_credit" in reason


def test_resolve_direction_routes_put_only():
    """Canonical plan Sec 6.1 (HARD_SAFETY), 29 Aug 2026: bearish is always
    NO_TRADE, never a call-side substitution."""
    assert risk.resolve_direction("bullish") == "bull_put"
    assert risk.resolve_direction("neutral") == "bull_put"
    assert risk.resolve_direction("bearish") is None
    with pytest.raises(ValueError):
        risk.resolve_direction("sideways")


def test_gate_vix_zone():
    plan = real_plan()
    assert risk.gate_vix_zone(base_state(), plan, GOV, NOW) is None

    hot = base_state(vix=31.0)
    reason = risk.gate_vix_zone(hot, plan, GOV, NOW)
    assert reason is not None and "vix_zone" in reason

    inverted = base_state(vix9d=20.0, vix3m=15.0)
    reason = risk.gate_vix_zone(inverted, plan, GOV, NOW)
    assert reason is not None and "vix_zone" in reason


def test_gate_intraday_shock():
    plan = real_plan()
    assert risk.gate_intraday_shock(base_state(), plan, GOV, NOW) is None

    shocked = base_state(intraday_move_pct=-0.025)
    reason = risk.gate_intraday_shock(shocked, plan, GOV, NOW)
    assert reason is not None and "intraday_shock" in reason


def test_gate_event_blackout():
    plan = real_plan()
    assert risk.gate_event_blackout(base_state(), plan, GOV, NOW) is None

    blocked = base_state(event_blackouts=[
        {"name": "ISM Manufacturing PMI", "start_ts": NOW.timestamp() - 60, "end_ts": NOW.timestamp() + 60},
    ])
    reason = risk.gate_event_blackout(blocked, plan, GOV, NOW)
    assert reason is not None and "event_blackout" in reason

    no_calendar = base_state(event_blackouts=None)
    reason = risk.gate_event_blackout(no_calendar, plan, GOV, NOW)
    assert reason is not None and "event_blackout" in reason


def test_gate_daily_fill_cap_per_underlying():
    plan = real_plan()  # underlying="SPY"
    assert risk.gate_daily_fill_cap_per_underlying(base_state(), plan, GOV, NOW) is None

    already_filled = base_state(filled_underlyings_today=["SPY"])
    reason = risk.gate_daily_fill_cap_per_underlying(already_filled, plan, GOV, NOW)
    assert reason is not None and "daily_fill_cap" in reason


def test_vrp_tightened_threshold():
    """Canonical plan Sec 4.6, 29 Aug 2026: 2.0-vol-point margin, not a
    plain IV>=RV check."""
    plan = real_plan()
    assert risk.gate_vrp_present(base_state(), plan, GOV, NOW) is None  # 3.0 points

    thin_vrp = base_state(atm_iv=0.125, realised_vol_20d=0.12)  # 0.5 points
    reason = risk.gate_vrp_present(thin_vrp, plan, GOV, NOW)
    assert reason is not None and "vrp_present" in reason


def test_quote_age_rejection():
    plan = real_plan()
    assert risk.gate_quote_sanity(base_state(), plan, GOV, NOW) is None

    stale_short = spread.Contract(
        symbol=plan.short.symbol, strike=plan.short.strike, delta=plan.short.delta,
        iv=plan.short.iv, bid=plan.short.bid, ask=plan.short.ask,
        quote_ts=NOW.timestamp() - 120,  # 120s old, exceeds the 60s cap
    )
    stale_plan = spread.SpreadPlan(
        underlying="SPY", direction="bull_put", expiry="2026-09-02",
        short=stale_short, long=plan.long, width=5, credit=plan.credit,
        qty=0, max_loss_dollars=plan.max_loss_dollars,
    )
    reason = risk.gate_quote_sanity(base_state(), stale_plan, GOV, NOW)
    assert reason is not None and "quote_sanity" in reason


def test_cumulative_drawdown_halts():
    plan = real_plan()
    state = base_state(equity=95900)
    reason = risk.gate_cumulative_drawdown(state, plan, GOV, NOW)
    assert reason is not None
    assert "cumulative_drawdown" in reason


def test_deadline_blocks_opens_after_wednesday():
    plan = real_plan()
    after_cutoff = datetime(2026, 9, 3, 9, 0, tzinfo=ET)
    reason = risk.gate_deadline(base_state(), plan, GOV, after_cutoff)
    assert reason is not None
    assert "deadline" in reason

    before_cutoff = datetime(2026, 9, 2, 10, 0, tzinfo=ET)
    reason = risk.gate_deadline(base_state(), plan, GOV, before_cutoff)
    assert reason is None


def test_deadline_wednesday_1045_boundary():
    """Canonical plan Sec 4.3, 29 Aug 2026: Wednesday is morning-only. 10:44
    is still eligible; 10:45 exactly is not (the boundary is inclusive)."""
    plan = real_plan()
    just_before = datetime(2026, 9, 2, 10, 44, tzinfo=ET)
    assert risk.gate_deadline(base_state(), plan, GOV, just_before) is None

    at_boundary = datetime(2026, 9, 2, 10, 45, tzinfo=ET)
    reason = risk.gate_deadline(base_state(), plan, GOV, at_boundary)
    assert reason is not None
    assert "deadline" in reason


def test_check_all_passes_the_real_trade_end_to_end():
    plan = real_plan()
    reason, qty = risk.check_all(base_state(), plan, GOV, NOW)
    assert reason is None
    assert qty == 1


# ---------------------------------------------------------------------------
# risk.py — exits
# ---------------------------------------------------------------------------

def test_exit_thresholds():
    state = base_state()
    take_profit = {"credit": 1.00, "cost_to_close": 0.48, "dte": 5}
    assert risk.exit_signal(take_profit, state, GOV, NOW) == "take_profit"

    stop = {"credit": 1.00, "cost_to_close": 2.10, "dte": 5}
    assert risk.exit_signal(stop, state, GOV, NOW) == "stop_loss"

    hold = {"credit": 1.00, "cost_to_close": 0.80, "dte": 5}
    assert risk.exit_signal(hold, state, GOV, NOW) is None

    time_exit = {"credit": 1.00, "cost_to_close": 0.80, "dte": 1}
    assert risk.exit_signal(time_exit, state, GOV, NOW) == "time_exit"


def test_force_close_ladder_escalates():
    """Canonical plan Sec 8.2, 29 Aug 2026: ladder moved 30 min earlier
    across the board (start 14:30, forceful rung by 15:30, leaving 15
    minutes of recovery time before the 16:00 close instead of 10)."""
    state = base_state()
    position = {"credit": 1.00, "cost_to_close": 0.80, "dte": 5}

    before = datetime(2026, 9, 3, 14, 0, tzinfo=ET)
    assert risk.exit_signal(position, state, GOV, before) is None

    rung1 = datetime(2026, 9, 3, 14, 35, tzinfo=ET)
    assert risk.exit_signal(position, state, GOV, rung1).startswith("force_close")
    assert risk.force_close_action(rung1, GOV) == "limit_at_mid"

    rung2 = datetime(2026, 9, 3, 15, 5, tzinfo=ET)
    assert risk.force_close_action(rung2, GOV) == "cross_the_spread"

    rung3 = datetime(2026, 9, 3, 15, 35, tzinfo=ET)
    assert risk.force_close_action(rung3, GOV) == "market_mleg"

    rung4 = datetime(2026, 9, 3, 15, 50, tzinfo=ET)
    assert risk.force_close_action(rung4, GOV) == "reconcile_and_alert"


# ---------------------------------------------------------------------------
# risk.py — orphan detection
# ---------------------------------------------------------------------------

def test_orphan_equity_detected():
    positions = [
        {"symbol": "SPY260902P00749000", "asset_class": "us_option"},
        {"symbol": "SPY", "asset_class": "us_equity"},
    ]
    orphans = risk.detect_orphan_equity(positions)
    assert orphans == ["SPY"]


def test_no_orphan_when_all_options():
    positions = [
        {"symbol": "SPY260902P00749000", "asset_class": "us_option"},
        {"symbol": "SPY260902P00754000", "asset_class": "us_option"},
    ]
    assert risk.detect_orphan_equity(positions) == []


# ---------------------------------------------------------------------------
# alpaca.py — assert_paper's submission-account binding (mocked; no live
# CLI calls in the automated suite — the underlying facts were verified
# live once, manually, on the throwaway profile: `doctor --profile` is
# silently ignored while ALPACA_PROFILE is honored, and a resubmitted
# duplicate client_order_id gets a 422, not a second order).
# ---------------------------------------------------------------------------

def _mock_doctor_result(profile):
    result = MagicMock()
    result.stdout = f"  active profile: {profile}\n  Trading:  https://paper-api.alpaca.markets\n"
    result.stderr = ""
    return result


def test_assert_paper_accepts_matching_submission_account(monkeypatch):
    monkeypatch.setenv("ALPACA_ACCOUNT_ID", "expected-id-123")
    monkeypatch.delenv("ALPACA_LIVE_TRADE", raising=False)
    with patch("alpaca.subprocess.run", return_value=_mock_doctor_result("submission")), \
         patch.object(alpaca, "_run", return_value={"id": "expected-id-123"}):
        alpaca.assert_paper(profile="submission")  # must not raise


def test_assert_paper_rejects_account_id_mismatch(monkeypatch):
    monkeypatch.setenv("ALPACA_ACCOUNT_ID", "expected-id-123")
    monkeypatch.delenv("ALPACA_LIVE_TRADE", raising=False)
    with patch("alpaca.subprocess.run", return_value=_mock_doctor_result("submission")), \
         patch.object(alpaca, "_run", return_value={"id": "some-other-account"}):
        with pytest.raises(alpaca.NotPaperError, match="account id mismatch"):
            alpaca.assert_paper(profile="submission")


def test_assert_paper_requires_account_id_env_var(monkeypatch):
    monkeypatch.delenv("ALPACA_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("ALPACA_LIVE_TRADE", raising=False)
    with patch("alpaca.subprocess.run", return_value=_mock_doctor_result("submission")):
        with pytest.raises(alpaca.NotPaperError, match="ALPACA_ACCOUNT_ID is not set"):
            alpaca.assert_paper(profile="submission")


def test_assert_paper_rejects_wrong_active_profile(monkeypatch):
    """The bug this closes: `alpaca doctor --profile X` used to always
    report on whichever profile the CLI had active, not the one being
    checked. Simulate that stale/wrong report and confirm it now fails
    closed instead of silently passing."""
    monkeypatch.delenv("ALPACA_LIVE_TRADE", raising=False)
    with patch("alpaca.subprocess.run", return_value=_mock_doctor_result("some_other_profile")):
        with pytest.raises(alpaca.NotPaperError, match="did not confirm active profile"):
            alpaca.assert_paper(profile="paper")


# ---------------------------------------------------------------------------
# alpaca.py / market.py — option chain completeness (finding F1). Verified
# live 30 Aug 2026 (CLI 0.0.13): --limit 100 returned 100 snapshots of ONE
# expiry with next_page_token set; --limit 1000 returns the whole SPY 6-9
# DTE put window (330 snapshots, 2 expiries) in one page.
# ---------------------------------------------------------------------------

def _chain_page(symbol, token):
    return {
        "snapshots": {symbol: {"latestQuote": {"bp": 1.0, "ap": 1.1, "t": "2026-08-28T19:59:56Z"},
                               "greeks": {"delta": -0.2}, "impliedVolatility": 0.2}},
        "next_page_token": token,
    }


def test_option_chain_follows_next_page_token_and_uses_limit_1000():
    pages = [_chain_page("SPY260908P00700000", "tok"), _chain_page("SPY260909P00700000", "")]
    with patch.object(alpaca, "assert_paper", lambda profile="submission": None), \
         patch.object(alpaca, "_run", side_effect=pages) as run_mock:
        chain = alpaca.option_chain("SPY", option_type="put")

    assert set(chain["snapshots"]) == {"SPY260908P00700000", "SPY260909P00700000"}
    assert {c.expiry for c in spread.parse_chain(chain["snapshots"])} == {"2026-09-08", "2026-09-09"}
    assert chain["pages"] == 2 and chain["next_page_token"] is None

    first, second = (list(c.args) for c in run_mock.call_args_list)
    assert first[first.index("--limit") + 1] == "1000"
    assert "--page-token" not in first
    assert second[second.index("--page-token") + 1] == "tok"


def test_option_chain_passes_strike_window_flags():
    with patch.object(alpaca, "assert_paper", lambda profile="submission": None), \
         patch.object(alpaca, "_run", return_value={"snapshots": {}, "next_page_token": ""}) as run_mock:
        alpaca.option_chain("SPY", option_type="put", strike_gte=690.5, strike_lte=785.2)
    args = list(run_mock.call_args.args)
    assert args[args.index("--strike-price-gte") + 1] == "690.5"
    assert args[args.index("--strike-price-lte") + 1] == "785.2"


def test_option_chain_raises_on_page_without_snapshots():
    # The CLI prints error JSON on stdout too -- a 422 body must never
    # parse as an empty chain (which would read as "no candidates" and,
    # worse, "leg not found" on an exit).
    with patch.object(alpaca, "assert_paper", lambda profile="submission": None), \
         patch.object(alpaca, "_run", return_value={"code": 40010001, "error": "x", "status": 422}):
        with pytest.raises(RuntimeError, match="40010001"):
            alpaca.option_chain("SPY", option_type="put")


def test_build_underlying_state_passes_strike_window_around_spot():
    now = datetime(2026, 8, 31, 10, 31, tzinfo=ET)
    bars = [
        {"t": f"{(now.date() - timedelta(days=i)).isoformat()}T04:00:00Z", "c": 760.0 + i}
        for i in range(1, 26)  # 25 sessions, all strictly before now's ET date
    ]
    chain_mock = MagicMock(return_value={"snapshots": {}})
    with patch("market.alpaca.latest_quote", return_value={"quote": {"bp": 769.25, "ap": 769.57, "t": "2026-08-28T20:00:00Z"}}), \
         patch("market.alpaca.stock_bars", return_value={"bars": bars}), \
         patch("market.alpaca.option_chain", chain_mock):
        state = market.build_underlying_state("SPY", now=now, dte_min=6, dte_max=9, profile="submission")

    assert state["spot"] == pytest.approx(769.41)
    kwargs = chain_mock.call_args.kwargs
    assert kwargs["strike_gte"] == round(769.41 * 0.90, 2)
    assert kwargs["strike_lte"] == round(769.41 * 1.02, 2)
    assert kwargs["expiration_date_gte"] == "2026-09-06"
    assert kwargs["expiration_date_lte"] == "2026-09-09"
    assert kwargs["option_type"] == "put"


# ---------------------------------------------------------------------------
# market.compute_rv20 -- the window is governance vrp.realised_vol_lookback_days
# (audit finding strategy-pnl-1: the key was rendered but read by nothing).
# No behaviour change at the current value: lookback 20 == the old hardcoded
# 21-session window.
# ---------------------------------------------------------------------------

RV_NOW = datetime(2026, 8, 31, 10, 31, tzinfo=ET)
# 25 complete sessions, oldest first, non-monotone so the window actually matters.
RV_CLOSES = [760.0 + ((i * 7) % 11) - 5 for i in range(25)]


def _rv_bars(closes):
    n = len(closes)
    return [
        {"t": f"{(RV_NOW.date() - timedelta(days=n - i)).isoformat()}T04:00:00Z", "c": c}
        for i, c in enumerate(closes)
    ]


def _rv_expected(closes):
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    return statistics.stdev(log_returns) * math.sqrt(252)  # N-1, same as compute_rv20


def test_compute_rv20_default_matches_previous_21_session_window():
    bars = _rv_bars(RV_CLOSES)
    default_rv, default_prior = market.compute_rv20(bars, RV_NOW)
    kwarg_rv, kwarg_prior = market.compute_rv20(bars, RV_NOW, lookback_days=20)
    assert default_rv == kwarg_rv and default_prior == kwarg_prior
    assert default_prior == RV_CLOSES[-1]
    assert abs(default_rv - _rv_expected(RV_CLOSES[-21:])) < 1e-12


def test_compute_rv20_short_lookback_uses_fewer_sessions():
    rv, prior = market.compute_rv20(_rv_bars(RV_CLOSES), RV_NOW, lookback_days=10)
    assert abs(rv - _rv_expected(RV_CLOSES[-11:])) < 1e-12
    assert prior == RV_CLOSES[-1]  # prior_close is independent of the window
    assert market.compute_rv20(_rv_bars(RV_CLOSES[-9:]), RV_NOW, lookback_days=10) == (None, None)


def test_build_underlying_state_passes_lookback():
    rv_mock = MagicMock(return_value=(0.1, 700.0))
    with patch("market.alpaca.latest_quote", return_value={"quote": {"bp": 769.25, "ap": 769.57, "t": "2026-08-28T20:00:00Z"}}), \
         patch("market.alpaca.stock_bars", return_value={"bars": _rv_bars(RV_CLOSES)}), \
         patch("market.alpaca.option_chain", return_value={"snapshots": {}}), \
         patch("market.compute_rv20", rv_mock):
        state = market.build_underlying_state("SPY", now=RV_NOW, dte_min=6, dte_max=9, rv_lookback_days=10)
    assert rv_mock.call_args.kwargs["lookback_days"] == 10
    assert state["realised_vol_20d"] == 0.1 and state["prior_close"] == 700.0


def test_build_underlying_state_reports_real_session_count_when_short():
    with patch("market.alpaca.latest_quote", return_value={"quote": {"bp": 769.25, "ap": 769.57, "t": "2026-08-28T20:00:00Z"}}), \
         patch("market.alpaca.stock_bars", return_value={"bars": _rv_bars(RV_CLOSES[-9:])}), \
         patch("market.alpaca.option_chain", return_value={"snapshots": {}}):
        with pytest.raises(market.MarketDataError, match="fewer than 11 complete daily sessions for RV10"):
            market.build_underlying_state("SPY", now=RV_NOW, dte_min=6, dte_max=9, rv_lookback_days=10)


# ---------------------------------------------------------------------------
# alpaca.py -- the CLI's real error contract (findings F2/F19/F20). Verified
# live 30 Aug 2026 (CLI 0.0.13): an API error is an EMPTY stdout, rc 1, and
# the error JSON on STDERR; the old stdout-only parse raised 'non-JSON' on
# every order-lookup miss, so no order could ever be placed.
# ---------------------------------------------------------------------------

NOT_FOUND_404 = ('{"code": 40410000, "error": "order not found for tg-e-x", "hint": "", "method": "GET", '
                 '"path": "/v2/orders:by_client_order_id", "request_id": "r1", "status": 404}')
DUPLICATE_422 = ('{"code": 40010001, "error": "client_order_id must be unique", "hint": "Validation error", '
                 '"method": "POST", "path": "/v2/orders", "request_id": "r2", "status": 422}')


def _cli(returncode, stdout, stderr=""):
    """Stands in for alpaca.subprocess.run with the real CLI's contract."""
    return lambda cmd, **kw: subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def _no_paper():
    return patch.object(alpaca, "assert_paper", lambda profile="submission": None)


def test_run_reads_error_json_from_stderr_and_raises():
    with patch("alpaca.subprocess.run", _cli(1, "", NOT_FOUND_404)):
        with pytest.raises(alpaca.AlpacaCLIError, match="rc=1") as excinfo:
            alpaca._run("order", "get")
        assert excinfo.value.payload["status"] == 404 and excinfo.value.returncode == 1
        assert alpaca._run("order", "get", allow_error=True)["status"] == 404


def test_run_slices_a_stderr_nag_off_the_error_json():
    nag = "warning: alpaca 0.0.14 is available\n" + NOT_FOUND_404
    with patch("alpaca.subprocess.run", _cli(1, "", nag)):
        assert alpaca._run("order", "get", allow_error=True)["code"] == 40410000


def test_run_empty_stdout_rc0_is_empty_dict():
    with patch("alpaca.subprocess.run", _cli(0, "", "")):
        assert alpaca._run("order", "cancel") == {}


def test_run_non_json_raises_runtime_error_with_rc():
    with patch("alpaca.subprocess.run", _cli(1, "boom", "")):
        with pytest.raises(RuntimeError, match="rc=1") as excinfo:
            alpaca._run("clock")
    assert not isinstance(excinfo.value, alpaca.AlpacaCLIError)


def test_get_order_by_client_id_404_is_a_miss():
    with _no_paper(), patch("alpaca.subprocess.run", _cli(1, "", NOT_FOUND_404)):
        assert alpaca.get_order_by_client_id("tg-e-x") is None


def test_get_order_by_client_id_non_404_error_raises():
    unauthorized = NOT_FOUND_404.replace('"status": 404', '"status": 401')
    with _no_paper(), patch("alpaca.subprocess.run", _cli(1, "", unauthorized)):
        with pytest.raises(alpaca.AlpacaCLIError):
            alpaca.get_order_by_client_id("tg-e-x")


def test_submit_mleg_returns_rejection_body():
    legs = [{"symbol": "S"}, {"symbol": "L"}]
    with _no_paper(), patch("alpaca.subprocess.run", _cli(1, "", DUPLICATE_422)):
        response = alpaca.submit_mleg(legs, limit_price="-0.60", client_order_id="tg-e-x")
    assert response["error"] == "client_order_id must be unique" and "id" not in response


def test_cancel_order_returns_empty_dict_on_204():
    with _no_paper(), patch("alpaca.subprocess.run", _cli(0, "{}", "")):
        assert alpaca.cancel_order("1ee5812d") == {}


# --- 30 Aug 2026 review hardening: CLI parse edge cases, chain page cap ----

def _cp(returncode, stdout="", stderr=""):
    import subprocess as _sp
    return _sp.CompletedProcess(["alpaca"], returncode, stdout, stderr)


def test_run_ignores_trailing_text_after_error_json():
    body = '{"code": 40410000, "error": "order not found for x", "status": 404}\nhint: run alpaca doctor\n'
    with patch("alpaca.subprocess.run", return_value=_cp(1, "", body)):
        assert alpaca._run("order", "get", allow_error=True)["status"] == 404


def test_get_order_by_client_id_hit_without_id_raises(monkeypatch):
    monkeypatch.setattr(alpaca, "assert_paper", lambda profile="submission": None)
    for stdout in ("{}", '{"message": "too many requests", "status": 429}'):
        with patch("alpaca.subprocess.run", return_value=_cp(0, stdout, "")):
            with pytest.raises(alpaca.AlpacaCLIError):
                alpaca.get_order_by_client_id("tg-e-x")


def test_option_chain_raises_when_page_cap_is_exhausted(monkeypatch):
    monkeypatch.setattr(alpaca, "assert_paper", lambda profile="submission": None)
    endless = {"snapshots": {"SPY260908P00700000": {}}, "next_page_token": "more"}
    with patch.object(alpaca, "_run", return_value=endless) as run_mock:
        with pytest.raises(RuntimeError, match="exceeded"):
            alpaca.option_chain("SPY", "put", expiration_date="2026-09-08")
    assert run_mock.call_count == 20


def test_parse_chain_keeps_zero_bid_only_when_allowed():
    snaps = {
        "SPY260908P00695000": {"latestQuote": {"bp": 0, "ap": 0.05, "t": "2026-08-28T19:59:56Z"}, "greeks": {"delta": -0.05}},
        "SPY260908P00700000": {"latestQuote": {"bp": 0.4, "ap": 0.5, "t": "2026-08-28T19:59:56Z"}, "greeks": {"delta": -0.1}},
        "SPY260908P00690000": {"latestQuote": {"bp": 0.1, "ap": None, "t": "2026-08-28T19:59:56Z"}},  # no ask: never kept
    }
    assert [c.symbol for c in spread.parse_chain(snaps)] == ["SPY260908P00700000"]
    kept = {c.symbol: c for c in spread.parse_chain(snaps, allow_zero_bid=True)}
    assert set(kept) == {"SPY260908P00695000", "SPY260908P00700000"}
    assert kept["SPY260908P00695000"].bid == 0.0 and kept["SPY260908P00695000"].mid == 0.025


# ---------------------------------------------------------------------------
# risk.available_underlyings — advisory, and must never disagree with the gates
# ---------------------------------------------------------------------------

def _plan_for(underlying):
    """A resolved plan for `underlying`, so the same scenario can be run
    through the real gates and compared against the advisory helper."""
    base = real_plan()
    return spread.SpreadPlan(
        underlying=underlying, direction=base.direction, expiry=base.expiry,
        short=base.short, long=base.long, width=base.width, credit=base.credit,
        qty=base.qty, max_loss_dollars=base.max_loss_dollars,
    )


def _gate_allows(underlying, state):
    """True when neither per-underlying cap gate vetoes this underlying."""
    plan = _plan_for(underlying)
    return (risk.gate_concurrent(state, plan, GOV, NOW) is None
            and risk.gate_daily_fill_cap_per_underlying(state, plan, GOV, NOW) is None)


def test_both_underlyings_available_on_a_clean_session():
    state = {"open_positions": [], "entries_today": 0, "filled_underlyings_today": []}
    assert risk.available_underlyings(state, GOV) == ["SPY", "QQQ"]


def test_an_open_position_removes_only_its_own_underlying():
    """The exact 31 Aug situation: SPY filled at 10:33, so the 13:30 window
    should have been offered QQQ and only QQQ."""
    state = {"open_positions": [{"underlying": "SPY"}], "entries_today": 1,
             "filled_underlyings_today": ["SPY"]}
    assert risk.available_underlyings(state, GOV) == ["QQQ"]


def test_a_closed_round_trip_still_blocks_the_same_underlying_today():
    """gate_daily_fill_cap exists because a morning fill blocks an
    afternoon re-entry even after that spread closed. The advisory helper
    has to honour that too, or it would offer a name the gate then vetoes."""
    state = {"open_positions": [], "entries_today": 1,
             "filled_underlyings_today": ["SPY"]}
    assert risk.available_underlyings(state, GOV) == ["QQQ"]


def test_nothing_is_available_at_the_concurrent_cap():
    state = {"open_positions": [{"underlying": "SPY"}, {"underlying": "QQQ"}],
             "entries_today": 2, "filled_underlyings_today": ["SPY", "QQQ"]}
    assert risk.available_underlyings(state, GOV) == []


def test_nothing_is_available_once_the_session_entry_cap_is_hit():
    """Both names are individually free, but the session is done. Returning
    them would send the loop off to fetch two chains and bill a model call
    for a trade gate_concurrent is about to refuse."""
    state = {"open_positions": [], "entries_today": GOV["entry"]["max_new_entries_per_session"],
             "filled_underlyings_today": []}
    assert risk.available_underlyings(state, GOV) == []


@pytest.mark.parametrize("state", [
    {"open_positions": [], "entries_today": 0, "filled_underlyings_today": []},
    {"open_positions": [{"underlying": "SPY"}], "entries_today": 1, "filled_underlyings_today": ["SPY"]},
    {"open_positions": [{"underlying": "QQQ"}], "entries_today": 1, "filled_underlyings_today": ["QQQ"]},
    {"open_positions": [], "entries_today": 1, "filled_underlyings_today": ["SPY"]},
    {"open_positions": [{"underlying": "SPY"}, {"underlying": "QQQ"}], "entries_today": 2,
     "filled_underlyings_today": ["SPY", "QQQ"]},
    {"open_positions": [], "entries_today": 2, "filled_underlyings_today": []},
], ids=["clean", "spy-open", "qqq-open", "spy-closed-today", "both-open", "session-cap"])
def test_the_advisory_list_never_disagrees_with_the_gates(state):
    """THE test for this helper. It duplicates gate arithmetic rather than
    calling the gates, because the gates need a resolved SpreadPlan that
    does not exist yet at proposal time. Duplication is only safe while the
    two provably agree.

    Offering something the gates then veto wastes a window (the bug this
    fixes). Withholding something the gates would have allowed silently
    costs a trade, which is worse and much harder to notice.
    """
    advisory = risk.available_underlyings(state, GOV)
    for underlying in GOV["strategy"]["underlyings"]:
        assert (underlying in advisory) == _gate_allows(underlying, state), (
            f"{underlying}: advisory={underlying in advisory} "
            f"gates={_gate_allows(underlying, state)} for {state}")


def test_the_helper_reads_governance_not_hardcoded_names():
    """A third underlying added to governance.json must appear here without
    touching risk.py."""
    gov = {**GOV, "strategy": {**GOV["strategy"], "underlyings": ["SPY", "QQQ", "IWM"]}}
    state = {"open_positions": [], "entries_today": 0, "filled_underlyings_today": []}
    assert risk.available_underlyings(state, gov) == ["SPY", "QQQ", "IWM"]


def test_the_helper_is_pure():
    """Same inputs, same answer, and the caller's state is not mutated --
    loop.py passes its live session counters straight in."""
    state = {"open_positions": [{"underlying": "SPY"}], "entries_today": 1,
             "filled_underlyings_today": ["SPY"]}
    snapshot = repr(state)
    assert risk.available_underlyings(state, GOV) == risk.available_underlyings(state, GOV)
    assert repr(state) == snapshot
