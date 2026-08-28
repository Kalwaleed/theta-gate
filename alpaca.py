"""Thin subprocess wrapper over the Alpaca CLI. The only place this codebase
talks to a broker. Every public function shells out to `alpaca` and parses
its JSON stdout — no alpaca-py, no direct HTTP.

Paper is asserted at import and re-checked before every order submission,
per Alpaca's own paper-trading skill: "verify the environment before every
order submission, not just once per session."
"""

import json
import os
import subprocess
import time
import uuid

PAPER_TRUE_VALUES = {"true", "1", "yes"}
REQUIRED_ENDPOINT = "https://paper-api.alpaca.markets"


class NotPaperError(RuntimeError):
    """Raised whenever paper mode cannot be proven. Fails closed."""


def _run(*args, profile=None):
    cmd = ["alpaca", *args, "--profile", profile] if profile else ["alpaca", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        # the CLI prints JSON to stdout on both success and error
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"alpaca {' '.join(args)} returned non-JSON: {result.stdout[:500]}")


def assert_paper(profile="submission"):
    """The one function every other function in this module calls first.

    Three-state result collapsed to two: PASS or raise. An unreadable or
    unparseable check is INCONCLUSIVE, and inconclusive fails closed —
    "treat unproven as live" (Alpaca's own MCP paper-trading skill, MCP:259).
    """
    live_signal = os.environ.get("ALPACA_LIVE_TRADE", "")
    if live_signal.strip().lower() in PAPER_TRUE_VALUES:
        raise NotPaperError(f"ALPACA_LIVE_TRADE={live_signal!r} indicates live trading")

    try:
        doctor = subprocess.run(
            ["alpaca", "doctor", "--profile", profile],
            capture_output=True, text=True, timeout=15,
        )
        output = doctor.stdout + doctor.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise NotPaperError(f"could not run alpaca doctor: {exc}") from exc

    if REQUIRED_ENDPOINT not in output:
        raise NotPaperError(
            f"alpaca doctor did not report {REQUIRED_ENDPOINT} — inconclusive, treated as live"
        )


def clock():
    assert_paper()
    return _run("clock")


def account(profile="submission"):
    assert_paper(profile)
    return _run("account", "get", profile=profile)


def positions(profile="submission"):
    assert_paper(profile)
    return _run("position", "list", profile=profile)


def option_chain(underlying, expiration_date, option_type, strike_gte=None, strike_lte=None, profile="submission"):
    assert_paper(profile)
    args = [
        "data", "option", "chain",
        "--underlying-symbol", underlying,
        "--expiration-date", expiration_date,
        "--type", option_type,
        "--limit", "100",
    ]
    if strike_gte is not None:
        args += ["--strike-price-gte", str(strike_gte)]
    if strike_lte is not None:
        args += ["--strike-price-lte", str(strike_lte)]
    return _run(*args, profile=profile)


def stock_bars(symbol, start, timeframe="1Day", limit=25, profile="submission"):
    assert_paper(profile)
    return _run(
        "data", "bars",
        "--symbol", symbol,
        "--timeframe", timeframe,
        "--start", start,
        "--limit", str(limit),
        profile=profile,
    )


def get_order_by_client_id(client_order_id, profile="submission"):
    """Ambiguity resolves by lookup, never by retry (Alpaca CLI:431-437,
    PT:384). A hit means resubmitting would duplicate; only a confirmed
    miss justifies a new submission."""
    assert_paper(profile)
    result = _run("order", "get-by-client-id", "--client-order-id", client_order_id, profile=profile)
    if isinstance(result, dict) and result.get("code") == 0 and "error" in result:
        return None
    return result


def get_order(order_id, profile="submission"):
    assert_paper(profile)
    return _run("order", "get", "--order-id", order_id, profile=profile)


def submit_mleg(legs, limit_price, qty=1, time_in_force="day", client_order_id=None, profile="submission"):
    """Submit a multi-leg options order. `limit_price` sign is the caller's
    responsibility — negative for a net credit, positive for a net debit.

    `legs`: list of dicts with symbol, ratio_qty, side, position_intent.
    Exactly 2 legs for this codebase (verticals only); the mleg format
    itself supports up to 4.

    client_order_id is generated and written to the journal by the caller
    *before* this function runs, so a crash mid-submit stays recoverable —
    the id exists on disk even if this HTTP call never returns.
    """
    assert_paper(profile)
    if len(legs) != 2:
        raise ValueError(f"expected exactly 2 legs, got {len(legs)}")
    if client_order_id is None:
        client_order_id = f"tg-{uuid.uuid4()}"

    args = [
        "order", "submit",
        "--order-class", "mleg",
        "--qty", str(qty),
        "--type", "limit",
        "--limit-price", str(limit_price),
        "--time-in-force", time_in_force,
        "--client-order-id", client_order_id,
        "--legs", json.dumps(legs),
    ]
    return _run(*args, profile=profile)


def poll_until_filled(order_id, max_attempts=60, profile="submission"):
    """Bounded poll — 'no order should be polled more than 60 times total'
    (Alpaca PT:586-589). Returns the final order state whatever it is;
    caller decides what a non-filled terminal state means."""
    for _ in range(max_attempts):
        order = get_order(order_id, profile=profile)
        status = order.get("status")
        if status in ("filled", "canceled", "expired", "rejected", "done_for_day"):
            return order
        time.sleep(2)
    return get_order(order_id, profile=profile)


def cancel_order(order_id, profile="submission"):
    """Cancels ONE order by id. Never call `order cancel-all` — see
    governance.json operational.no_bulk_operations."""
    assert_paper(profile)
    return _run("order", "cancel", "--order-id", order_id, profile=profile)
