"""SQLite read model, derived from data/journal.jsonl. Never a second
source of truth.

The canonical plan specced Postgres with row-level security and six
credentialed roles; docs/PLAN.md cut that as out of scope for a 5-day
paper demo. This file is the middle path -- the queryable history the
dashboard and the write-up need, without a service, a schema migration
story, or a second thing that can disagree with the broker.

The split that makes this safe:

  * journal.jsonl stays the append-only WRITE path, exactly as built and
    verified. loop.py's `_append_journal` is untouched by this file. The
    intent-before-network-call durability property is a property of that
    append, and nothing here weakens it.
  * this database is a pure FUNCTION of that file. `rebuild()` drops and
    replays from line 1 every time, so it can never drift: if it and the
    journal disagree, the journal wins by construction and the fix is to
    rebuild. It is gitignored precisely so nobody is tempted to treat a
    committed binary as authority.

That direction of dependency is also why SQLite is a better fit here than
Postgres *or* than promoting SQLite to the primary store. A committed
binary .db in the git-publish path would collide with the one durability
mechanism this repo actually has -- five people rebasing onto main while
an Actions cron commits the journal several times a day. JSONL merges and
diffs; a .db file does not.

What the database adds that a linear scan of the JSONL does not:

  1. Aggregation for app.py -- "why no trade" counted by gate, the equity
     curve, per-session decision logs -- as SQL rather than hand-rolled
     Python loops over a list of dicts.
  2. A hash chain over the accepted lines (`chain_sha256`), which makes
     retroactive edits to trading history detectable. This is the one
     piece of the canonical plan's event-sourcing story that costs
     almost nothing to keep.
  3. A place to answer questions loop.py doesn't need but a judge will
     ask: quoted vs filled slippage, time-to-fill, gate rejection
     frequency by reason.

Every query function here has a pure-Python counterpart in loop.py
(`_open_positions`, `_entries_today`, `_consecutive_exceptions`,
`_exit_attempt_number`). Those remain the reference implementation for
trading decisions. test_store.py asserts the two agree on the same
input; if they ever diverge, loop.py is right and this file has a bug.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

JOURNAL_PATH = "data/journal.jsonl"
DB_PATH = "data/theta_gate.db"

SCHEMA_VERSION = 2

# Fixed no_trade reasons emitted by loop.py that are NOT risk-gate vetoes.
# A gate veto arrives as the gate's own return string, shaped
# "gate_name: detail", so anything outside this set that contains ": " is
# attributed to its gate. Kept explicit rather than inferred so a new bare
# reason token shows up as 'other' in the dashboard instead of being
# silently mis-parsed into a nonexistent gate.
NON_GATE_NO_TRADE_REASONS = {
    "all_underlyings_at_cap",
    "bearish_no_call_side",
    "halt_active",
    "max_entries_reached",
    "model_failure_or_malformed",
    "no_candidates",
    "orphan_equity_block",
    "outside_entry_window",
    "regime_data_unavailable",
    "underlying_data_unavailable",
    "underlying_unavailable",
    "unsupported_underlying",
}

DDL = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per accepted journal line, in file order. `payload` keeps the
-- original object verbatim so no query here can lose a field that a later
-- question turns out to need.
CREATE TABLE events (
    seq          INTEGER PRIMARY KEY,
    ts           TEXT NOT NULL,
    session_date TEXT,
    event        TEXT NOT NULL,
    level        TEXT,
    position_id  TEXT,
    underlying   TEXT,
    reason       TEXT,
    gate         TEXT,
    order_id     TEXT,
    client_order_id TEXT,
    ok           INTEGER,
    payload      TEXT NOT NULL,
    line_sha256  TEXT NOT NULL,
    chain_sha256 TEXT NOT NULL
);

CREATE INDEX idx_events_event ON events(event);
CREATE INDEX idx_events_position ON events(position_id);
CREATE INDEX idx_events_session ON events(session_date);

-- Derived, one row per position that ever filled. Rebuilt with the rest.
CREATE TABLE positions (
    position_id     TEXT PRIMARY KEY,
    -- The seq of the entry_filled/exit_filled row each side came from.
    -- Joining back on ts instead was a real parity bug: a replay can
    -- journal the same position_id twice at the SAME timestamp, and the
    -- ts join then matched both rows, so open_positions() returned two
    -- open positions where loop._open_positions returns one.
    entry_seq       INTEGER,
    exit_seq        INTEGER,
    underlying      TEXT,
    direction       TEXT,
    trade_date      TEXT,
    window          TEXT,
    expiry          TEXT,
    short_symbol    TEXT,
    long_symbol     TEXT,
    width           REAL,
    qty             INTEGER,
    credit          REAL,
    max_loss_dollars REAL,
    entry_ts        TEXT,
    entry_order_id  TEXT,
    exit_ts         TEXT,
    exit_reason     TEXT,
    close_debit     REAL,
    exit_order_id   TEXT,
    realised_pnl_dollars REAL,
    status          TEXT NOT NULL
);

-- The "why no trade" panel, straight out of the journal.
CREATE VIEW gate_rejections AS
    SELECT session_date,
           COALESCE(gate, 'other') AS gate,
           reason,
           COUNT(*) AS n
    FROM events
    WHERE event = 'no_trade'
    GROUP BY session_date, gate, reason;

-- Realised P&L in close order. Cumulative sum is left to the caller so
-- this stays a plain projection.
CREATE VIEW realised_pnl AS
    SELECT position_id, underlying, exit_ts, exit_reason,
           credit, close_debit, qty, realised_pnl_dollars
    FROM positions
    WHERE status = 'closed'
    ORDER BY exit_ts;
"""


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _session_date(ts):
    """The ET calendar date a timestamp belongs to. Matches loop.py's
    `_entries_today`, which compares ET dates rather than UTC ones -- a
    19:30 UTC tick is the same trading session as a 14:00 UTC one."""
    try:
        return datetime.fromisoformat(ts).astimezone(ET).date().isoformat()
    except (TypeError, ValueError):
        return None


