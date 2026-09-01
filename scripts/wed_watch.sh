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

# 3. journal watch through the window
seen=0
while :; do
  git fetch -q origin main 2>/dev/null || true
  j=$(git show FETCH_HEAD:data/journal.jsonl 2>/dev/null)
  if [ -n "$j" ]; then
    n=$(printf '%s\n' "$j" | wc -l | tr -d ' ')
    if [ "$seen" -eq 0 ]; then seen=$n; elif [ "$n" -gt "$seen" ]; then
      printf '%s\n' "$j" | tail -n $((n - seen)) | /usr/bin/python3 -c '
import sys, json
LOUD = {"entry_intent","entry_submitted","entry_filled","submit_failed","exit_intent",
        "exit_filled","exit_unfilled","exit_fill_leg_mismatch","assignment_detected",
        "untracked_broker_position","force_close_unresolved","journal_publish_failed",
        "not_paper_abort"}
for line in sys.stdin:
    try: d = json.loads(line)
    except Exception: continue
    e, ts = d.get("event"), d.get("ts","")[11:19]
    if e == "no_trade" and d.get("reason") != "outside_entry_window":
        print(f"{ts}  NO_TRADE  {d.get(\"reason\")}")
    elif e == "proposal":
        try: p = json.loads(d.get("raw_response","{}"))
        except Exception: p = {}
        print(f"{ts}  PROPOSAL  {p.get(\"underlying\")} {p.get(\"direction\")} conf={p.get(\"confidence\")}")
    elif e == "exit_evaluated" and d.get("signal") != "hold":
        print(f"{ts}  EXIT SIGNAL  {d.get(\"position_id\")} {d.get(\"signal\")} ctc={d.get(\"cost_to_close\")}")
    elif e == "tick_completed" and d.get("halt_active"):
        print(f"{ts}  *** HALT ACTIVE ***")
    elif e in LOUD:
        keep = {k: v for k, v in d.items() if k in ("underlying","credit","qty","width","limit_price","error","level","position_id")}
        print(f"{ts}  {e.upper()}  {json.dumps(keep)}")
'
      seen=$n
    fi
  fi
  [ "$(now_et '%H%M')" -ge 1052 ] && break
  sleep 60
done
echo "=== FINAL ENTRY WINDOW CLOSED ($(now_et '%H:%M') ET). No further entries this hackathon. ==="
printf '%s\n' "$j" | grep -E '"event": *"(entry_filled|exit_evaluated|tick_completed)"' | tail -4
