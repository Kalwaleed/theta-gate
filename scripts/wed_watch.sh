#!/bin/bash
# Wednesday 2 Sep: the LAST entry window. Watch from the open, not from 10:30.
# Reports (1) the credit-quality reading just after the open, ~55 min before the
# window, (2) any exit signal on either open position, (3) the window outcome.
cd /Users/papasmurf/Documents/Code_Projects/ClaudeCode/Projects/Alpaca_AI_Trading_Agent
TARGET=0902   # Wed 2 Sep
now_et() { TZ=America/New_York date "+$1"; }

# 1. sleep until the Wednesday open
while :; do
  d=$(now_et '%m%d'); t=$(now_et '%H%M')
  [ "$d" = "$TARGET" ] && [ "$t" -ge 0928 ] && break
  [ "$d" -gt "$TARGET" ] && { echo "MISSED: it is already past Wed 2 Sep — re-arm manually"; exit 1; }
  sleep 300
done
echo "=== WED 2 SEP — MARKET OPEN, $(now_et '%H:%M') ET. Last entry window is 10:30; entries close 10:45. ==="

# 2. the credit reading, once quotes are live
while [ "$(now_et '%H%M')" -lt 0936 ]; do sleep 30; done
set -a; source .env; set +a
echo "--- credit-quality reading, live band, ~55 min before the final window ---"
timeout 280 env PYTHONPATH=. .venv/bin/python3 scripts/measure_credit_curve.py 2>&1 \
  | grep -E "^== (SPY|QQQ)  3-5|\\\$   5 wide|credit_quality|minimum_credit" | sed 's/^ *//'

# 3. journal watch through the window. The parser lives in scripts/journal_watch.py
# because Python quoted inside a shell string is not syntax-checked until it runs,
# and on 2 Sep that moment was a SyntaxError in every poll of this loop.
seen=0
wseq=0
J="${TMPDIR:-/tmp}/wed_journal.jsonl"
while :; do
  git fetch -q origin main 2>/dev/null || true
  j=$(git show FETCH_HEAD:data/journal.jsonl 2>/dev/null)
  if [ -n "$j" ]; then
    n=$(printf '%s\n' "$j" | wc -l | tr -d ' ')
    if [ "$seen" -eq 0 ]; then seen=$n; elif [ "$n" -gt "$seen" ]; then
      printf '%s\n' "$j" > "$J"
      out=$(env PYTHONPATH=. .venv/bin/python3 scripts/journal_watch.py --journal "$J" --since "$wseq")
      printf '%s\n' "$out" | grep -v '^SEQ='
      new=$(printf '%s\n' "$out" | sed -n 's/^SEQ=//p'); [ -n "$new" ] && wseq=$new
      seen=$n
    fi
  fi
  [ "$(now_et '%H%M')" -ge 1052 ] && break
  sleep 60
done
echo "=== FINAL ENTRY WINDOW CLOSED ($(now_et '%H:%M') ET). No further entries this hackathon. ==="
printf '%s\n' "$j" | grep -E '"event": *"(entry_filled|exit_evaluated|tick_completed)"' | tail -4
