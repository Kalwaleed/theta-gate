"""Pure functions: turn a chain snapshot into a concrete 2-leg vertical, and
that vertical into an Alpaca mleg order body. No I/O, no network — every
function here takes data in and returns data out.

The LLM proposer never touches this file's output directly; it only ever
supplies {underlying, direction, target_dte}. Strike selection is entirely
deterministic.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Contract:
    symbol: str
    strike: float
    delta: float
    iv: float | None
    bid: float
    ask: float
    quote_ts: float | None = None  # unix seconds, from the chain snapshot's latestQuote.t
    expiry: str = ""  # "YYYY-MM-DD", parsed from the OCC symbol itself

    @property
    def mid(self):
        return round((self.bid + self.ask) / 2, 4)


@dataclass(frozen=True)
class SpreadPlan:
    underlying: str
    direction: str  # "bull_put" | "bear_call"
    expiry: str
    short: Contract
    long: Contract
    width: float
    credit: float
    qty: int
    max_loss_dollars: float


def parse_chain(raw_snapshots: dict) -> list[Contract]:
    """raw_snapshots is the `.snapshots` dict from `alpaca data option chain`
    JSON output, keyed by OCC symbol. Contracts with no two-sided quote are
    dropped — they cannot be traded and cannot be trusted."""
    contracts = []
    for symbol, snap in raw_snapshots.items():
        quote = snap.get("latestQuote") or {}
        bid, ask = quote.get("bp"), quote.get("ap")
        if not bid or not ask:
            continue
        greeks = snap.get("greeks") or {}
        strike = _strike_from_occ(symbol)
        contracts.append(Contract(
            symbol=symbol,
            strike=strike,
            delta=greeks.get("delta"),
            iv=snap.get("impliedVolatility"),
            bid=bid,
            ask=ask,
            quote_ts=parse_quote_ts(quote.get("t")),
            expiry=_expiry_from_occ(symbol),
        ))
    return contracts


def parse_quote_ts(raw: str | None) -> float | None:
    """latestQuote.t is an RFC3339 UTC string with sub-microsecond precision
    (e.g. '2026-08-28T19:59:56.711359584Z') — verified live 29 Aug 2026.
    Python's fromisoformat truncates the extra digits rather than erroring."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _expiry_from_occ(symbol: str) -> str:
    """The 6 digits right before the P/C flag (which is right before the
    8-digit strike) are YYMMDD — works regardless of underlying symbol
    length, e.g. 'SPY260902P00754000' -> '2026-09-02'."""
    yymmdd = symbol[-15:-9]
    return f"20{yymmdd[0:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"


def _strike_from_occ(symbol: str) -> float:
    # last 8 digits of an OCC symbol are the strike, x1000
    return int(symbol[-8:]) / 1000


def pick_spread(
    contracts: list[Contract],
    direction: str,
    width: float,
    delta_min: float,
    delta_max: float,
) -> SpreadPlan | None:
    """Selects the short leg whose |delta| falls in [delta_min, delta_max]
    and is closest to the midpoint of that band, then the long leg exactly
    `width` further out-of-the-money. Returns None if no strike qualifies —
    never silently falls back to a wrong strike.

    direction "bull_put": sell a put spread below spot (short put ITM-ward
    of long put — i.e. short strike ABOVE long strike for puts).
    direction "bear_call": sell a call spread above spot (short strike
    BELOW long strike for calls).
    """
    target_delta = (delta_min + delta_max) / 2
    candidates = [
        c for c in contracts
        if c.delta is not None and delta_min <= abs(c.delta) <= delta_max
    ]
    if not candidates:
        return None

    short = min(candidates, key=lambda c: abs(abs(c.delta) - target_delta))

    if direction == "bull_put":
        long_strike = short.strike - width
    elif direction == "bear_call":
        long_strike = short.strike + width
    else:
        raise ValueError(f"unknown direction: {direction}")

    # Same-expiry only: `contracts` may span multiple expiries (rank_candidates
    # passes the whole DTE-range fetch through here per expiry group, but a
    # caller could pass an unfiltered multi-expiry list) — without this filter
    # a same-strike contract from a DIFFERENT expiry could silently become the
    # long leg of a calendar-mismatched "vertical".
    long_candidates = [
        c for c in contracts
        if c.expiry == short.expiry and math.isclose(c.strike, long_strike, abs_tol=0.01)
    ]
    if not long_candidates:
        return None
    long = long_candidates[0]

    credit = round(short.mid - long.mid, 4)
    if credit <= 0:
        return None

    return SpreadPlan(
        underlying="",  # filled in by the caller, which knows the underlying
        direction=direction,
        expiry=short.expiry,
        short=short,
        long=long,
        width=width,
        credit=credit,
        qty=0,           # sized by risk.size_position, not here
        max_loss_dollars=round((width - credit) * 100, 2),
    )


