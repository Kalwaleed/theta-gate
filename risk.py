"""The risk guard. Every function here is pure: no I/O, no network, no
`datetime.now()` — the caller (loop.py) fetches state and injects `now`.
That's what makes this file unit-testable and what makes it the only
component holding a real decision.

`check_all` runs all 21 gates in order (18 state-only, then 3 sized —
see `_STATE_ONLY_GATES` / `_SIZED_GATES` below) and returns the first
failure reason, or None if the proposal is clear to submit. First rejection
wins and is final — no gate is re-evaluated after a veto.
"""

import math
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Environment group
# ---------------------------------------------------------------------------

def gate_paper_env(state: dict, plan, gov: dict, now: datetime) -> str | None:
    if not state.get("paper_verified"):
        return "paper_env: could not prove paper endpoint — treated as live, refused"
    return None


def gate_kill_switch(state: dict, plan, gov: dict, now: datetime) -> str | None:
    if state.get("halt_active"):
        return "kill_switch: HALT file present"
    return None


def gate_account_ready(state: dict, plan, gov: dict, now: datetime) -> str | None:
    allowed_status = set(gov["environment"]["required_account_status"])
    status = state.get("account_status")
    if status not in allowed_status:
        return f"account_status: {status!r} not in {sorted(allowed_status)}"
    if state.get("trading_blocked"):
        return "account_status: trading_blocked is true"
    required_level = gov["environment"]["required_effective_options_level"]
    effective_level = min(
        state.get("options_approved_level", 0),
        state.get("options_configured_max_level", 0),
    )
    if effective_level < required_level:
        return f"options_level: effective {effective_level} < required {required_level}"
    return None


# ---------------------------------------------------------------------------
# Direction routing — not part of check_all()'s pipeline (there is no plan
# yet). Called by loop.py BEFORE any strike selection (spread.rank_candidates),
# but AFTER that tick's chain fetch (market.build_underlying_state) — not
# before it, as an earlier version of this comment claimed. Currently safe
# regardless of call order only because build_underlying_state hardcodes
# option_type="put" unconditionally: a bearish proposal simply gets no
# strikes chosen from the puts already fetched. That stops being true the
# moment call-side support is added — a call fetch driven by direction would
# then need to happen AFTER this function, not before, or a bearish proposal
# could still trigger a real call-chain fetch before being rejected.
# ---------------------------------------------------------------------------

def resolve_direction(proposal_direction: str) -> str | None:
    """Canonical plan Sec 6.1 (HARD_SAFETY), 29 Aug 2026: V1 is put-credit
    only. A bearish proposal is NO_TRADE, never a call-side substitution.
    This is an explicit assertion loop.py must call, not an accident of
    loop.py simply never constructing a bear_call plan — the guard has to
    be real, not just unexercised code."""
    if proposal_direction in ("bullish", "neutral"):
        return "bull_put"
    if proposal_direction == "bearish":
        return None
    raise ValueError(f"unknown proposal direction: {proposal_direction!r}")


# ---------------------------------------------------------------------------
# Regime group — entry-only, sourced from market.py's VIX/calendar snapshot.
# Never blocks exits or liquidates an open position (see exit_signal, which
# does not read any of these fields).
# ---------------------------------------------------------------------------

def gate_vix_zone(state: dict, plan, gov: dict, now: datetime) -> str | None:
    """Canonical plan Sec 4.6, 29 Aug 2026. Boundaries fail conservatively —
    VIX exactly at the ceiling or a flat term structure both reject."""
    vix, vix9d, vix3m = state.get("vix"), state.get("vix9d"), state.get("vix3m")
    if vix is None or vix9d is None or vix3m is None:
        return "vix_zone: missing VIX/VIX9D/VIX3M — cannot confirm regime"
    ceiling = gov["regime"]["vix_max_exclusive"]
    if vix >= ceiling:
        return f"vix_zone: VIX {vix:.2f} at or above ceiling {ceiling:.2f}"
    if gov["regime"]["require_vix9d_lt_vix3m"] and not (vix9d < vix3m):
        return f"vix_zone: term structure not in contango (VIX9D {vix9d:.2f} >= VIX3M {vix3m:.2f})"
    return None


def gate_intraday_shock(state: dict, plan, gov: dict, now: datetime) -> str | None:
    move = state.get("intraday_move_pct")
    if move is None:
        return "intraday_shock: missing intraday move — cannot confirm regime"
    ceiling = gov["regime"]["intraday_move_abs_max_exclusive"]
    if abs(move) >= ceiling:
        return f"intraday_shock: |{move:.1%}| at or above ceiling {ceiling:.1%}"
    return None


