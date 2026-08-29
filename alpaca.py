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

PAPER_TRUE_VALUES = {"true", "1", "yes"}
REQUIRED_ENDPOINT = "https://paper-api.alpaca.markets"


class NotPaperError(RuntimeError):
    """Raised whenever paper mode cannot be proven. Fails closed."""


def _profile_env(profile):
    """Verified live 29 Aug 2026: `alpaca doctor --profile X` silently
    ignores the --profile flag and always reports on whichever profile is
    currently `alpaca profile use`-active, while `alpaca account get
    --profile X` correctly honors it (confirmed by comparing returned
    account IDs) — and ALPACA_PROFILE=X works correctly for both. Rather
    than trust the flag for some commands and not others, every subprocess
    in this module gets the profile through the one mechanism verified to
    work everywhere, so whatever assert_paper checks is guaranteed to be
    what actually acts."""
    return {**os.environ, "ALPACA_PROFILE": profile} if profile else dict(os.environ)


def _run(*args, profile=None):
    result = subprocess.run(
        ["alpaca", *args], capture_output=True, text=True, timeout=30,
        env=_profile_env(profile),
    )
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

    Verifies three things, in order: (1) the endpoint doctor reports is
    paper-api, (2) doctor's active profile is actually the one this call
    claims to check — closes a real gap where the old --profile-flag check
    always reported on whatever profile happened to be CLI-active, (3) for
    the submission profile specifically, the live account id matches
    ALPACA_ACCOUNT_ID — so a config mistake that points 'submission' at the
    wrong paper account fails closed instead of silently trading it.
    """
    live_signal = os.environ.get("ALPACA_LIVE_TRADE", "")
    if live_signal.strip().lower() in PAPER_TRUE_VALUES:
        raise NotPaperError(f"ALPACA_LIVE_TRADE={live_signal!r} indicates live trading")

    try:
        doctor = subprocess.run(
            ["alpaca", "doctor"],
            capture_output=True, text=True, timeout=15,
            env=_profile_env(profile),
        )
        output = doctor.stdout + doctor.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise NotPaperError(f"could not run alpaca doctor: {exc}") from exc

    if REQUIRED_ENDPOINT not in output:
        raise NotPaperError(
            f"alpaca doctor did not report {REQUIRED_ENDPOINT} for profile {profile!r} — inconclusive, treated as live"
        )
    if f"active profile: {profile}" not in output:
        raise NotPaperError(
            f"alpaca doctor did not confirm active profile {profile!r} — inconclusive, treated as live. Output: {output[:300]!r}"
        )

    if profile == "submission":
        expected_id = os.environ.get("ALPACA_ACCOUNT_ID", "").strip()
        if not expected_id:
            raise NotPaperError("ALPACA_ACCOUNT_ID is not set — refusing to trade the submission profile blind")
        acct = _run("account", "get", profile=profile)
        actual_id = acct.get("id") if isinstance(acct, dict) else None
        if actual_id != expected_id:
            raise NotPaperError(
                f"account id mismatch for profile 'submission': expected {expected_id!r}, got {actual_id!r}"
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


def submit_mleg(legs, limit_price, client_order_id, qty=1, time_in_force="day", profile="submission"):
    """Submit a multi-leg options order. `limit_price` sign is the caller's
    responsibility — negative for a net credit, positive for a net debit.

    `legs`: list of dicts with symbol, ratio_qty, side, position_intent.
    Exactly 2 legs for this codebase (verticals only); the mleg format
    itself supports up to 4.

    client_order_id is REQUIRED, not generated here (see spread.client_order_id) —
    that's the entire idempotency mechanism: the caller computes the same
    deterministic id on every retry and looks it up (get_order_by_client_id)
    before ever calling this. A random fallback here would silently defeat
    that — verified live 29 Aug 2026 that Alpaca rejects a resubmitted
    duplicate id with 422 'client_order_id must be unique' rather than
    creating a second order, so the id must be the SAME id on retry, never
    a fresh one.
    """
    assert_paper(profile)
    if len(legs) != 2:
        raise ValueError(f"expected exactly 2 legs, got {len(legs)}")

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


def list_orders(status="open", profile="submission"):
    """Live open/working orders — distinct from get_order_by_client_id's
    single lookup. Needed because gate_concurrent only ever saw *filled*
    positions: a crash after an order is accepted but before the journal
    records it, retried in a later window (a different deterministic
    client_order_id, since the id includes the window), was invisible to
    both the id lookup and that gate — risking two live orders on one
    underlying. loop.py folds this into the same tick-start state as filled
    positions. --nested rolls mleg legs under their parent order."""
    assert_paper(profile)
    return _run("order", "list", "--status", status, "--nested", profile=profile)


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
