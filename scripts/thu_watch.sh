#!/bin/bash
# Thursday 3 Sep: the force-close ladder. 14:30 -> 15:00 -> 15:30 -> 15:45 ET,
# and the book must end flat before Friday's 11:00 submission. That code path has
# never executed live -- exit_intent 0, exit_filled 0, force_close_unresolved 0
# across every session to date. So this watches every rung, reports a MISSING
# tick as loudly as a bad one, and shouts if the book is not flat with time left
# to close by hand.
cd /Users/papasmurf/Documents/Code_Projects/ClaudeCode/Projects/Alpaca_AI_Trading_Agent
TARGET=0903   # Thu 3 Sep
J="${TMPDIR:-/tmp}/thu_journal.jsonl"
now_et() { TZ=America/New_York date "+$1"; }
# The agent journals from GitHub Actions, so the remote is the source of truth.
pull() { git fetch -q origin main 2>/dev/null; git show FETCH_HEAD:data/journal.jsonl > "$J" 2>/dev/null; }
jw() { env PYTHONPATH=. .venv/bin/python3 scripts/journal_watch.py --journal "$J" "$@"; }

# 1. sleep until five minutes before the first rung
while :; do
  d=$(now_et '%m%d'); t=$(now_et '%H%M')
  [ "$d" = "$TARGET" ] && [ "$t" -ge 1425 ] && break
  [ "$d" -gt "$TARGET" ] && { echo "MISSED: it is already past Thu 3 Sep -- re-arm manually"; exit 1; }
  sleep 300
done
pull
echo "=== THU 3 SEP $(now_et '%H:%M') ET -- ladder at 14:30 / 15:00 / 15:30 / 15:45. The book must end flat. ==="
echo "--- the book going into the ladder ---"
jw --flat || true
seq=$(jw --since 0 | sed -n 's/^SEQ=//p')

# 2. every rung, every decision-log row, until 15:51
rungs_done=""
# Two tiers, because Actions cron drift is normal here and a watcher that
# cries wolf on every rung is worse than none. Measured 31 Aug - 2 Sep: the
# 14:30 rung ran +5..+15m late, 15:00 +8..+12m, 15:30 +1..+7m, 15:45 +0..+4m.
# So a quiet note at +6m, and a real alarm only past the observed envelope --
# still inside the 30-minute rung spacing, with time to dispatch by hand.
check_rung() {          # $1 = rung HHMM, $2 = "note" or "alarm"
  case " $rungs_done " in *" $1:$2 "*) return;; esac
  rungs_done="$rungs_done $1:$2"
  lt=$(jw --last-tick)
  ltt=$(printf '%s' "$lt" | cut -c12-16 | tr -d ':')
  if [ -n "$ltt" ] && [ "$ltt" -ge "$1" ]; then
    late=$(( (ltt/100*60 + ltt%100) - ($1/100*60 + $1%100) ))
    echo "    rung $1: tick landed $lt  (+${late}m)"
    rungs_done="$rungs_done $1:note $1:alarm"   # settled, skip the other tier
  elif [ "$2" = "alarm" ]; then
    echo "!!! RUNG $1: STILL NO TICK past the observed drift envelope -- cron did not fire."
    echo "!!! Last tick: ${lt:-none}.  Dispatch by hand:  gh workflow run agent.yml"
  else
    echo "    rung $1: no tick yet (normal so far -- this rung has run up to +15m late)"
  fi
}
while :; do
  pull
  if [ -s "$J" ]; then
    out=$(jw --since "$seq")
    printf '%s\n' "$out" | grep -v '^SEQ='
    new=$(printf '%s\n' "$out" | sed -n 's/^SEQ=//p'); [ -n "$new" ] && seq=$new
    printf '%s\n' "$out" | grep -q FORCE_CLOSE_UNRESOLVED && \
      echo "!!! FORCE_CLOSE_UNRESOLVED -- final rung, position still open, no order placed. INTERVENE. !!!"
  fi
  t=$(now_et '%H%M')
  for r in 1430:1436:note 1430:1447:alarm 1500:1506:note 1500:1517:alarm \
           1530:1536:note 1530:1544:alarm 1545:1550:note 1545:1554:alarm; do
    rung=${r%%:*}; rest=${r#*:}; deadline=${rest%%:*}; tier=${rest##*:}
    [ "$t" -ge "$deadline" ] && check_rung "$rung" "$tier"
  done
  [ "$t" -ge 1555 ] && break
  sleep 60
done

# 3. the flat check, with ~9 minutes left before the 16:00 close
echo "=== $(now_et '%H:%M') ET -- FLAT CHECK ==="
if jw --flat; then
  echo "*** BOOK IS FLAT. ***"
else
  echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo "!!! BOOK IS NOT FLAT AT $(now_et '%H:%M') ET -- CLOSE BY HAND BEFORE 16:00 !!!"
  echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
fi

# 4. the deck numbers, once the session is closed. Print only -- the deck is
#    filled by hand, in one sitting, from one source.
while [ "$(now_et '%H%M')" -lt 1605 ]; do sleep 60; done
pull
echo "=== $(now_et '%H:%M') ET -- DECK STATS (the four PLACEHOLDER lines) ==="
jw --stats

# 5. the public flip
while [ "$(now_et '%H%M')" -lt 1705 ]; do sleep 300; done
echo "=== $(now_et '%H:%M') ET -- PUBLIC FLIP CHECK ==="
priv=$(gh api repos/Kalwaleed/theta-gate --jq .private 2>&1)
if [ "$priv" = "false" ]; then echo "repo is PUBLIC"; else echo "!!! repo private=$priv -- the flip did not happen"; fi
gh run list --workflow=go-public.yml -L 1 2>&1