def gate_event_blackout(state: dict, plan, gov: dict, now: datetime) -> str | None:
    """Reads the frozen, hand-verified event calendar — loop.py loads
    governance.json's entry.event_calendar_path once and expands each event
    into a concrete [start_ts, end_ts] blackout window (Tier 1: prior
    session close through 30 min after release; Tier 2: +/-30 min) before
    the tick begins. This gate never fetches anything itself, and a missing
    calendar fails closed rather than silently skipping the check."""
    blackouts = state.get("event_blackouts")
    if blackouts is None:
        return "event_blackout: no event calendar loaded — fails closed"
    now_ts = now.timestamp()
    for ev in blackouts:
        if ev["start_ts"] <= now_ts <= ev["end_ts"]:
            return f"event_blackout: inside {ev['name']} blackout window"
    return None


# ---------------------------------------------------------------------------
# Contract group
# ---------------------------------------------------------------------------

def gate_greeks_present(state: dict, plan, gov: dict, now: datetime) -> str | None:
    for leg, name in ((plan.short, "short"), (plan.long, "long")):
        if leg.delta is None or leg.iv is None:
            return f"greeks_present: {name} leg has null delta/iv (0DTE or illiquid contract)"
    return None


def gate_dte_window(state: dict, plan, gov: dict, now: datetime) -> str | None:
    expiry = datetime.strptime(plan.expiry, "%Y-%m-%d").replace(tzinfo=ET)
    dte = (expiry.date() - now.astimezone(ET).date()).days
    dte_min, dte_max = gov["strategy"]["dte_min"], gov["strategy"]["dte_max"]
    if dte <= 0:
        return "dte_window: expiry is today or past (0DTE structurally excluded)"
    if not (dte_min <= dte <= dte_max):
        return f"dte_window: {dte} DTE outside [{dte_min}, {dte_max}]"
    return None


def gate_delta_band(state: dict, plan, gov: dict, now: datetime) -> str | None:
    lo, hi = gov["strategy"]["short_delta_min"], gov["strategy"]["short_delta_max"]
    d = abs(plan.short.delta) if plan.short.delta is not None else None
    if d is None or not (lo <= d <= hi):
        return f"delta_band: short delta {d} outside [{lo}, {hi}]"
    return None


# ---------------------------------------------------------------------------
# Price group
# ---------------------------------------------------------------------------

def gate_credit_quality(state: dict, plan, gov: dict, now: datetime) -> str | None:
    """Verified live 26 Aug 2026: credit/width tracks ~0.8 x |short delta|,
    not a fixed absolute band. A ratio far off that curve is a bad quote,
    not a gift or a rejectable trade."""
    if plan.width <= 0:
        return "credit_quality: zero-width spread"
    ratio = plan.credit / plan.width
    expected = gov["strategy"]["credit_quality_expected_ratio"] * abs(plan.short.delta)
    if expected <= 0:
        return "credit_quality: expected ratio is zero, cannot evaluate"
    deviation = abs(ratio - expected) / expected
    max_dev = gov["strategy"]["credit_quality_max_deviation"]
    if deviation > max_dev:
        return f"credit_quality: ratio {ratio:.3f} deviates {deviation:.0%} from expected {expected:.3f} (max {max_dev:.0%})"
    return None


def gate_minimum_credit(state: dict, plan, gov: dict, now: datetime) -> str | None:
    """Fable 5 strategy review, 28 Aug 2026: an absolute floor, separate from
    the relative credit_quality check above. At the low end of the delta
    band with that check's own tolerance, credit can be too thin to be
    worth the mechanical and execution risk even though it passes the
    relative test."""
    if plan.width <= 0:
        return "minimum_credit: zero-width spread"
    ratio = plan.credit / plan.width
    floor = gov["strategy"]["min_credit_pct_of_width"]
    if ratio < floor:
        return f"minimum_credit: ratio {ratio:.3f} below floor {floor:.3f}"
    return None


def gate_quote_sanity(state: dict, plan, gov: dict, now: datetime) -> str | None:
    max_spread_pct = gov["quote_sanity"]["max_spread_pct_of_mid"]
    max_age = gov["quote_sanity"]["max_quote_age_seconds"]
    for leg, name in ((plan.short, "short"), (plan.long, "long")):
        if leg.bid <= 0 or leg.ask <= leg.bid:
            return f"quote_sanity: {name} leg has invalid bid/ask ({leg.bid}/{leg.ask})"
        spread_pct = (leg.ask - leg.bid) / leg.mid
        if spread_pct > max_spread_pct:
            return f"quote_sanity: {name} leg spread {spread_pct:.0%} exceeds {max_spread_pct:.0%}"
        if leg.quote_ts is None:
            return f"quote_sanity: {name} leg has no quote timestamp"
        age = now.timestamp() - leg.quote_ts
        if age > max_age:
            return f"quote_sanity: {name} leg quote is {age:.0f}s old, exceeds {max_age}s"
    return None


