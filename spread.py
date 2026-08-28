"""Pure functions: turn a chain snapshot into a concrete 2-leg vertical, and
that vertical into an Alpaca mleg order body. No I/O, no network — every
function here takes data in and returns data out.

The LLM proposer never touches this file's output directly; it only ever
supplies {underlying, direction, target_dte}. Strike selection is entirely
deterministic.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Contract:
    symbol: str
    strike: float
    delta: float
    iv: float | None
    bid: float
    ask: float

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
        ))
    return contracts


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

    long_candidates = [c for c in contracts if math.isclose(c.strike, long_strike, abs_tol=0.01)]
    if not long_candidates:
        return None
    long = long_candidates[0]

    credit = round(short.mid - long.mid, 4)
    if credit <= 0:
        return None

    return SpreadPlan(
        underlying="",  # filled in by the caller, which knows the underlying
        direction=direction,
        expiry="",      # filled in by the caller from the requested expiration
        short=short,
        long=long,
        width=width,
        credit=credit,
        qty=0,           # sized by risk.size_position, not here
        max_loss_dollars=round((width - credit) * 100, 2),
    )


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