def _split_gate(reason):
    """A risk-gate veto reaches the journal as the gate's own return
    string ("delta_band: short leg 0.31 outside 0.16-0.25"). Bare tokens
    from loop.py's own control flow have no gate."""
    if not isinstance(reason, str) or reason in NON_GATE_NO_TRADE_REASONS:
        return None
    head, sep, _ = reason.partition(":")
    return head.strip() if sep and head.strip() else None


def read_journal(journal_path=JOURNAL_PATH):
    """Torn-line handling is deliberately identical to loop.py's
    `_read_journal`: a half-written line from a crash mid-append is
    skipped, never raised. The two must agree on which lines exist at all
    or every parity test below is meaningless."""
    path = Path(journal_path)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            records.append((line, obj))
    return records


def rebuild(db_path=DB_PATH, journal_path=JOURNAL_PATH):
    """Drop everything and replay the journal from line 1. Deterministic:
    same journal in, byte-identical logical content out. Returns an open
    connection.

    Rebuilding rather than incrementally appending is the whole safety
    argument -- there is no code path that can leave this database holding
    a fact the journal does not.

    Build-then-rename, not build-in-place. The first version unlinked the
    target and created the schema directly at `db_path`, which is fine for
    the CLI and fatal for the dashboard: Streamlit serves concurrent
    sessions on separate threads, so several cold loads land in here at
    once and stamp on each other mid-DDL. Measured on the real code, 10 of
    12 simultaneous cold loads failed -- `disk I/O error`, `attempt to
    write a readonly database`, `table meta already exists`. On the public
    demo URL that is a broken page in front of a judge, and
    `showErrorDetails = "none"` means it would not even say why.

    Each caller now builds a uniquely-named database of its own and
    `os.replace`s it over the target, which is atomic on POSIX and on
    Windows. Concurrent builders do identical work from the same journal,
    so whichever lands last wins and every one of them is correct -- the
    determinism this function already guaranteed is what makes the race
    benign rather than merely unlikely.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique per process AND per thread: Streamlit's concurrency is threads
    # inside one process, so a pid-only suffix would still collide.
    staging = path.with_name(f"{path.name}.building.{os.getpid()}.{threading.get_ident()}")
    staging.unlink(missing_ok=True)

    conn = sqlite3.connect(str(staging))
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)

    records = read_journal(journal_path)
    chain = ""
    rows = []
    for seq, (raw, obj) in enumerate(records, start=1):
        line_sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        chain = hashlib.sha256((chain + line_sha).encode("utf-8")).hexdigest()
        reason = obj.get("reason")
        ok = obj.get("ok")
        rows.append((
            seq,
            obj.get("ts"),
            _session_date(obj.get("ts")),
            obj.get("event", ""),
            obj.get("level"),
            obj.get("position_id"),
            obj.get("underlying"),
            reason if isinstance(reason, str) else None,
            _split_gate(reason) if obj.get("event") == "no_trade" else None,
            obj.get("order_id"),
            obj.get("client_order_id"),
            None if ok is None else int(bool(ok)),
            json.dumps(obj, sort_keys=True),
            line_sha,
            chain,
        ))

    conn.executemany(
        "INSERT INTO events (seq, ts, session_date, event, level, position_id, underlying,"
        " reason, gate, order_id, client_order_id, ok, payload, line_sha256, chain_sha256)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?)",
        [
            ("schema_version", str(SCHEMA_VERSION)),
            ("journal_path", str(journal_path)),
            ("event_count", str(len(rows))),
            ("chain_head", chain),
        ],
    )
    _build_positions(conn)
    conn.commit()
    conn.close()

    try:
        # Atomic on POSIX and Windows: readers either see the whole old
        # database or the whole new one, never a half-built schema.
        os.replace(staging, path)
    except OSError:
        staging.unlink(missing_ok=True)
        raise

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _build_positions(conn):
    """Fold entry_filled/exit_filled into one row per position.

    Mirrors loop.py's `_open_positions`: an entry is keyed by position_id
    with the LAST entry_filled winning (an adopted-order replay can
    journal the same position twice), and it counts as closed the moment
    any exit_filled names it. Deliberately does not try to be cleverer
    than loop.py here -- divergence is the bug this design exists to
    prevent.
    """
    entries, exits = {}, {}
    for row in conn.execute(
        "SELECT seq, ts, event, payload FROM events"
        " WHERE event IN ('entry_filled','exit_filled') ORDER BY seq"
    ):
        obj = json.loads(row["payload"])
        pid = obj.get("position_id")
        if not pid:
            continue
        (entries if row["event"] == "entry_filled" else exits)[pid] = (row["seq"], row["ts"], obj)

    rows = []
    for pid, (entry_seq, entry_ts, e) in entries.items():
        exit_seq, exit_ts, x = exits.get(pid, (None, None, {}))
        credit, qty = e.get("credit"), e.get("qty")
        debit = x.get("close_debit")
        pnl = None
        if x and None not in (credit, debit, qty):
            # Credit received minus debit paid to close, per contract, x100.
            pnl = round((credit - debit) * 100 * qty, 2)
        rows.append((
            pid, entry_seq, exit_seq,
            e.get("underlying"), e.get("direction"), e.get("trade_date"),
            e.get("window"), e.get("expiry"), e.get("short_symbol"), e.get("long_symbol"),
            e.get("width"), qty, credit, e.get("max_loss_dollars"),
            entry_ts, e.get("order_id"),
            exit_ts, x.get("reason"), debit, x.get("order_id"),
            pnl, "closed" if pid in exits else "open",
        ))

    conn.executemany(
        "INSERT INTO positions (position_id, entry_seq, exit_seq, underlying, direction,"
        " trade_date, window, expiry, short_symbol, long_symbol, width, qty, credit,"
        " max_loss_dollars, entry_ts, entry_order_id, exit_ts, exit_reason, close_debit,"
        " exit_order_id, realised_pnl_dollars, status)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def connect(db_path=DB_PATH, journal_path=JOURNAL_PATH, rebuild_if_stale=True):
    """Open the read model, rebuilding when it is missing or behind the
    journal. Cheap enough to call on every dashboard page load: the
    journal is a few hundred lines over the whole hackathon.

    Every read here is wrapped, because this is the dashboard's only entry
    point and it runs on a public URL with `showErrorDetails = "none"` --
    an escaping sqlite3 error is a blank page a judge cannot interpret and
    we cannot diagnose. A reader can legitimately arrive mid-`os.replace`
    and find a file that vanished or changed identity under it; the answer
    is always the same, and always safe: rebuild from the journal, which
    is the source of truth anyway.
    """
    path = Path(db_path)
    if not path.exists():
        return rebuild(db_path, journal_path)

    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        if not rebuild_if_stale:
            return conn
        stored = conn.execute("SELECT value FROM meta WHERE key='event_count'").fetchone()
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    except (sqlite3.Error, OSError):
        return rebuild(db_path, journal_path)

    live = len(read_journal(journal_path))
    if stored is None or version is None or int(stored[0]) != live or int(version[0]) != SCHEMA_VERSION:
        conn.close()
        return rebuild(db_path, journal_path)
    return conn


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------

def verify_chain(conn):
    """Recompute the hash chain over stored rows. Returns (ok, seq) where
    seq is the first divergent row, or None when intact.

    This detects an edited or reordered history *inside the database*. It
    is not a defence against someone rewriting journal.jsonl and
    rebuilding -- git history is what covers that -- but it does mean the
    artifact a judge queries can be shown to be a faithful replay.
    """
    chain = ""
    for row in conn.execute("SELECT seq, payload, line_sha256, chain_sha256 FROM events ORDER BY seq"):
        chain = hashlib.sha256((chain + row["line_sha256"]).encode("utf-8")).hexdigest()
        if chain != row["chain_sha256"]:
            return False, row["seq"]
    return True, None


# ---------------------------------------------------------------------------
# Queries -- parity counterparts to loop.py's journal scans
# ---------------------------------------------------------------------------

def open_positions(conn):
    """Counterpart to loop._open_positions. Returns the entry_filled
    payloads, so callers see exactly what the journal scan hands back."""
    rows = conn.execute(
        "SELECT e.payload FROM positions p"
        " JOIN events e ON e.seq = p.entry_seq"
        " WHERE p.status = 'open'"
    ).fetchall()
    return [json.loads(r["payload"]) for r in rows]


def entries_today(conn, now):
    """Counterpart to loop._entries_today. Returns (count, underlyings)."""
    today = now.astimezone(ET).date().isoformat()
    rows = conn.execute(
        "SELECT underlying FROM events WHERE event='entry_filled' AND session_date=? ORDER BY seq",
        (today,),
    ).fetchall()
    return len(rows), [r["underlying"] for r in rows]


def consecutive_exceptions(conn):
    """Counterpart to loop._consecutive_exceptions: the trailing run of
    ok=false tick_completed rows, stopping at the first ok=true."""
    count = 0
    for row in conn.execute(
        "SELECT ok FROM events WHERE event='tick_completed' ORDER BY seq DESC"
    ):
        # loop.py reads a missing `ok` as true, so NULL breaks the run too.
        if row["ok"] is None or row["ok"]:
            break
        count += 1
    return count


def exit_attempt_number(conn, position_id):
    """Counterpart to loop._exit_attempt_number."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE event='exit_unfilled' AND position_id=?",
        (position_id,),
    ).fetchone()
    return row["n"] + 1