def gate_vrp_present(state: dict, plan, gov: dict, now: datetime) -> str | None:
    """The only edge this strategy claims. Verified live: a fairly priced
    chain has zero arithmetic edge. Sell premium only when it's rich.
    Canonical plan Sec 4.6, 29 Aug 2026: tightened from a plain IV>=RV check
    to a 2.0-vol-point margin — IV barely above RV is noise, not a priced
    premium."""
    if not gov["vrp"]["require_atm_iv_gte_realised_vol"]:
        return None
    atm_iv = state.get("atm_iv")
    realised_vol = state.get("realised_vol")
    if atm_iv is None or realised_vol is None:
        return "vrp_present: missing IV or realised-vol input — cannot confirm premium exists"
    vrp_points = (atm_iv - realised_vol) * 100
    min_points = gov["vrp"]["min_vrp_points"]
    if vrp_points < min_points:
        return f"vrp_present: VRP {vrp_points:.1f} points below floor {min_points:.1f} (IV {atm_iv:.3f}, RV {realised_vol:.3f})"
    return None


# ---------------------------------------------------------------------------
# Exposure group
# ---------------------------------------------------------------------------

def measured_vrp_points(state: dict) -> float | None:
    """ATM implied minus trailing realised vol, in vol points -- the same
    quantity gate_vrp_present thresholds. Exposed rather than recomputed so
    the gate and the sizer can never disagree about what the premium is."""
    atm_iv, realised_vol = state.get("atm_iv"), state.get("realised_vol")
    if atm_iv is None or realised_vol is None:
        return None
    return (atm_iv - realised_vol) * 100


def _scale(value: float, floor_v: float, ceil_v: float, lo: int, hi: int) -> int:
    """Linear interpolation from a signal onto a contract count, clamped at
    both ends. Shared by both sizing signals so they cannot drift apart."""
    if hi <= lo or ceil_v <= floor_v:
        return lo
    t = min(1.0, max(0.0, (value - floor_v) / (ceil_v - floor_v)))
    return min(hi, lo + int(t * (hi - lo + 1)))


def size_position(plan, gov: dict, confidence: float | None = None,
                  vrp_points: float | None = None) -> int:
    """How many contracts, from a deterministic function of governance and
    a market signal.

    THE LLM DOES NOT SIZE THE POSITION. The bounds, the scale and the
    ceiling all live in governance.json, which no LLM can write to, and
    gate_max_loss_per_trade / gate_total_open_risk / gate_buying_power_floor
    all still run afterwards and veto independently.

    Signal, by governance.strategy.sizing_signal:

      "vrp"         MEASURED variance risk premium in vol points, scaled
                    from min_vrp_points (the entry floor) to
                    vrp_points_for_max_size. This is the edge the strategy
                    actually claims; it is measured from the chain and the
                    bars, and it varies with the market.

      "confidence"  The model's self-reported conviction. Kept as a
                    fallback and for comparison, but see
                    docs/STRATEGY-REVIEW-2026-09-01 Sec 5: across every
                    live proposal on 31 Aug the model answered 0.60, 0.60,
                    0.60, 0.62. A constant carries no signal, so sizing on
                    it was sizing on nothing.

    Missing signal falls back to min_contracts -- never to max. A sizer
    that maxes out on absent data is the wrong failure direction.

    Returns 0 -- never fractional, never negative -- if even the minimum
    would breach the per-trade cap.
    """
    per_contract_loss = (plan.width - plan.credit) * 100
    if per_contract_loss <= 0:
        return 0

    s = gov["strategy"]
    signal = s.get("sizing_signal", s.get("sizing_mode"))
    lo = s.get("min_contracts", s.get("fixed_quantity", 1))
    hi = s.get("max_contracts", lo)

    if signal == "vrp" and vrp_points is not None:
        qty = _scale(vrp_points, gov["vrp"]["min_vrp_points"],
                     gov["vrp"]["vrp_points_for_max_size"], lo, hi)
    elif signal == "confidence" and confidence is not None:
        qty = _scale(float(confidence), s["confidence_floor"], s["confidence_ceiling"], lo, hi)
    else:
        qty = lo

    if qty < 1:
        return 0
    # Shrink to fit rather than refusing: a plan too big for the per-trade
    # cap is still a valid smaller plan, and returning 0 would silently
    # forfeit a trade the guard allows.
    while qty > 1 and per_contract_loss * qty > gov["risk"]["max_loss_per_trade_dollars"]:
        qty -= 1
    if per_contract_loss * qty > gov["risk"]["max_loss_per_trade_dollars"]:
        return 0
    return qty


