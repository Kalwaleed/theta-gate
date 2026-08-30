"""Thin subprocess wrapper over the Alpaca CLI. The only place this codebase
talks to a broker. Every public function shells out to `alpaca` and parses
its JSON (stdout on success, stderr on an API error — see _run) — no
alpaca-py, no direct HTTP.

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


class AlpacaCLIError(RuntimeError):
    """The CLI reported an API error: a non-zero exit, or a body carrying
    an "error" key. .payload is the parsed body and .returncode the exit
    code, so a caller that opted in with allow_error can classify it (a
    404 is a lookup miss, a 422 is a rejection) instead of crashing."""

    def __init__(self, args, returncode, payload):
        super().__init__(f"alpaca {' '.join(args)} failed (rc={returncode}): {json.dumps(payload, default=str)[:500]}")
        self.payload = payload
        self.returncode = returncode


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


def _run(*args, profile=None, allow_error=False):
    """Verified live 30 Aug 2026 (CLI 0.0.13, throwaway paper account):
    success is JSON on stdout, rc 0. An API error is an EMPTY stdout, rc 1,
    and the error JSON on STDERR -- a get-by-client-id miss is {"code":
    40410000, "error": "order not found for <id>", "status": 404, ...}, a
    duplicate client_order_id on submit is {"code": 40010001, "error":
    "client_order_id must be unique", "status": 422, ...}. The old
    stdout-only parse turned every one of those into RuntimeError
    ('returned non-JSON: ') -- the first order lookup of a tick crashed it.
    `order cancel` answers `{}` (or nothing) with rc 0.

    stderr also carries the CLI's hints and version nags, so it is sliced
    from its first "{" before parsing -- a nag ahead of the JSON must not
    turn an API error back into non-JSON.

    allow_error=False (the default): rc != 0, or a body with an "error"
    key, raises AlpacaCLIError so an unhandled API error surfaces as a
    tick_exception rather than a silently wrong value. allow_error=True
    returns the error body to the three callers that classify it
    themselves: get_order_by_client_id, submit_mleg, cancel_order."""
    result = subprocess.run(
        ["alpaca", *args], capture_output=True, text=True, timeout=30,
        env=_profile_env(profile),
    )
    raw = result.stdout.strip()
    if not raw:
        raw = result.stderr[result.stderr.find("{"):].strip() if "{" in result.stderr else ""
    if not raw and result.returncode == 0:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"alpaca {' '.join(args)} returned non-JSON (rc={result.returncode}): {raw[:500]}")
    if result.returncode != 0 or (isinstance(payload, dict) and "error" in payload):
        if allow_error:
            return payload
        raise AlpacaCLIError(args, result.returncode, payload)
    return payload


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


def clock(profile="submission"):
    """Takes `profile` like every other function here. It previously
    asserted the default profile but then ran against whatever
    ALPACA_PROFILE happened to be ambient — the exact split this module's
    _profile_env() exists to prevent, missed because nothing calls this
    yet. Fixed before something does."""
    assert_paper(profile)
    return _run("clock", profile=profile)


def account(profile="submission"):
    assert_paper(profile)
    return _run("account", "get", profile=profile)


def positions(profile="submission"):
    assert_paper(profile)
    return _run("position", "list", profile=profile)


def option_chain(underlying, option_type, expiration_date=None, expiration_date_gte=None,
                  expiration_date_lte=None, strike_gte=None, strike_lte=None, limit=1000,
                  profile="submission"):
    """Verified live 29 Aug 2026: --expiration-date-gte/-lte fetch every
    listed expiry in a range in one call. loop.py uses the range form to
    pull the whole 6-9 DTE window at once — spread.parse_chain now extracts
    each contract's own expiry from its OCC symbol, so candidates across
    multiple expiries can be ranked together (canonical plan Sec 6.2)
    without a separate call per DTE.

    Verified live 30 Aug 2026 (CLI 0.0.13): the old hardcoded --limit 100
    returned 100 snapshots of ONE expiry (100 of SPY's 330 6-9 DTE puts)
    with next_page_token set and ignored — the 0.16-0.25 delta band could
    fall off the page, and an open position's leg outside it made every
    exit skip as exit_quote_unavailable. --limit 1000 returns the whole
    SPY window (330 snapshots, expiries 260908+260909, next_page_token "")
    in one page in ~0.8 s; QQQ 334. Any further page is fetched with
    --page-token and merged, so `snapshots` is always the complete chain
    for the given filters. Returns {"snapshots", "next_page_token": None,
    "pages"}."""
    assert_paper(profile)
    args = [
        "data", "option", "chain",
        "--underlying-symbol", underlying,
        "--type", option_type,
        "--limit", str(limit),
    ]
    if expiration_date is not None:
        args += ["--expiration-date", expiration_date]
    if expiration_date_gte is not None:
        args += ["--expiration-date-gte", expiration_date_gte]
    if expiration_date_lte is not None:
        args += ["--expiration-date-lte", expiration_date_lte]
    if strike_gte is not None:
        args += ["--strike-price-gte", str(strike_gte)]
    if strike_lte is not None:
        args += ["--strike-price-lte", str(strike_lte)]

    merged, token = {}, None
    # ponytail: 20-page cap — a full SPY window is one page at limit 1000
    for pages in range(1, 21):
        page = _run(*args, *(["--page-token", token] if token else []), profile=profile)
        if not isinstance(page, dict) or "snapshots" not in page:
            # an error body must not become an empty chain (= "no candidates" / "leg not found")
            raise RuntimeError(f"alpaca option chain page {pages} has no snapshots: {str(page)[:300]}")
        merged.update(page["snapshots"] or {})
        token = page.get("next_page_token")
        if not token:
            break
    return {"snapshots": merged, "next_page_token": None, "pages": pages}


def stock_bars(symbol, start, timeframe="1Day", limit=25, adjustment="all", profile="submission"):
    """adjustment defaults to 'all' (split + cash-distribution), verified
    live 29 Aug 2026 — canonical plan Sec 5.3: RV20 must be computed on
    adjusted closes, or a stock split reads as a fake huge return."""
    assert_paper(profile)
    return _run(
        "data", "bars",
        "--symbol", symbol,
        "--timeframe", timeframe,
        "--start", start,
        "--limit", str(limit),
        "--adjustment", adjustment,
        profile=profile,
    )


def latest_quote(symbol, profile="submission"):
    """Live bid/ask + timestamp for spot — canonical plan Sec 5.4 wants spot
    no more than 10s older than the newest option leg quote, which a daily
    bar can never satisfy."""
    assert_paper(profile)
    return _run("data", "latest-quote", "--symbol", symbol, profile=profile)


def get_order_by_client_id(client_order_id, profile="submission"):
    """Ambiguity resolves by lookup, never by retry (Alpaca CLI:431-437,
    PT:384). A hit means resubmitting would duplicate; only a confirmed
    miss justifies a new submission.

    Verified live 30 Aug 2026 (CLI 0.0.13): a miss is a 404 body on stderr
    ({"code": 40410000, "error": "order not found for <id>", "status":
    404}) -- the ONLY error this maps to None. Anything else (401, 5xx, a
    rate limit) raises AlpacaCLIError: an unproven miss must never read as
    "safe to submit". A hit keeps coming back after the order is canceled
    (status "canceled", filled_qty "0"), so whether a hit is adoptable is
    the caller's call -- see loop._lookup_or_submit."""
    assert_paper(profile)
    args = ("order", "get-by-client-id", "--client-order-id", client_order_id)
    result = _run(*args, profile=profile, allow_error=True)
    if isinstance(result, dict) and "error" in result:
        if result.get("status") == 404:
            return None
        raise AlpacaCLIError(args, 1, result)  # the CLI exits 1 on every API error (verified 30 Aug 2026)
    return result


def get_order(order_id, profile="submission"):
    assert_paper(profile)
    return _run("order", "get", "--order-id", order_id, profile=profile)


def submit_mleg(legs, limit_price, client_order_id, qty=1, time_in_force="day", dry_run=False, profile="submission"):
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

    A rejection (that 422, or any other API error -- verified 30 Aug 2026
    it arrives on stderr with no "id") is RETURNED, not raised: the caller
    journals the body as submit_failed and ends the attempt.
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
    if dry_run:
        args.append("--dry-run")
    return _run(*args, profile=profile, allow_error=True)


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
    governance.json operational.no_bulk_operations.

    Verified live 30 Aug 2026 (CLI 0.0.13): a cancel answers `{}` rc 0,
    and so does cancelling an already-canceled order (idempotent). A
    cancel racing a fill is answered 422 (not cancelable); that body is
    returned rather than raised because loop._cancel_and_confirm polls the
    order right after to learn what actually happened (filled vs canceled)
    — the poll, not this response, is the source of truth."""
    assert_paper(profile)
    return _run("order", "cancel", "--order-id", order_id, profile=profile, allow_error=True)