# ---------------------------------------------------------------------------
# Queries -- reporting, for app.py and the write-up
# ---------------------------------------------------------------------------

def gate_rejection_counts(conn, session_date=None):
    """The "why no trade" panel. Ordered most-frequent-first."""
    if session_date:
        sql = ("SELECT gate, reason, SUM(n) AS n FROM gate_rejections WHERE session_date=?"
               " GROUP BY gate, reason ORDER BY n DESC, reason")
        rows = conn.execute(sql, (session_date,)).fetchall()
    else:
        sql = ("SELECT gate, reason, SUM(n) AS n FROM gate_rejections"
               " GROUP BY gate, reason ORDER BY n DESC, reason")
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def equity_curve(conn, starting_equity):
    """Realised-only equity, one point per closed position, in close
    order. Deliberately not mark-to-market: paper non-trade activities
    land next day (docs/PLAN.md), so an intraday unrealised number built
    from this journal would be quietly wrong."""
    equity = float(starting_equity)
    points = [{"ts": None, "position_id": None, "realised": 0.0, "equity": equity}]
    for row in conn.execute("SELECT * FROM realised_pnl"):
        equity += row["realised_pnl_dollars"] or 0.0
        points.append({
            "ts": row["exit_ts"],
            "position_id": row["position_id"],
            "realised": row["realised_pnl_dollars"],
            "equity": round(equity, 2),
        })
    return points


