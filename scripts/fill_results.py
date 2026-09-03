#!/usr/bin/env python3
"""Fill the Results placeholders in the deck and the write-up from the
journal, once the book is flat.

  python scripts/fill_results.py --dry-run    # show the numbers, change nothing
  python scripts/fill_results.py              # write them in

Thursday holds the flatten, the deck, the write-up, the repo flip and the
recording. Hand-editing 14 substitutions across two files under that much
time pressure is how a wrong number ships, so this does it from one source
and prints what it did.

REFUSES TO RUN WITH OPEN POSITIONS unless --force is passed. A P&L filled
from a half-closed book is worse than a placeholder: the placeholder is
obviously unfinished, the wrong number is not.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import store  # noqa: E402

DECK = Path(__file__).resolve().parent.parent / "deck" / "theta-gate.tex"
WRITEUP = Path(__file__).resolve().parent.parent / "submission" / "WRITEUP.md"


def max_drawdown_pct(curve):
    """Largest peak-to-trough fall in realised equity, as a positive
    percentage. Realised-only, matching the curve the dashboard draws --
    Alpaca posts paper non-trade activity the next day, so an intraday
    mark-to-market figure would not reconcile with the account."""
    peak = None
    worst = 0.0
    for point in curve:
        equity = point["equity"]
        peak = equity if peak is None else max(peak, equity)
        if peak > 0:
            worst = max(worst, (peak - equity) / peak)
    return worst * 100


def collect(starting_equity=100_000):
    conn = store.connect()
    s = store.summary(conn, starting_equity=starting_equity)
    curve = store.equity_curve(conn, starting_equity=starting_equity)
    closed = s["positions_closed"]
    return {
        "open": s["positions_open"],
        "P&L": f"${s['realised_pnl_dollars']:,.2f}" if s["realised_pnl_dollars"] >= 0
               else f"-${abs(s['realised_pnl_dollars']):,.2f}",
        "n": str(closed),
        # Explicit rather than 0%: a win rate over zero trades is undefined,
        # and printing "0%" would read as "we lost every one".
        "%": f"{100 * s['wins'] / closed:.0f}%" if closed else "n/a",
        "s": str(len(s["sessions"])),
        "drawdown": f"{max_drawdown_pct(curve):.1f}%",
        "wins": s["wins"],
    }


def apply(vals, dry_run):
    # The deck has two \PLACEHOLDER{\%}: win rate first, max drawdown
    # second, in frame order. They are NOT the same number.
    deck = DECK.read_text(encoding="utf-8")
    deck_new = (deck.replace(r"\PLACEHOLDER{P\&L}", vals["P&L"])
                    .replace(r"\PLACEHOLDER{n}", vals["n"]))
    deck_new = deck_new.replace(r"\PLACEHOLDER{\%}", vals["%"], 1)
    deck_new = deck_new.replace(r"\PLACEHOLDER{\%}", vals["drawdown"], 1)

    wu = WRITEUP.read_text(encoding="utf-8")
    wu_new = (wu.replace("[P&L]", vals["P&L"])
                .replace("[n]", vals["n"])
                .replace("[s]", vals["s"]))
    wu_new = wu_new.replace("[%]", vals["%"], 1)
    wu_new = wu_new.replace("[%]", vals["drawdown"], 1)

    # Count INVOCATIONS only. The \newcommand definition and the header
    # comment both contain the word and must survive -- counting them made
    # a fully-filled deck report two remaining, so the exit code lied.
    deck_left = sum(
        line.count(r"\PLACEHOLDER{")
        for line in deck_new.splitlines()
        if not line.lstrip().startswith("%") and r"\newcommand{\PLACEHOLDER}" not in line
    )
    left = deck_left + len(re.findall(r"\[(P&L|n|%|s)\]", wu_new))
    if not dry_run:
        DECK.write_text(deck_new, encoding="utf-8")
        WRITEUP.write_text(wu_new, encoding="utf-8")
    return left


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="fill even with positions still open (do not use for the submission)")
    args = ap.parse_args(argv)

    vals = collect()
    print(f"  realised P&L   {vals['P&L']}")
    print(f"  trades closed  {vals['n']}")
    print(f"  win rate       {vals['%']}   ({vals['wins']} of {vals['n']})")
    print(f"  max drawdown   {vals['drawdown']}")
    print(f"  sessions       {vals['s']}")

    if vals["open"] and not args.force:
        print(f"\n  REFUSING: {vals['open']} position(s) still open. The book is not flat, so "
              f"these numbers are not final.\n  Re-run after the flatten, or pass --force.")
        return 1
    if vals["n"] == "0" and not args.force:
        print("\n  REFUSING: no closed trades. Nothing to report yet.")
        return 1

    left = apply(vals, args.dry_run)
    print(f"\n  {'would fill' if args.dry_run else 'filled'} deck + write-up; "
          f"{left} placeholder(s) remaining")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