def gate_max_loss_per_trade(state: dict, plan, gov: dict, now: datetime, qty: int) -> str | None:
    if qty < 1:
        return "max_loss_per_trade: spread too wide for minimum 1-contract size within cap"
    max_loss = (plan.width - plan.credit) * 100 * qty
    cap = gov["risk"]["max_loss_per_trade_dollars"]
    if max_loss > cap:
        return f"max_loss_per_trade: ${max_loss:.0f} exceeds cap ${cap}"
    return None


def gate_total_open_risk(state: dict, plan, gov: dict, now: datetime, qty: int) -> str | None:
    existing = sum(p.get("max_loss_dollars", 0) for p in state.get("open_positions", []))
    new_risk = (plan.width - plan.credit) * 100 * qty
    cap = gov["risk"]["max_total_open_risk_dollars"]
    if existing + new_risk > cap:
        return f"total_open_risk: ${existing + new_risk:.0f} would exceed cap ${cap}"
    return None


def gate_concurrent(state: dict, plan, gov: dict, now: datetime) -> str | None:
    open_positions = state.get("open_positions", [])
    if len(open_positions) >= gov["risk"]["max_concurrent_positions"]:
        return f"concurrent: {len(open_positions)} open positions at cap"
    same_underlying = [p for p in open_positions if p.get("underlying") == plan.underlying]
    if len(same_underlying) >= gov["risk"]["max_positions_per_underlying"]:
        return f"concurrent: already at max positions for {plan.underlying}"
    if state.get("entries_today", 0) >= gov["entry"]["max_new_entries_per_session"]:
        return "concurrent: max new entries for this session reached"
    return None


def gate_daily_fill_cap_per_underlying(state: dict, plan, gov: dict, now: datetime) -> str | None:
    """A filled entry earlier today blocks a same-underlying re-entry later
    today, even if that earlier spread has already closed — canonical plan
    Sec 4.5, 29 Aug 2026. Distinct from gate_concurrent above, which only
    sees currently-open positions and live orders, not today's completed
    round trips."""
    filled_today = state.get("filled_underlyings_today", [])
    cap = gov["risk"]["max_filled_entries_per_underlying_per_session"]
    count = filled_today.count(plan.underlying)
    if count >= cap:
        return f"daily_fill_cap: {plan.underlying} already has {count} filled entr{'y' if count == 1 else 'ies'} today"
    return None


def gate_buying_power_floor(state: dict, plan, gov: dict, now: datetime, qty: int) -> str | None:
    """Verified live 26 Aug 2026: margin held is width x 100 x qty, NOT max
    loss. These are different numbers — check against the correct one."""
    margin_required = plan.width * 100 * qty
    bp = state.get("options_buying_power", 0)
    bp_after = bp - margin_required
    floor = gov["risk"]["options_buying_power_floor_dollars"]
    if bp_after < floor:
        return f"buying_power_floor: ${bp_after:.0f} after trade below floor ${floor}"
    max_loss = (plan.width - plan.credit) * 100 * qty
    multiple = gov["risk"]["options_buying_power_floor_multiple_of_max_loss"]
    if bp < multiple * max_loss:
        return f"buying_power_floor: ${bp:.0f} below {multiple}x max loss (${max_loss:.0f})"
    return None


# ---------------------------------------------------------------------------
# Drawdown & deadline group
# ---------------------------------------------------------------------------

def gate_daily_drawdown(state: dict, plan, gov: dict, now: datetime) -> str | None:
    start = state.get("session_start_equity")
    equity = state.get("equity")
    if not start:
        return None
    pct = (equity - start) / start
    halt_pct = gov["risk"]["daily_drawdown_halt_pct"]
    if pct <= halt_pct:
        return f"daily_drawdown: {pct:.1%} at or below halt threshold {halt_pct:.1%}"
    return None


def gate_cumulative_drawdown(state: dict, plan, gov: dict, now: datetime) -> str | None:
    equity = state.get("equity", gov["risk"]["starting_equity_dollars"])
    floor = gov["risk"]["cumulative_drawdown_halt_equity_dollars"]
    if equity <= floor:
        return f"cumulative_drawdown: equity ${equity:.0f} at or below halt floor ${floor}"
    if state.get("consecutive_exceptions", 0) >= gov["operational"]["max_loop_exceptions_before_halt"]:
        return "cumulative_drawdown: too many consecutive loop exceptions"
    return None