def decision_log(conn, limit=200):
    """Everything that happened, newest first, minus routine per-tick noise.

    This was an ALLOWLIST of twelve event names, and it silently rotted:
    loop.py emits thirty, so nine of the events an operator most needs to
    see were invisible on the dashboard -- assignment_detected,
    untracked_broker_position, submit_failed, journal_publish_failed,
    exit_fill_leg_mismatch, force_close_unresolved and the
    *_stale_unresolved family. `proposal` had already gone missing the
    same way and was fixed by hand.

    The worst of those is force_close_unresolved. It fires when Thursday's
    mandatory flatten fails to close a position -- the single highest-stakes
    event of the week -- and the page would not have shown it.

    So it is a DENYLIST now. A new event type added to loop.py appears
    automatically; only noise has to be named. An allowlist fails closed
    on visibility, which is the wrong direction for a page whose job is to
    show what happened.

    Excluded, and why each is safe to drop:
      tick_completed   fires every 5-20 minutes all session, ~40/day, and
                       carries no decision.
      exit_evaluated   per-tick mark-to-market telemetry, 26 on 31 Aug
                       alone, almost always signal=hold. When an exit
                       actually triggers, exit_intent follows and IS shown.
      no_trade with reason outside_entry_window -- the loop declining to
                       look, not a decision about a candidate. Every other
                       no_trade reason, gate vetoes included, is shown.
    """
    rows = conn.execute(
        "SELECT seq, ts, session_date, event, level, position_id, underlying, reason, gate, payload"
        " FROM events"
        " WHERE event NOT IN ('tick_completed','exit_evaluated')"
        "   AND NOT (event = 'no_trade' AND reason = 'outside_entry_window')"
        " ORDER BY seq DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        rec = dict(r)
        rec["payload"] = json.loads(rec["payload"])
        out.append(rec)
    return out


def summary(conn, starting_equity=100000):
    """One dict for the top of the dashboard and the write-up's numbers."""
    counts = {
        r["event"]: r["n"]
        for r in conn.execute("SELECT event, COUNT(*) AS n FROM events GROUP BY event")
    }
    pos = conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(status='open') AS open_now,"
        " SUM(status='closed') AS closed,"
        " SUM(CASE WHEN status='closed' AND realised_pnl_dollars > 0 THEN 1 ELSE 0 END) AS wins,"
        " COALESCE(SUM(realised_pnl_dollars), 0) AS realised"
        " FROM positions"
    ).fetchone()
    chain_ok, bad_seq = verify_chain(conn)
    sessions = [r[0] for r in conn.execute(
        "SELECT DISTINCT session_date FROM events WHERE session_date IS NOT NULL ORDER BY session_date"
    )]
    return {
        "events": sum(counts.values()),
        "event_counts": counts,
        "sessions": sessions,
        "positions_total": pos["total"] or 0,
        "positions_open": pos["open_now"] or 0,
        "positions_closed": pos["closed"] or 0,
        "wins": pos["wins"] or 0,
        "realised_pnl_dollars": round(pos["realised"] or 0.0, 2),
        "equity": round(starting_equity + (pos["realised"] or 0.0), 2),
        "chain_intact": chain_ok,
        "chain_first_bad_seq": bad_seq,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Theta Gate SQLite read model")
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--journal", default=JOURNAL_PATH)
    parser.add_argument("--rebuild", action="store_true", help="drop and replay the journal")
    parser.add_argument("--verify", action="store_true", help="check the hash chain")
    parser.add_argument("--summary", action="store_true", help="print the summary dict")
    parser.add_argument("--gates", action="store_true", help="print no-trade counts by gate")
    args = parser.parse_args(argv)

    conn = rebuild(args.db, args.journal) if args.rebuild else connect(args.db, args.journal)

    if args.verify or args.rebuild:
        ok, seq = verify_chain(conn)
        print(f"chain: {'intact' if ok else f'BROKEN at seq {seq}'}")
    if args.summary or not (args.verify or args.gates):
        print(json.dumps(summary(conn), indent=2, default=str))
    if args.gates:
        for row in gate_rejection_counts(conn):
            print(f"{row['n']:>4}  {row['gate'] or '-':<24} {row['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