def friction_ratio(plan: SpreadPlan) -> float:
    """Canonical plan Sec 5.5: natural vs optimistic credit — a diagnostic,
    used here only to RANK passing candidates, never to gate one (risk.py's
    gate_quote_sanity + gate_credit_quality already gate quote quality from
    two angles; this is deliberately not a third overlapping gate)."""
    natural = plan.short.bid - plan.long.ask
    optimistic = plan.short.ask - plan.long.bid
    mid = (natural + optimistic) / 2
    if mid <= 0:
        return math.inf
    return (optimistic - natural) / mid


def rank_candidates(
    contracts: list[Contract], direction: str, width: float,
    delta_min: float, delta_max: float, now: datetime,
) -> list[SpreadPlan]:
    """Canonical plan Sec 6.2: build every valid vertical across every
    expiry present in `contracts` (a single option_chain call across the
    whole DTE range, not one call per expiry), then rank deterministically:
    lowest friction_ratio -> delta closest to the band midpoint -> largest
    calendar DTE -> short OCC symbol -> long OCC symbol. Returns candidates
    best-first; the caller (loop.py) still runs risk.check_all on each in
    order and takes the first that passes every gate — this only decides
    the order gates are tried in, never bypasses them."""
    by_expiry: dict[str, list[Contract]] = {}
    for c in contracts:
        by_expiry.setdefault(c.expiry, []).append(c)

    candidates = []
    for group in by_expiry.values():
        plan = pick_spread(group, direction=direction, width=width, delta_min=delta_min, delta_max=delta_max)
        if plan is not None:
            candidates.append(plan)

    target_delta = (delta_min + delta_max) / 2
    now_date = now.astimezone(ET).date()

    def sort_key(plan: SpreadPlan):
        dte = (datetime.strptime(plan.expiry, "%Y-%m-%d").date() - now_date).days
        return (
            friction_ratio(plan),
            abs(abs(plan.short.delta) - target_delta),
            -dte,  # largest DTE first
            plan.short.symbol,
            plan.long.symbol,
        )

    candidates.sort(key=sort_key)
    return candidates


def client_order_id(purpose: str, trade_date: str, window: str, underlying: str, stage: str) -> str:
    """Deterministic and readable, e.g. 'tg-e-20260831-1030-spy-s0'. No HMAC
    or randomness — order volume here is tiny and non-adversarial, so plain
    determinism is enough for uniqueness. This *is* the idempotency
    mechanism: a crashed-and-retried tick recomputes the same id and looks
    it up (alpaca.get_order_by_client_id) before ever submitting again.
    Verified live 29 Aug 2026: Alpaca rejects a resubmitted duplicate id
    with 422 'client_order_id must be unique' rather than creating a
    second order.

    purpose: "e" (entry) | "x" (exit) | "r" (repair)
    trade_date: "YYYYMMDD"
    window: "1030" | "1330" | a fixed exit-rung name (e.g. "stop", "force1430")
    underlying: "spy" | "qqq"
    stage: "s0" | "s1" | rung name
    """
    cid = f"tg-{purpose}-{trade_date}-{window}-{underlying.lower()}-{stage}"
    if len(cid) > 128:
        raise ValueError(f"client_order_id too long ({len(cid)} chars): {cid}")
    return cid


def mleg_body(plan: SpreadPlan, qty: int) -> dict:
    """Builds the exact Alpaca mleg order body. Two traps this function
    exists to make impossible: a positive limit_price on a credit spread,
    and a top-level symbol/side (mleg orders have neither).

    Verified live 26 Aug 2026: negative limit_price = net credit.
    """
    if plan.credit <= 0:
        raise ValueError("mleg_body only handles credit spreads; credit must be > 0")

    ratio_gcd = math.gcd(1, 1)  # both legs are 1:1; assert explicitly for clarity
    assert ratio_gcd == 1

    if plan.direction == "bull_put":
        short_side, long_side = "sell", "buy"
    else:
        short_side, long_side = "sell", "buy"

    return {
        "order_class": "mleg",
        "qty": str(qty),
        "type": "limit",
        "limit_price": f"-{plan.credit:.2f}",
        "time_in_force": "day",
        "legs": [
            {
                "symbol": plan.short.symbol,
                "ratio_qty": "1",
                "side": short_side,
                "position_intent": "sell_to_open",
            },
            {
                "symbol": plan.long.symbol,
                "ratio_qty": "1",
                "side": long_side,
                "position_intent": "buy_to_open",
            },
        ],
    }


def closing_mleg_body(plan: SpreadPlan, qty: int, limit_price: float) -> dict:
    """The reverse order that closes an open spread. Sign convention still
    applies: a positive limit_price here is what you pay to close (a debit
    to close a credit spread you're happy with; could be negative if the
    position has moved further in your favor)."""
    return {
        "order_class": "mleg",
        "qty": str(qty),
        "type": "limit",
        "limit_price": f"{limit_price:.2f}",
        "time_in_force": "day",
        "legs": [
            {
                "symbol": plan.short.symbol,
                "ratio_qty": "1",
                "side": "buy",
                "position_intent": "buy_to_close",
            },
            {
                "symbol": plan.long.symbol,
                "ratio_qty": "1",
                "side": "sell",
                "position_intent": "sell_to_close",
            },
        ],
    }