def gate_deadline(state: dict, plan, gov: dict, now: datetime) -> str | None:
    now_et = now.astimezone(ET)
    cutoff_date = datetime.strptime(gov["entry"]["no_entries_after_date"], "%Y-%m-%d").date()
    cutoff_time = dtime.fromisoformat(gov["entry"]["no_entries_after_time_et"])
    if now_et.date() > cutoff_date or (now_et.date() == cutoff_date and now_et.time() >= cutoff_time):
        return f"deadline: past {cutoff_date} {cutoff_time} ET — no new entries"
    return None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

# Order matters: cheapest / most-decisive checks first. Sizing gates need
# `qty`, computed once via size_position() before the exposure group runs.
_STATE_ONLY_GATES = [
    gate_paper_env,
    gate_kill_switch,
    gate_account_ready,
    gate_vix_zone,
    gate_intraday_shock,
    gate_event_blackout,
    gate_greeks_present,
    gate_dte_window,
    gate_delta_band,
    gate_credit_quality,
    gate_minimum_credit,
    gate_quote_sanity,
    gate_vrp_present,
    gate_concurrent,
    gate_daily_fill_cap_per_underlying,
    gate_daily_drawdown,
    gate_cumulative_drawdown,
    gate_deadline,
]

_SIZED_GATES = [
    gate_max_loss_per_trade,
    gate_total_open_risk,
    gate_buying_power_floor,
]


def check_all(state: dict, plan, gov: dict, now: datetime,
              confidence: float | None = None) -> tuple[str | None, int]:
    """Returns (veto_reason_or_None, qty). qty is 0 if vetoed before sizing
    was relevant, or if sizing itself failed.

    `confidence` is the proposer's stated conviction, passed to
    size_position. It can only ever move qty inside the governance-defined
    band -- the three sized gates below run afterwards on the result and
    veto independently, so a confident model still cannot exceed the
    per-trade cap, the open-risk cap, or the buying-power floor.
    Defaults to None, which reproduces fixed-quantity behaviour exactly.
    """
    for gate in _STATE_ONLY_GATES:
        reason = gate(state, plan, gov, now)
        if reason:
            return reason, 0

    qty = size_position(plan, gov, confidence, measured_vrp_points(state))
    for gate in _SIZED_GATES:
        reason = gate(state, plan, gov, now, qty)
        if reason:
            return reason, 0

    return None, qty


def exit_signal(position: dict, state: dict, gov: dict, now: datetime) -> str | None:
    """position: {"credit": float, "cost_to_close": float, "dte": int}.
    Returns the exit reason, or None to hold. Deterministic, no LLM."""
    now_et = now.astimezone(ET)
    force_date = datetime.strptime(gov["exit"]["force_close_start_date"], "%Y-%m-%d").date()
    force_time = dtime.fromisoformat(gov["exit"]["force_close_start_time_et"])
    if now_et.date() > force_date or (now_et.date() == force_date and now_et.time() >= force_time):
        return "force_close: past the flatten deadline"

    credit = position["credit"]
    cost_to_close = position["cost_to_close"]

    take_profit_at = credit * (1 - gov["exit"]["take_profit_pct_of_credit"])
    if cost_to_close <= take_profit_at:
        return "take_profit"

    stop_at = credit * gov["exit"]["stop_close_debit_multiple"]
    if cost_to_close >= stop_at:
        return "stop_loss"

    if position.get("dte", 99) <= gov["exit"]["time_exit_dte"]:
        return "time_exit"

    return None


def force_close_action(now: datetime, gov: dict) -> str:
    """Which rung of the flatten ladder applies right now. Only meaningful
    once exit_signal has already returned 'force_close'."""
    now_et = now.astimezone(ET)
    ladder = gov["exit"]["force_close_ladder"]
    action = ladder[0]["action"]
    for rung in ladder:
        rung_time = dtime.fromisoformat(rung["at_et"])
        if now_et.time() >= rung_time:
            action = rung["action"]
    return action


def detect_orphan_equity(positions: list[dict]) -> list[str]:
    """An equity position among the account's holdings means an option
    leg was assigned overnight, converting a defined-risk spread into
    naked stock. Flag it for immediate close via an explicit order —
    never close_position, never close_all."""
    return [p["symbol"] for p in positions if p.get("asset_class") == "us_equity"]
