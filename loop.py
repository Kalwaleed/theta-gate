"""loop.py -- the one-tick orchestrator. The only place in this repo that
decides to place or close a real (paper) order.

Priority order every tick, each step protecting the one before it:
  1. resolve `now`
  2. prove paper (alpaca.assert_paper) -- any failure is CRITICAL: journal
     and STOP, no further action at all, not even reconciliation
  3. check the local HALT flag
  4. reconcile: fresh positions, open orders, account -- never trusted from
     a prior tick's memory
  5. detect an assigned equity leg -- CRITICAL, blocks entries this tick
     regardless of HALT; also detect any broker option position the
     journal has no record of (a likely lost entry_filled from a prior
     tick's failed git push) -- CRITICAL, triggers HALT
  6. evaluate every open Theta Gate position for an exit (deterministic,
     runs even under HALT or an orphan-equity block); a naked single leg
     found anywhere in this step (after a cancel, a reported fill, or a
     reconciliation gap) also triggers HALT
  7. HALT blocks entries here, after exits/reconciliation have already run
  8. is `now` inside an eligible entry window?
  9. today's entry counts, from the journal, cross-checked against the
     broker's own closed orders
  10. the entry attempt: brain.propose -> risk gates -> the two-stage price
      ladder
  11. journal tick_completed, then git add/commit/push the journal
      (publication only, never load-bearing for trading logic)

Durability without a database: Alpaca is authoritative for what is actually
open (positions/orders, refetched every tick). A deterministic
client_order_id (spread.client_order_id) is always looked up
(alpaca.get_order_by_client_id) before ever submitting -- the whole
idempotency story. The journal (data/journal.jsonl) is append-only and
written incrementally: the intent to submit an order is durable on disk
BEFORE the network call that might submit it, so a crash mid-tick is
recoverable by re-running the same tick logic, recomputing the identical
id, and finding it either present (adopt) or genuinely absent (safe to
proceed).
"""

import argparse
import dataclasses
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import alpaca
import brain
import market
import risk
import spread

ET = ZoneInfo("America/New_York")

GOVERNANCE_PATH = "governance.json"
JOURNAL_PATH = "data/journal.jsonl"
HALT_PATH = "data/HALT.json"
LOCK_PATH = "data/.loop.lock"

# --- hardcoded fallbacks for governance fields that don't exist yet ------
# Every one of these is named explicitly in the build report as a
# candidate for promotion into governance.json.
ENTRY_FIRST_LIMIT_WAIT_SECONDS = 30    # no entry.first_limit_wait_seconds in governance.json yet
ENTRY_LADDER_TOTAL_BUDGET_SECONDS = 60  # canonical Sec 7.3's 60s total budget across both entry stages
ENTRY_CONCESSION_DOLLARS = 0.05         # canonical Sec 7.3's one permitted concession
ENTRY_CONCESSION_FLOOR_DOLLARS = 0.50   # canonical Sec 7.3's credit floor -- never chase below this
EXIT_CONCESSION_DOLLARS = 0.05          # mirrors the entry ladder's concession size; not governance-specified
ENTRY_WINDOW_MINUTES = 15               # canonical Sec 4.3; governance.json's windows_et lists only start times
LOCK_STALE_SECONDS = 600                # a same-machine lock older than this is presumed abandoned


# ---------------------------------------------------------------------------
# Journal -- append-only JSONL. Every record: {"ts", "event", ...fields}.
# entry_filled / exit_filled carry enough to replay open positions,
# entries_today, filled_underlyings_today, and consecutive_exceptions from
# this file alone on the next tick.
# ---------------------------------------------------------------------------

def _append_journal(event, **fields):
    """Incremental by construction: opens, writes one line, closes -- never
    batched in memory across a tick. `default=str` is a last-resort net so
    an unexpected type can never crash the single most safety-critical
    write in this file."""
    record = {"ts": datetime.now(ET).isoformat(), "event": event, **fields}
    Path("data").mkdir(exist_ok=True)
    with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
    return record


def _read_journal():
    path = Path(JOURNAL_PATH)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a torn line from a mid-write crash -- skip, don't crash reconciliation
    return events


def _position_id(trade_date, window, underlying):
    return f"tg-e-{trade_date}-{window}-{underlying.lower()}"


def _open_positions(events):
    """Every entry_filled not yet matched by an exit_filled for the same
    position_id -- scans full history, not just today, since a position can
    stay open across multiple days."""
    entries = {}
    for e in events:
        if e.get("event") == "entry_filled" and e.get("position_id"):
            entries[e["position_id"]] = e
    closed_ids = {e.get("position_id") for e in events if e.get("event") == "exit_filled"}
    return [rec for pid, rec in entries.items() if pid not in closed_ids]


def _entries_today(events, now):
    today = now.astimezone(ET).date()
    fills = []
    for e in events:
        if e.get("event") != "entry_filled":
            continue
        try:
            ts = datetime.fromisoformat(e["ts"]).astimezone(ET)
        except (KeyError, ValueError):
            continue
        if ts.date() == today:
            fills.append(e)
    return len(fills), [e.get("underlying") for e in fills]


def _consecutive_exceptions(events):
    """Counts the trailing run of ok=false tick_completed events, scanning
    backward, stopping at the first ok=true (or start of file)."""
    count = 0
    for e in reversed(events):
        if e.get("event") != "tick_completed":
            continue
        if e.get("ok", True):
            break
        count += 1
    return count


def _exit_attempt_number(events, position_id):
    """1 on a position's first exit attempt; increments only after a
    durably-journaled exit_unfilled give-up -- this is what keeps a
    retried exit's client_order_id fresh across give-up cycles instead of
    perpetually re-adopting the same canceled order.

    Counted per position_id ONLY, not per reason/rung: exit_signal
    recomputes the reason fresh from live prices every tick, and it can
    legitimately flip (stop_loss this tick, time_exit the next, as price
    oscillates near a threshold). Keying on (position_id, rung) -- as an
    earlier version of this function did -- meant a reason-flip reset the
    attempt count AND changed the client_order_id's window slot, silently
    orphaning any order still outstanding under the previous reason's id:
    a crash-recovery retry would compute a different id and never look the
    old one up again. Keying on position_id alone survives a reason-flip
    because the id no longer depends on the reason at all (see
    _attempt_exit, which now uses entry_rec["window"] for that slot)."""
    return sum(1 for e in events if e.get("event") == "exit_unfilled" and e.get("position_id") == position_id) + 1


