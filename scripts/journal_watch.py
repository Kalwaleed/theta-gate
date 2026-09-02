#!/usr/bin/env python3
"""Read the journal for a shell watcher: what happened, is the book flat,
and the deck numbers.

This replaces the `python3 -c '...'` block wed_watch.sh embedded. Python
quoted inside a shell string is never syntax-checked until it runs, and on
2 Sep that moment was a SyntaxError in every poll of the final entry
window -- the window ran unwatched. A real file is imported by
test_journal_watch.py, so CI is the gate now.

It reuses store.decision_log (a DENYLIST -- a new event type in loop.py
appears here on its own) instead of the hand-picked allowlist wed_watch.sh
carried, which was already missing naked_leg_detected,
exit_reconciliation_gap and the whole *_stale_unresolved family. See that
function's docstring for the same mistake, made once before in app.py.
"""

import argparse
import json

import loop
import store

FIELDS = ("position_id", "underlying", "reason", "gate")
# Payload keys worth a line of terminal width. Not a filter on which events
# print -- every event prints; this only decides what detail comes with it.
EXTRAS = ("signal", "credit", "qty", "width", "limit_price", "cost_to_close", "error")


def since(conn, seq, limit):
    """Decision-log rows newer than `seq`, oldest first, then the new high
    water mark on a SEQ= line for the caller to feed back in."""
    rows = sorted((r for r in store.decision_log(conn, limit=limit) if r["seq"] > seq),
                  key=lambda r: r["seq"])
    for r in rows:
        crit = "*** CRITICAL *** " if r.get("level") == "critical" else ""
        payload = r.get("payload") or {}
        if r["event"] == "proposal":  # the interesting fields are inside the model's reply
            try:
                payload = {**payload, **json.loads(payload.get("raw_response") or "{}")}
            except (ValueError, TypeError):
                pass
        bits = " ".join([f"{k}={r[k]}" for k in FIELDS if r.get(k)]
                        + [f"{k}={payload[k]}" for k in ("direction", "confidence") + EXTRAS
                           if payload.get(k) is not None])
        print(f"{(r['ts'] or '')[11:19]}  {crit}{(r['event'] or '').upper()}  {bits}".rstrip())
    print(f"SEQ={rows[-1]['seq'] if rows else seq}")
    return 0


def last_tick(conn):
    """Newest tick_completed. The ladder depends on ticks landing near
    14:30/15:00/15:30/15:45 and GitHub Actions cron drifts, so a missing
    tick is a reportable failure -- silence is the dangerous case."""
    row = conn.execute(
        "SELECT ts, payload FROM events WHERE event = 'tick_completed'"
        " ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return 1
    print(f"{row['ts']}  halt={json.loads(row['payload']).get('halt_active')}")
    return 0


def flat(journal_path):
    """Exit 0 only when nothing is open. loop._open_positions is the same
    derivation the force-close ladder itself uses."""
    loop.JOURNAL_PATH = journal_path
    open_now = loop._open_positions(loop._read_journal())
    for p in open_now:
        print(f"OPEN  {p.get('position_id')}  {p.get('underlying')} qty={p.get('qty')}")
    if not open_now:
        print("FLAT: no open positions")
    return 1 if open_now else 0


def stats(conn, starting_equity):
    """The four deck numbers. Print only -- the deck is filled by hand, in
    one sitting, from one source."""
    s = store.summary(conn, starting_equity)
    curve = store.equity_curve(conn, starting_equity)
    peak = starting_equity
    drawdown = 0.0
    for pt in curve:
        peak = max(peak, pt["equity"])
        drawdown = max(drawdown, peak - pt["equity"])
    closed = s["positions_closed"]
    print(f"realised P&L   ${s['realised_pnl_dollars']:+,.2f}")
    print(f"trades closed  {closed}")
    print(f"win rate       {(100.0 * s['wins'] / closed) if closed else 0:.0f}%  ({s['wins']}/{closed})")
    print(f"max drawdown   ${drawdown:,.2f}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--since", type=int, metavar="SEQ", help="decision-log rows newer than SEQ")
    p.add_argument("--flat", action="store_true", help="exit 0 if no position is open")
    p.add_argument("--last-tick", action="store_true", help="newest tick_completed, for cron-lateness checks")
    p.add_argument("--stats", action="store_true", help="the four deck numbers")
    p.add_argument("--journal", default=store.JOURNAL_PATH)
    p.add_argument("--db", default=None, help="default: the real read model, or <journal>.db for any other journal")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--starting-equity", type=float, default=100000)
    args = p.parse_args(argv)

    if args.flat:  # journal-only, no read model needed
        return flat(args.journal)
    # Never rebuild the real read model from a rehearsal journal.
    db = args.db or (store.DB_PATH if args.journal == store.JOURNAL_PATH else args.journal + ".db")
    conn = store.connect(db, args.journal)
    if args.last_tick:
        return last_tick(conn)
    if args.stats:
        return stats(conn, args.starting_equity)
    return since(conn, args.since or 0, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
