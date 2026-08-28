"""All tests, one file, inline fixtures. The chain data below is not
synthetic — it's the real SPY 7-DTE (2026-09-02 expiry) put chain captured
live on 26 Aug 2026, the same chain that produced the real fill proving the
mleg body shape. See docs in the plan for the probe.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import risk
import spread

ET = ZoneInfo("America/New_York")

GOV = {
    "strategy": {
        "underlyings": ["SPY", "QQQ"], "structure": "vertical", "legs": 2,
        "width_dollars": 5, "dte_min": 4, "dte_max": 9,
        "short_delta_min": 0.16, "short_delta_max": 0.25,
        "credit_quality_expected_ratio": 0.8, "credit_quality_max_deviation": 0.40,
    },
    "entry": {
        "windows_et": ["10:30", "13:30"], "max_new_entries_per_session": 2,
        "no_entries_after_date": "2026-09-02", "no_entries_after_time_et": "16:00",
    },
    "exit": {
        "take_profit_pct_of_credit": 0.50, "stop_loss_multiple_of_credit": 2.0,
        "time_exit_dte": 2, "force_close_start_date": "2026-09-03",
        "force_close_start_time_et": "15:00",
        "force_close_ladder": [
            {"at_et": "15:00", "action": "limit_at_mid"},
            {"at_et": "15:30", "action": "cross_the_spread"},
            {"at_et": "15:50", "action": "market_mleg"},
        ],
    },
    "risk": {
        "max_loss_per_trade_dollars": 1000, "max_total_open_risk_dollars": 3000,
        "max_concurrent_positions": 3, "max_positions_per_underlying": 1,
        "options_buying_power_floor_dollars": 25000,
        "options_buying_power_floor_multiple_of_max_loss": 5,
        "daily_drawdown_halt_pct": -0.02,
        "cumulative_drawdown_halt_equity_dollars": 96000,
        "starting_equity_dollars": 100000,
    },
    "quote_sanity": {"min_bid_dollars": 0.01, "max_spread_pct_of_mid": 0.15, "max_quote_age_seconds": 600},
    "vrp": {"realised_vol_lookback_days": 20, "require_atm_iv_gte_realised_vol": True},
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

# Real SPY put chain, 2026-09-02 expiry, captured live 26 Aug 2026 (5 trading
# days before expiry at capture time; used here with `now` = 28 Aug, still
# inside the 4-9 DTE window).
REAL_CHAIN_SNAPSHOTS = {
    "SPY260902P00749000": {"latestQuote": {"bp": 0.98, "ap": 1.01}, "greeks": {"delta": -0.1279}, "impliedVolatility": 0.145},
    "SPY260902P00752000": {"latestQuote": {"bp": 1.29, "ap": 1.33}, "greeks": {"delta": -0.1658}, "impliedVolatility": 0.144},
    "SPY260902P00753000": {"latestQuote": {"bp": 1.42, "ap": 1.46}, "greeks": {"delta": -0.1806}, "impliedVolatility": 0.144},
    "SPY260902P00754000": {"latestQuote": {"bp": 1.57, "ap": 1.61}, "greeks": {"delta": -0.1969}, "impliedVolatility": 0.144},
    "SPY260902P00755000": {"latestQuote": {"bp": 1.73, "ap": 1.76}, "greeks": {"delta": -0.2140}, "impliedVolatility": 0.143},
    "SPY260902P00756000": {"latestQuote": {"bp": 1.90, "ap": 1.95}, "greeks": {"delta": -0.2329}, "impliedVolatility": 0.143},
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


NOW = datetime(2026, 8, 28, 11, 0, tzinfo=ET)


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


# ---------------------------------------------------------------------------
# risk.py — sizing
# ---------------------------------------------------------------------------

def test_sizing_from_max_loss_not_premium():
    """width 5, credit ~0.60 -> per-contract max loss ~$440 -> qty 2 within
    the $1000 cap. A hand-built qty of 3 must be rejected by the gate."""
    plan = real_plan()
    qty = risk.size_position(plan, GOV)
    assert qty == 2

    state = base_state()
    reason = risk.gate_max_loss_per_trade(state, plan, GOV, NOW, qty=3)
    assert reason is not None
    assert "max_loss_per_trade" in reason


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


def test_check_all_passes_the_real_trade_end_to_end():
    plan = real_plan()
    reason, qty = risk.check_all(base_state(), plan, GOV, NOW)
    assert reason is None
    assert qty == 2


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
    state = base_state()
    position = {"credit": 1.00, "cost_to_close": 0.80, "dte": 5}

    before = datetime(2026, 9, 3, 14, 0, tzinfo=ET)
    assert risk.exit_signal(position, state, GOV, before) is None

    after = datetime(2026, 9, 3, 15, 10, tzinfo=ET)
    assert risk.exit_signal(position, state, GOV, after).startswith("force_close")
    assert risk.force_close_action(after, GOV) == "limit_at_mid"

    later = datetime(2026, 9, 3, 15, 45, tzinfo=ET)
    assert risk.force_close_action(later, GOV) == "cross_the_spread"

    latest = datetime(2026, 9, 3, 16, 0, tzinfo=ET)
    assert risk.force_close_action(latest, GOV) == "market_mleg"


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