# ---------------------------------------------------------------------------
# HALT flag -- no documented shape existed anywhere in the repo (checked
# STRATEGY.md/PLAN.md's prose descriptions and grepped for HALT.example.json);
# this is the first thing to define data/HALT.json's actual JSON shape.
# ---------------------------------------------------------------------------

def _check_halt():
    path = Path(HALT_PATH)
    if not path.exists():
        default = {"active": False, "reason": "", "activated_at": None}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(default, indent=2) + "\n", encoding="utf-8")
        return False, default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A corrupt safety-flag file is ambiguous, and ambiguous must never
        # silently mean "not halted".
        return True, {"active": True, "reason": "HALT.json unreadable -- failing closed", "activated_at": None}
    return bool(data.get("active")), data


def _trigger_halt(reason):
    """Idempotent: the first reason wins. If HALT is already active, a
    second, unrelated problem discovered later in the same or a later tick
    must not overwrite the original reason/timestamp a human needs to see
    what happened first. Always writes for real, even under --dry-run --
    HALT records a fact about live broker state (a naked leg, an untracked
    position), not a trading action; dry_run only gates broker WRITES."""
    if _check_halt()[0]:
        return
    Path(HALT_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(HALT_PATH).write_text(
        json.dumps({"active": True, "reason": reason, "activated_at": datetime.now(ET).isoformat()}, indent=2) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Trivial same-machine lock -- guards only against two loop.py processes
# started by accident on the same box in the same window. The GitHub
# Actions concurrency group (built separately, infra layer) is the real
# overlap guard; this is a cheap belt-and-suspenders extra, nothing more.
# ponytail: PID+age check, not a real lease -- fine at this scale.
# ---------------------------------------------------------------------------

def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _acquire_lock():
    path = Path(LOCK_PATH)
    if path.exists():
        blocked = False
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
            started = datetime.fromisoformat(info["started_at"])
            age = (datetime.now(ET) - started).total_seconds()
            blocked = _pid_alive(info.get("pid")) and age <= LOCK_STALE_SECONDS
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            blocked = False
        if blocked:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": os.getpid(), "started_at": datetime.now(ET).isoformat()}), encoding="utf-8")
    return True


def _release_lock():
    try:
        Path(LOCK_PATH).unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Account state mapping -- Alpaca's raw account fields to Theta Gate's
# internal gate-input keys (see test_agent.py's base_state()).
# ---------------------------------------------------------------------------

def _map_account_state(account):
    """Field names below (status, trading_blocked, options_approved_level,
    options_trading_level, equity, last_equity, options_buying_power) are
    Alpaca's standard documented Account object fields -- NOT verified live
    this session (no real account fetch was made, per this build's own
    no-network-call constraint). Flagged in the build report: spot-check
    against one real `alpaca account get` response before Monday.
    `last_equity` is mapped to session_start_equity (previous session's
    closing equity == today's starting equity, assuming no session-crossing
    surprises)."""
    return {
        "account_status": account.get("status"),
        "trading_blocked": bool(account.get("trading_blocked", False)),
        "options_approved_level": account.get("options_approved_level"),
        "options_configured_max_level": account.get("options_trading_level"),
        "equity": float(account.get("equity") or 0),
        "session_start_equity": float(account.get("last_equity") or account.get("equity") or 0),
        "options_buying_power": float(account.get("options_buying_power") or 0),
    }


# ---------------------------------------------------------------------------
# Order primitives -- the idempotent submit, bounded wait, cancel-confirm.
# Every order this file ever places goes through _lookup_or_submit.
# ---------------------------------------------------------------------------

def _lookup_or_submit(client_order_id, legs, limit_price, qty, profile, dry_run):
    """ALWAYS look up by client_order_id before ever submitting. A hit is
    adopted, never resubmitted. Verified live 29 Aug 2026: Alpaca rejects a
    resubmitted duplicate id with HTTP 422, never a second order."""
    existing = alpaca.get_order_by_client_id(client_order_id, profile=profile)
    if existing is not None:
        return existing, "adopted"
    response = alpaca.submit_mleg(
        legs, limit_price=limit_price, client_order_id=client_order_id,
        qty=qty, dry_run=dry_run, profile=profile,
    )
    # dry_run's echo has no "id"/"status" -- that absence is the only signal
    # distinguishing an echo from a real submitted order (verified 29 Aug 2026).
    action = "submitted" if response.get("id") else "dry_run"
    return response, action


def _wait_for_terminal(order, wait_seconds, profile, gov):
    order_id = order.get("id")
    if not order_id:
        return order
    cap = gov["operational"]["order_poll_max_attempts"]
    attempts = min(max(1, wait_seconds // 2), cap)
    return alpaca.poll_until_filled(order_id, max_attempts=attempts, profile=profile)


def _cancel_and_confirm(order_id, profile, gov, dry_run=False):
    """dry_run skips the real cancel entirely -- a cancel is a broker WRITE,
    same as submit_mleg, and an order this function might be asked to
    cancel can be a REAL order this tick merely *adopted* (found already
    live via client_order_id lookup, e.g. left over from an earlier
    non-dry-run tick). Without this gate, a --dry-run run could silently
    cancel a real order. Still returns the order's current state either
    way, since callers must notice if it filled anyway (a cancel never
    wins a race against a fill in flight)."""
    if dry_run:
        return alpaca.get_order(order_id, profile=profile)
    alpaca.cancel_order(order_id, profile=profile)
    cap = gov["operational"]["order_poll_max_attempts"]
    return alpaca.poll_until_filled(order_id, max_attempts=min(5, cap), profile=profile)


def _confirm_flat(symbols, profile):
    positions = alpaca.positions(profile=profile)
    open_symbols = {p.get("symbol") for p in positions}
    return not (set(symbols) & open_symbols)


def _check_leg_symmetry(short_symbol, long_symbol, profile, position_id, context):
    """A vertical's two legs must always be BOTH open or BOTH closed.
    Exactly one open alone is a naked, unhedged option position -- far
    worse than a missed trade, and the one broker state this codebase must
    never just log and move past. HALTs (blocks new entries; open
    positions still get managed) and journals CRITICAL rather than trying
    an automated single-leg close: alpaca.py has no single-leg order
    primitive, and building one untested, days before the deadline, is
    itself a real-money-shaped risk. A human closes it manually from the
    CRITICAL journal entry. Returns True if symmetric (nothing to do)."""
    positions = alpaca.positions(profile=profile)
    open_symbols = {p.get("symbol") for p in positions} & {short_symbol, long_symbol}
    if open_symbols in (set(), {short_symbol, long_symbol}):
        return True
    _trigger_halt(f"naked leg after {context}: {position_id} has only {sorted(open_symbols)} open")
    _append_journal("naked_leg_detected", level="critical", position_id=position_id, context=context,
                     open_symbols=sorted(open_symbols),
                     note="one leg of a vertical is open alone -- HALT set, needs human close")
    return False


def _extract_actual_price(order, fallback):
    """Prefers the order's actual filled_avg_price; falls back to the
    limit price we submitted at if absent. Sign convention mirrors
    limit_price's own documented convention -- NOT verified live against a
    real filled mleg order's response shape this session. Flagged in the
    build report."""
    raw = order.get("filled_avg_price")
    if raw is None:
        return fallback
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


# ---------------------------------------------------------------------------
# Fresh quotes for an already-open position (for cost_to_close).
# ---------------------------------------------------------------------------

def _fresh_close_quotes(underlying, expiry, short_symbol, long_symbol, profile):
    """HARD_SAFETY (risk.resolve_direction): V1 is put-only, so every open
    Theta Gate position is a bull_put vertical -- option_type is always
    'put' here."""
    chain = alpaca.option_chain(underlying, option_type="put", expiration_date=expiry, profile=profile)
    contracts = {c.symbol: c for c in spread.parse_chain(chain.get("snapshots", {}))}
    short_c, long_c = contracts.get(short_symbol), contracts.get(long_symbol)
    if short_c is None or long_c is None:
        raise market.MarketDataError(f"{underlying}: could not fetch fresh quotes for {short_symbol}/{long_symbol}")
    return short_c, long_c


def _current_entry_window(now, gov):
    now_et = now.astimezone(ET)
    for w in gov["entry"]["windows_et"]:
        start = dtime.fromisoformat(w)
        start_dt = datetime.combine(now_et.date(), start, tzinfo=ET)
        end_dt = start_dt + timedelta(minutes=ENTRY_WINDOW_MINUTES)
        if start_dt <= now_et < end_dt:
            return w.replace(":", "")
    return None


def _current_force_rung(now, gov):
    """Mirrors risk.force_close_action's own ladder walk to also recover
    the rung's at_et (needed for the client-order-id tag) -- the ACTION
    value itself always comes from risk.force_close_action, never
    recomputed; the assert is a cheap internal consistency check."""
    now_et = now.astimezone(ET)
    ladder = gov["exit"]["force_close_ladder"]
    current = ladder[0]
    for rung in ladder:
        if now_et.time() >= dtime.fromisoformat(rung["at_et"]):
            current = rung
    assert current["action"] == risk.force_close_action(now, gov)
    return current


# ---------------------------------------------------------------------------
# Exit handling (step 6)
# ---------------------------------------------------------------------------

def _journal_exit_fill(order, position_id, underlying, reason, qty, submitted_price,
                        short_symbol, long_symbol, profile):
    actual_debit = _extract_actual_price(order, submitted_price)
    still_open = not _confirm_flat([short_symbol, long_symbol], profile)
    _append_journal(
        "exit_filled", position_id=position_id, underlying=underlying, reason=reason, qty=qty,
        close_debit=actual_debit, order_id=order.get("id"), client_order_id=order.get("client_order_id"),
        legs_confirmed_closed=not still_open,
    )
    if still_open:
        _append_journal(
            "exit_fill_leg_mismatch", level="warning", position_id=position_id,
            note="order reports filled but a leg still shows open in the broker -- needs human check",
        )
        _check_leg_symmetry(short_symbol, long_symbol, profile, position_id, context="exit_fill_mismatch")


def _attempt_exit(entry_rec, reason, short_c, long_c, gov, now, profile, dry_run, journal_events):
    """Deliberately simpler than canonical's per-exit-type ladder (Sec
    8.2): one shared shape for stop_loss/take_profit/time_exit -- a limit
    at the fresh mid, one concession after the urgent-exit wait, then give
    up for the next tick to retry. Only Thursday's force-close gets the
    full governance-driven ladder (see _attempt_force_close)."""
    position_id = entry_rec["position_id"]
    underlying = entry_rec["underlying"]
    qty = entry_rec["_close_qty"]
    trade_date = entry_rec["trade_date"]

    plan = spread.SpreadPlan(
        underlying=underlying, direction=entry_rec["direction"], expiry=entry_rec["expiry"],
        short=short_c, long=long_c, width=entry_rec["width"], credit=entry_rec["credit"],
        qty=qty, max_loss_dollars=0,
    )
    mid_debit = round(short_c.mid - long_c.mid, 2)
    natural_debit = round(short_c.ask - long_c.bid, 2)

    rung = {"stop_loss": "stop", "take_profit": "tp", "time_exit": "time"}[reason]
    attempt_n = _exit_attempt_number(journal_events, position_id)
    stage0 = "s0" if attempt_n == 1 else f"s0r{attempt_n}"
    stage1 = "s1" if attempt_n == 1 else f"s1r{attempt_n}"
    # governance.operational.unfilled_order_cancel_after_seconds is the only
    # existing field named for "how long to wait before canceling an
    # unfilled order" -- mapped here to the spec's "urgent-exit wait" since
    # no exit-specific field exists yet. Flagged in the build report.
    wait_seconds = gov["operational"]["unfilled_order_cancel_after_seconds"]

    # window (not rung) is the id's stable slot: entry_rec["window"] is the
    # same value baked into this position's own position_id, so it can
    # never change tick to tick the way the recomputed reason/rung can.
    window = entry_rec["window"]

    cid0 = spread.client_order_id("x", trade_date, window, underlying, stage0)
    body0 = spread.closing_mleg_body(plan, qty, mid_debit)
    _append_journal("exit_intent", position_id=position_id, client_order_id=cid0, reason=reason,
                     rung=rung, stage=stage0, limit_price=mid_debit, qty=qty)
    order, action = _lookup_or_submit(cid0, body0["legs"], body0["limit_price"], qty, profile, dry_run)
    _append_journal(f"exit_{action}", position_id=position_id, client_order_id=cid0, order_id=order.get("id"))
    if action == "dry_run":
        return {"filled": False, "dry_run": True}

    order = _wait_for_terminal(order, wait_seconds, profile, gov)
    if order.get("status") == "filled":
        _journal_exit_fill(order, position_id, underlying, reason, qty, mid_debit,
                            short_c.symbol, long_c.symbol, profile)
        return {"filled": True, "order_id": order.get("id")}

    if order.get("id"):
        # A cancel never wins a race against a fill already in flight --
        # must check what actually happened, not assume the cancel worked.
        order = _cancel_and_confirm(order["id"], profile, gov, dry_run)
        if order.get("status") == "filled":
            _journal_exit_fill(order, position_id, underlying, reason, qty, mid_debit,
                                short_c.symbol, long_c.symbol, profile)
            return {"filled": True, "order_id": order.get("id"), "raced_cancel": True}
        _check_leg_symmetry(short_c.symbol, long_c.symbol, profile, position_id, context=f"exit_cancel:{reason}:s0")

    stage1_price = max(mid_debit, min(round(mid_debit + EXIT_CONCESSION_DOLLARS, 2), natural_debit))
    cid1 = spread.client_order_id("x", trade_date, window, underlying, stage1)
    body1 = spread.closing_mleg_body(plan, qty, stage1_price)
    _append_journal("exit_intent", position_id=position_id, client_order_id=cid1, reason=reason,
                     rung=rung, stage=stage1, limit_price=stage1_price, qty=qty)
    order, action = _lookup_or_submit(cid1, body1["legs"], body1["limit_price"], qty, profile, dry_run)
    _append_journal(f"exit_{action}", position_id=position_id, client_order_id=cid1, order_id=order.get("id"))
    if action == "dry_run":
        return {"filled": False, "dry_run": True}

    order = _wait_for_terminal(order, wait_seconds, profile, gov)
    if order.get("status") == "filled":
        _journal_exit_fill(order, position_id, underlying, reason, qty, stage1_price,
                            short_c.symbol, long_c.symbol, profile)
        return {"filled": True, "order_id": order.get("id")}

    if order.get("id"):
        order = _cancel_and_confirm(order["id"], profile, gov, dry_run)
        if order.get("status") == "filled":
            _journal_exit_fill(order, position_id, underlying, reason, qty, stage1_price,
                                short_c.symbol, long_c.symbol, profile)
            return {"filled": True, "order_id": order.get("id"), "raced_cancel": True}
        _check_leg_symmetry(short_c.symbol, long_c.symbol, profile, position_id, context=f"exit_cancel:{reason}:s1")
    _append_journal("exit_unfilled", position_id=position_id, client_order_id=cid1, reason=reason, rung=rung)
    return {"filled": False}


def _attempt_force_close(entry_rec, short_c, long_c, gov, now, profile, dry_run, open_orders):
    """The full governance-driven ladder (governance.json fully specifies
    it). No in-tick wait: the ladder is time-spaced across ticks (30 min
    per rung, per governance.exit.force_close_ladder), so each tick just
    submits/adopts whatever the CURRENT rung is; a stale earlier-rung order
    still open gets canceled first."""
    position_id = entry_rec["position_id"]
    underlying = entry_rec["underlying"]
    qty = entry_rec["_close_qty"]
    trade_date = entry_rec["trade_date"]

    current_rung = _current_force_rung(now, gov)
    action = current_rung["action"]
    rung_tag = "force" + current_rung["at_et"].replace(":", "")

    if action == "reconcile_and_alert":
        _append_journal("force_close_unresolved", level="critical", position_id=position_id,
                         underlying=underlying, note="past the final flatten rung, position still open")
        return {"filled": False, "rung": rung_tag}

    plan = spread.SpreadPlan(
        underlying=underlying, direction=entry_rec["direction"], expiry=entry_rec["expiry"],
        short=short_c, long=long_c, width=entry_rec["width"], credit=entry_rec["credit"],
        qty=qty, max_loss_dollars=0,
    )
    mid_debit = round(short_c.mid - long_c.mid, 2)
    natural_debit = max(mid_debit, round(short_c.ask - long_c.bid, 2))
    price = {
        "limit_at_mid": mid_debit,
        "cross_the_spread": natural_debit,
        # spread.closing_mleg_body only builds LIMIT orders (spread.py is
        # off-limits to edit this session) and no live canary this session
        # proved a true market-mleg order type -- canonical Sec 8.2's own
        # fallback for exactly this situation is "the most marketable
        # validated limit bounded by spread width", which is what this is.
        "market_mleg": min(round(natural_debit + 0.05, 2), entry_rec["width"] - 0.01),
    }[action]

    stale_prefix = f"tg-x-{trade_date}-force"
    this_rung_prefix = f"tg-x-{trade_date}-{rung_tag}-{underlying.lower()}-"
    for o in open_orders:
        coid = str(o.get("client_order_id") or "")
        if coid.startswith(stale_prefix) and f"-{underlying.lower()}-" in coid and not coid.startswith(this_rung_prefix):
            if o.get("id"):
                canceled = _cancel_and_confirm(o["id"], profile, gov, dry_run)
                if canceled.get("status") == "filled":
                    # a stale earlier-rung order raced the cancel and filled --
                    # the position is very likely already closed. Report it,
                    # don't also submit a fresh order for this rung on top.
                    _journal_exit_fill(canceled, position_id, underlying, "force_close", qty, mid_debit,
                                        short_c.symbol, long_c.symbol, profile)
                    return {"filled": True, "rung": rung_tag, "order_id": o.get("id"), "raced_stale_fill": True}
                _append_journal("force_close_stale_canceled", position_id=position_id, client_order_id=coid,
                                 dry_run=dry_run)

    cid = spread.client_order_id("x", trade_date, rung_tag, underlying, "s0")
    body = spread.closing_mleg_body(plan, qty, price)
    _append_journal("exit_intent", position_id=position_id, client_order_id=cid, reason="force_close",
                     rung=rung_tag, action=action, stage="s0", limit_price=price, qty=qty)
    order, act = _lookup_or_submit(cid, body["legs"], body["limit_price"], qty, profile, dry_run)
    _append_journal(f"exit_{act}", position_id=position_id, client_order_id=cid, order_id=order.get("id"))
    if act == "dry_run":
        return {"filled": False, "dry_run": True, "rung": rung_tag}

    if order.get("status") == "filled":
        _journal_exit_fill(order, position_id, underlying, "force_close", qty, price,
                            short_c.symbol, long_c.symbol, profile)
        return {"filled": True, "rung": rung_tag, "order_id": order.get("id")}
    return {"filled": False, "rung": rung_tag, "order_id": order.get("id")}


def _evaluate_and_exit_position(entry_rec, option_positions, gov, now, profile, dry_run, open_orders, journal_events):
    position_id = entry_rec["position_id"]
    short_sym, long_sym = entry_rec["short_symbol"], entry_rec["long_symbol"]
    short_pos, long_pos = option_positions.get(short_sym), option_positions.get(long_sym)
    if short_pos is None and long_pos is None:
        # Both legs already gone at the broker even though the journal
        # thinks this position is open: most likely a lost exit_filled
        # event (e.g. a git-publish failure on an earlier tick/runner).
        # Nothing dangerous is open -- just a stale journal -- so this
        # does not warrant a HALT, only a loud note for a human to fold
        # this position out of the journal's view.
        _append_journal("exit_position_already_flat", position_id=position_id,
                         note="journal shows this position open but the broker shows both legs already "
                              "closed -- journal is stale, not a live risk")
        return None
    if short_pos is None or long_pos is None:
        # Exactly one leg missing: the other is a naked, unhedged option
        # position the exit-management loop was about to silently skip
        # (the qty_to_close/quote-fetch logic below assumes both legs
        # exist). HALT before this position falls out of view.
        _trigger_halt(f"naked leg: {position_id} is missing exactly one broker leg")
        _append_journal("exit_reconciliation_gap", level="critical", position_id=position_id,
                         note="journal shows this position open but the broker is missing exactly one "
                              "leg -- naked exposure. HALT set; needs human close.")
        return None

    qty_to_close = min(abs(int(float(short_pos.get("qty", 0) or 0))), abs(int(float(long_pos.get("qty", 0) or 0))))
    if qty_to_close < 1:
        return None

    try:
        short_c, long_c = _fresh_close_quotes(entry_rec["underlying"], entry_rec["expiry"], short_sym, long_sym, profile)
    except market.MarketDataError as exc:
        _append_journal("exit_quote_unavailable", position_id=position_id, error=str(exc))
        return None

    cost_to_close = round(short_c.mid - long_c.mid, 2)
    dte = (datetime.strptime(entry_rec["expiry"], "%Y-%m-%d").date() - now.astimezone(ET).date()).days
    reason = risk.exit_signal({"credit": entry_rec["credit"], "cost_to_close": cost_to_close, "dte": dte}, {}, gov, now)
    _append_journal("exit_evaluated", position_id=position_id, underlying=entry_rec["underlying"],
                     credit=entry_rec["credit"], cost_to_close=cost_to_close, dte=dte, signal=reason or "hold")
    if reason is None:
        return {"position_id": position_id, "signal": "hold"}

    entry_rec = {**entry_rec, "_close_qty": qty_to_close}
    if reason.startswith("force_close"):
        result = _attempt_force_close(entry_rec, short_c, long_c, gov, now, profile, dry_run, open_orders)
    else:
        result = _attempt_exit(entry_rec, reason, short_c, long_c, gov, now, profile, dry_run, journal_events)
    return {"position_id": position_id, "signal": reason, **result}


# ---------------------------------------------------------------------------
# Entry handling (steps 8-10)
# ---------------------------------------------------------------------------

def _journal_entry_fill(order, candidate, qty, window_label, trade_date, underlying, stage,
                         latency_seconds, submitted_credit):
    actual_credit = -_extract_actual_price(order, -submitted_credit)
    max_loss_dollars = round((candidate.width - actual_credit) * 100 * qty, 2)
    _append_journal(
        "entry_filled", position_id=_position_id(trade_date, window_label, underlying),
        underlying=underlying, direction=candidate.direction, trade_date=trade_date, window=window_label,
        expiry=candidate.expiry, short_symbol=candidate.short.symbol, long_symbol=candidate.long.symbol,
        width=candidate.width, qty=qty, credit=actual_credit, max_loss_dollars=max_loss_dollars,
        order_id=order.get("id"), client_order_id=order.get("client_order_id"), stage=stage,
        latency_seconds=latency_seconds,
    )


def _attempt_entry(candidate, qty, window_label, trade_date, now, gov, profile, dry_run):
    underlying = candidate.underlying
    position_id = _position_id(trade_date, window_label, underlying)
    started = time.monotonic()

    body0 = spread.mleg_body(candidate, qty)
    cid0 = spread.client_order_id("e", trade_date, window_label, underlying, "s0")
    # The intent is durable on disk BEFORE any lookup/submit network call --
    # a crash here is recoverable by re-running this tick, recomputing the
    # identical id, and finding it either present (adopt) or absent (safe).
    _append_journal("entry_intent", position_id=position_id, client_order_id=cid0, stage="s0",
                     underlying=underlying, window=window_label, trade_date=trade_date,
                     expiry=candidate.expiry, short_symbol=candidate.short.symbol,
                     long_symbol=candidate.long.symbol, width=candidate.width, qty=qty,
                     limit_price=body0["limit_price"])
    order, action = _lookup_or_submit(cid0, body0["legs"], body0["limit_price"], qty, profile, dry_run)
    _append_journal(f"entry_{action}", position_id=position_id, client_order_id=cid0, order_id=order.get("id"))
    if action == "dry_run":
        return {"filled": False, "dry_run": True, "stage": "s0"}

    order = _wait_for_terminal(order, ENTRY_FIRST_LIMIT_WAIT_SECONDS, profile, gov)
    if order.get("status") == "filled":
        _journal_entry_fill(order, candidate, qty, window_label, trade_date, underlying, "s0",
                             time.monotonic() - started, candidate.credit)
        return {"filled": True, "stage": "s0", "order_id": order.get("id")}

    if order.get("id"):
        # A cancel never wins a race against a fill already in flight --
        # must check what actually happened, not assume the cancel worked.
        order = _cancel_and_confirm(order["id"], profile, gov, dry_run)
        if order.get("status") == "filled":
            _journal_entry_fill(order, candidate, qty, window_label, trade_date, underlying, "s0",
                                 time.monotonic() - started, candidate.credit)
            return {"filled": True, "stage": "s0", "order_id": order.get("id"), "raced_cancel": True}
    if not _check_leg_symmetry(candidate.short.symbol, candidate.long.symbol, profile, position_id,
                                context="entry_cancel:s0"):
        _append_journal("entry_unfilled", level="critical", position_id=position_id, client_order_id=cid0,
                         reason="unexpected_exposure_after_cancel")
        return {"filled": False, "stage": "s0"}

    # Stage s1: one concession only, never more. Never below the $0.50 floor.
    s1_price = round(max(candidate.credit - ENTRY_CONCESSION_DOLLARS, ENTRY_CONCESSION_FLOOR_DOLLARS), 2)
    limit_price1 = f"-{s1_price:.2f}"
    cid1 = spread.client_order_id("e", trade_date, window_label, underlying, "s1")
    _append_journal("entry_intent", position_id=position_id, client_order_id=cid1, stage="s1",
                     underlying=underlying, window=window_label, trade_date=trade_date,
                     expiry=candidate.expiry, short_symbol=candidate.short.symbol,
                     long_symbol=candidate.long.symbol, width=candidate.width, qty=qty,
                     limit_price=limit_price1)
    order, action = _lookup_or_submit(cid1, body0["legs"], limit_price1, qty, profile, dry_run)
    _append_journal(f"entry_{action}", position_id=position_id, client_order_id=cid1, order_id=order.get("id"))
    if action == "dry_run":
        return {"filled": False, "dry_run": True, "stage": "s1"}

    remaining = max(ENTRY_LADDER_TOTAL_BUDGET_SECONDS - ENTRY_FIRST_LIMIT_WAIT_SECONDS, 1)
    order = _wait_for_terminal(order, remaining, profile, gov)
    if order.get("status") == "filled":
        _journal_entry_fill(order, candidate, qty, window_label, trade_date, underlying, "s1",
                             time.monotonic() - started, s1_price)
        return {"filled": True, "stage": "s1", "order_id": order.get("id")}

    if order.get("id"):
        order = _cancel_and_confirm(order["id"], profile, gov, dry_run)
        if order.get("status") == "filled":
            _journal_entry_fill(order, candidate, qty, window_label, trade_date, underlying, "s1",
                                 time.monotonic() - started, s1_price)
            return {"filled": True, "stage": "s1", "order_id": order.get("id"), "raced_cancel": True}
        _check_leg_symmetry(candidate.short.symbol, candidate.long.symbol, profile, position_id,
                             context="entry_cancel:s1")
    _append_journal("entry_unfilled", position_id=position_id, client_order_id=cid1)
    return {"filled": False, "stage": "s1"}


def _attempt_entry_pipeline(window_label, now, gov, profile, dry_run, account_state,
                             open_positions_journal, entries_today, filled_underlyings_today,
                             consecutive_exceptions, halt_active):
    trade_date = now.astimezone(ET).strftime("%Y%m%d")

    try:
        regime = market.build_regime_state(now, gov["entry"]["event_calendar_path"], gov["regime"]["vix_source_url_template"])
    except market.MarketDataError as exc:
        _append_journal("no_trade", reason="regime_data_unavailable", detail=str(exc))
        return {"attempted": True, "filled": False, "reason": "regime_data_unavailable"}

    underlying_states = {}
    for u in gov["strategy"]["underlyings"]:
        try:
            underlying_states[u] = market.build_underlying_state(
                u, now, gov["strategy"]["dte_min"], gov["strategy"]["dte_max"], profile=profile,
            )
        except market.MarketDataError as exc:
            _append_journal("no_trade", reason="underlying_data_unavailable", underlying=u, detail=str(exc))
            return {"attempted": True, "filled": False, "reason": "underlying_data_unavailable"}

    # brain.propose sees only scalar market numbers, never the raw chain.
    brain_context = {u: {k: v for k, v in s.items() if k != "contracts"} for u, s in underlying_states.items()}
    brain_context.update({"vix": regime["vix"], "vix9d": regime["vix9d"], "vix3m": regime["vix3m"]})

    propose_result = brain.propose(brain_context, now)
    _append_journal(
        "proposal", schema_version=propose_result.schema_version, model=propose_result.model,
        latency_seconds=propose_result.latency_seconds, raw_response=propose_result.raw_response,
        proposal=(dataclasses.asdict(propose_result.proposal) if propose_result.proposal else None),
    )

    if propose_result.proposal is None:
        _append_journal("no_trade", reason="model_failure_or_malformed")
        return {"attempted": True, "filled": False, "reason": "model_failure_or_malformed"}
    proposal = propose_result.proposal

    direction = risk.resolve_direction(proposal.direction)
    if direction is None:
        # HARD_SAFETY (canonical Sec 6.1): bearish is NO_TRADE, never a call-side substitution.
        _append_journal("no_trade", reason="bearish_no_call_side", underlying=proposal.underlying)
        return {"attempted": True, "filled": False, "reason": "bearish_no_call_side"}

    if proposal.underlying not in gov["strategy"]["underlyings"]:
        _append_journal("no_trade", reason="unsupported_underlying", underlying=proposal.underlying)
        return {"attempted": True, "filled": False, "reason": "unsupported_underlying"}

    underlying = proposal.underlying
    u_state = underlying_states[underlying]

    candidates = spread.rank_candidates(
        u_state["contracts"], direction, gov["strategy"]["width_dollars"],
        gov["strategy"]["short_delta_min"], gov["strategy"]["short_delta_max"], now,
    )
    if not candidates:
        _append_journal("no_trade", reason="no_candidates", underlying=underlying)
        return {"attempted": True, "filled": False, "reason": "no_candidates"}

    base_gate_state = {
        **account_state,
        "paper_verified": True,
        "halt_active": halt_active,
        "open_positions": [
            {"underlying": r["underlying"], "max_loss_dollars": r.get("max_loss_dollars", 0)}
            for r in open_positions_journal
        ],
        "entries_today": entries_today,
        "consecutive_exceptions": consecutive_exceptions,
        "realised_vol_20d": u_state["realised_vol_20d"],
        "intraday_move_pct": u_state["intraday_move_pct"],
        "vix": regime["vix"], "vix9d": regime["vix9d"], "vix3m": regime["vix3m"],
        "event_blackouts": regime["event_blackouts"],
        "filled_underlyings_today": filled_underlyings_today,
    }

    winner, winner_qty, last_reason = None, 0, "no_candidates"
    for candidate in candidates:
        candidate = dataclasses.replace(candidate, underlying=underlying)
        expiry_puts = [c for c in u_state["contracts"] if c.expiry == candidate.expiry]
        atm_iv = market.compute_atm_iv(expiry_puts, u_state["spot"])
        gate_state = {**base_gate_state, "atm_iv": atm_iv}
        reason, qty = risk.check_all(gate_state, candidate, gov, now)
        if reason is None:
            winner, winner_qty = candidate, qty
            break
        last_reason = reason

    if winner is None:
        _append_journal("no_trade", reason=last_reason, underlying=underlying)
        return {"attempted": True, "filled": False, "reason": last_reason}

    ladder_result = _attempt_entry(winner, winner_qty, window_label, trade_date, now, gov, profile, dry_run)
    return {"attempted": True, "underlying": underlying, **ladder_result}


def _cross_check_entries_today(journal_count, now, profile):
    """Cross-checks the journal-derived count against the broker's own
    closed orders for today, filtered to Theta Gate entry client_order_ids.
    'closed' as an alpaca order-list status value is Alpaca's standard REST
    status filter (open/closed/all) -- not verified live this session. Any
    failure here (wrong status value, network issue, unexpected shape) is
    swallowed and the journal-only count is trusted alone; the HIGHER of
    the two counts is used, so a mismatch only ever makes entry gating more
    conservative, never less."""
    try:
        today = now.astimezone(ET).strftime("%Y%m%d")
        closed = alpaca.list_orders(status="closed", profile=profile)
        if not isinstance(closed, list):
            return journal_count
        prefix = f"tg-e-{today}-"
        broker_count = sum(
            1 for o in closed
            if isinstance(o, dict) and str(o.get("client_order_id") or "").startswith(prefix)
            and o.get("status") == "filled"
        )
    except Exception:
        return journal_count
    if broker_count != journal_count:
        _append_journal("reconciliation_mismatch", journal_entries_today=journal_count, broker_entries_today=broker_count)
    return max(journal_count, broker_count)


# ---------------------------------------------------------------------------
# Git publish -- transport only, never load-bearing for trading logic
# (canonical Sec 13.4). A failed push is logged, never crashes the tick.
# ---------------------------------------------------------------------------

def _git_publish(now):
    """Publishes the journal AND the HALT flag together. HALT is only a
    real circuit breaker if it survives to the next tick's fresh checkout
    on an ephemeral CI runner -- an unpublished HALT.json is silently lost
    the moment that runner is destroyed, defeating every HALT trigger in
    this file exactly the way an unpublished journal entry defeats the
    risk caps (see the publish_failed check in _run_tick_body). HALT.json
    is only ever git-added when it exists, and its content is stable
    (only _trigger_halt writes to it after the first tick), so this does
    not create a commit every tick -- only when a halt is newly set."""
    try:
        subprocess.run(["git", "pull", "--rebase", "origin", "main"],
                        capture_output=True, text=True, timeout=30, check=False)
        paths = [JOURNAL_PATH] + ([HALT_PATH] if Path(HALT_PATH).exists() else [])
        status = subprocess.run(["git", "status", "--porcelain", *paths],
                                 capture_output=True, text=True, timeout=15, check=False)
        if not status.stdout.strip():
            return {"committed": False, "reason": "nothing to commit"}
        subprocess.run(["git", "add", *paths], capture_output=True, text=True, timeout=15, check=False)
        subprocess.run(["git", "commit", "-m", f"journal: tick {now.isoformat()}"],
                        capture_output=True, text=True, timeout=15, check=False)
        push = subprocess.run(["git", "push"], capture_output=True, text=True, timeout=30, check=False)
        if push.returncode != 0:
            # one rebase-and-retry, then give up quietly
            subprocess.run(["git", "pull", "--rebase", "origin", "main"],
                            capture_output=True, text=True, timeout=30, check=False)
            push = subprocess.run(["git", "push"], capture_output=True, text=True, timeout=30, check=False)
        return {
            "committed": True, "pushed": push.returncode == 0,
            "push_error": None if push.returncode == 0 else push.stderr[:300],
        }
    except Exception as exc:
        return {"committed": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_tick(now=None, dry_run=False, profile="submission"):
    now = now if now is not None else datetime.now(ET)
    Path("data").mkdir(exist_ok=True)

    if not _acquire_lock():
        return {"ok": True, "now": now.isoformat(), "skipped": "concurrent_run_blocked"}
    try:
        return _run_tick_guarded(now, dry_run, profile)
    finally:
        _release_lock()


def _run_tick_guarded(now, dry_run, profile):
    """run_tick's typed contract is `-> dict`, never a raised exception --
    any unexpected failure below is caught, journaled (so
    gate_cumulative_drawdown's consecutive_exceptions count sees it on the
    next tick), and returned as ok=False. The CLI entrypoint decides the
    process exit code from that field."""
    try:
        return _run_tick_body(now, dry_run, profile)
    except Exception as exc:
        _append_journal("tick_exception", level="critical", error=f"{type(exc).__name__}: {exc}")
        _append_journal("tick_completed", ok=False, error=str(exc))
        return {"ok": False, "now": now.isoformat(), "error": str(exc)}


def _run_tick_body(now, dry_run, profile):
    with open(GOVERNANCE_PATH, encoding="utf-8") as f:
        gov = json.load(f)

    # Step 2 -- prove paper before anything else. Any failure: CRITICAL, STOP.
    try:
        alpaca.assert_paper(profile)
    except alpaca.NotPaperError as exc:
        _append_journal("not_paper_abort", level="critical", profile=profile, error=str(exc))
        return {"ok": False, "now": now.isoformat(), "aborted_at": "assert_paper", "error": str(exc)}

    # Step 3
    halt_active, halt_info = _check_halt()

    # Step 4 -- fresh every tick, never trusted from a prior tick's memory
    positions = alpaca.positions(profile=profile)
    open_orders = alpaca.list_orders(status="open", profile=profile)
    account = alpaca.account(profile=profile)
    account_state = _map_account_state(account)

    # Step 5
    orphan_symbols = risk.detect_orphan_equity(positions)
    block_entries_orphan = bool(orphan_symbols)
    if orphan_symbols:
        _append_journal(
            "assignment_detected", level="critical", symbols=orphan_symbols, flatten_attempted=False,
            gap="alpaca.py exposes no stock-order submission method -- not added this session "
                "(alpaca.py's write boundary was out of scope this diff). Needs a human decision.",
        )

    # Step 6 -- exits run regardless of HALT/orphan-block, deterministic, before any entry logic
    journal_events = _read_journal()
    open_positions_journal = _open_positions(journal_events)
    option_positions = {p.get("symbol"): p for p in positions if p.get("asset_class") == "us_option"}

    # The journal is only durable once git-published; on an ephemeral CI
    # runner, a tick whose push silently failed (see the git-publish check
    # at the end of this function) leaves its entry_filled event invisible
    # to every future tick's fresh checkout. If the broker shows an open
    # option leg no currently-known position accounts for, that is exactly
    # what a lost entry_filled looks like -- HALT rather than silently
    # under-counting entries_today/open_positions against the real risk caps.
    journal_known_symbols = {
        s for rec in open_positions_journal for s in (rec.get("short_symbol"), rec.get("long_symbol")) if s
    }
    untracked_symbols = set(option_positions) - journal_known_symbols
    if untracked_symbols:
        _trigger_halt(f"broker shows open option position(s) the journal has no record of: {sorted(untracked_symbols)}")
        _append_journal(
            "untracked_broker_position", level="critical", symbols=sorted(untracked_symbols),
            note="broker holds option position(s) missing from the journal's view -- likely a lost "
                 "entry_filled event (e.g. a git-publish failure on an earlier runner). HALT set; "
                 "needs human reconciliation before further entries.",
        )

    exits_this_tick = []
    for entry_rec in open_positions_journal:
        result = _evaluate_and_exit_position(
            entry_rec, option_positions, gov, now, profile, dry_run, open_orders, journal_events,
        )
        if result is not None:
            exits_this_tick.append(result)

    # Re-read post-exit: anything that just closed above must not still
    # count as open exposure for this same tick's entry gating.
    journal_events = _read_journal()
    open_positions_journal = _open_positions(journal_events)
    entries_today, filled_underlyings_today = _entries_today(journal_events, now)
    consecutive_exceptions = _consecutive_exceptions(journal_events)
    entries_today = _cross_check_entries_today(entries_today, now, profile)

    # Re-check HALT: the untracked-position check above, or a naked-leg
    # detection inside the exit loop, may have just set it THIS tick --
    # the halt_active read at step 3 predates both and must not be trusted
    # to gate step 7's entry decision below.
    halt_active, _ = _check_halt()

    entry_result = {"attempted": False}
    if halt_active:
        # Step 7
        _append_journal("no_trade", reason="halt_active")
    elif block_entries_orphan:
        _append_journal("no_trade", reason="orphan_equity_block")
    else:
        # Step 8
        window_label = _current_entry_window(now, gov)
        if window_label is None:
            _append_journal("no_trade", reason="outside_entry_window")
        # Step 9
        elif entries_today >= gov["entry"]["max_new_entries_per_session"]:
            _append_journal("no_trade", reason="max_entries_reached")
        else:
            # Step 10
            entry_result = _attempt_entry_pipeline(
                window_label, now, gov, profile, dry_run, account_state,
                open_positions_journal, entries_today, filled_underlyings_today,
                consecutive_exceptions, halt_active,
            )

    # Step 11
    _append_journal(
        "tick_completed", ok=True, halt_active=halt_active, orphan_symbols=orphan_symbols,
        exits=len(exits_this_tick), entry_attempted=entry_result.get("attempted", False),
    )
    git_result = _git_publish(now)

    # A commit that failed to push is not "transport, never load-bearing" --
    # this tick wrote real state (an entry_filled/exit_filled/HALT-relevant
    # event) that a future tick's fresh checkout will never see. That
    # silently defeats every journal-derived risk cap (entries_today,
    # open_positions, ...). Surface it as a tick failure: main() exits
    # non-zero (a red GitHub Actions run a human notices) and, once this
    # event DOES reach a future successful push, consecutive_exceptions
    # sees it too.
    publish_failed = bool(git_result.get("committed")) and not git_result.get("pushed")
    if publish_failed:
        _append_journal("journal_publish_failed", level="critical", git_result=git_result,
                         note="journal committed locally but push failed -- this runner's state may "
                              "never reach the next tick's fresh checkout")

    return {
        "ok": not publish_failed, "now": now.isoformat(), "halt_active": halt_active,
        "orphan_symbols": orphan_symbols, "exits": exits_this_tick,
        "entry": entry_result, "git": git_result,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Theta Gate one-tick orchestrator")
    parser.add_argument("--once", action="store_true",
                         help="run a single tick and exit (the only mode V1 needs; a tick always runs "
                              "exactly once regardless -- this flag documents intent for a future looping mode)")
    parser.add_argument("--dry-run", action="store_true",
                         help="thread dry_run through to every broker WRITE (submit_mleg, cancel_order); "
                              "reconciliation, gates, and journaling still happen for real, including real "
                              "reads, real HALT triggers, and a real call to Anthropic via brain.propose")
    parser.add_argument("--profile", default="submission",
                         help="Alpaca CLI profile to trade against (default: submission)")
    args = parser.parse_args()

    now = datetime.now(ET)
    summary = run_tick(now=now, dry_run=args.dry_run, profile=args.profile)
    print(json.dumps(summary, indent=2, default=str))
    if not summary.get("ok", False):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
