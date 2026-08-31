# Demo + video — shot list and spoken script

**Target 3:00.** lablab publishes no length limit on the archived rules page,
so short is the safe read. Everything below is recordable **before** Thursday
except Shot 8, which needs the flat book.

## Before you hit record

**Never on camera:** `.env`, `env.example` filled in, `alpaca doctor` output,
GitHub secrets pages, any terminal where you have just pasted a key. The
Alpaca **account ID is fine** — the submission requires it.

```bash
cd /Users/papasmurf/Documents/Code_Projects/ClaudeCode/Projects/Alpaca_AI_Trading_Agent
set -a; source .env; set +a          # do this BEFORE recording, off camera
.venv/bin/python3 -m streamlit run app.py    # leave running in a second window
```

Terminal at ~120x35, font large enough to read at 720p. One browser tab on the
dashboard, one on the GitHub Actions runs list. Close everything else.

## The spine

Every competitor in this hackathon claims deterministic risk gates — BABIL and
SPY Sentinel both say it in their one-liners. **Do not describe the
architecture. Show the refusals.** Anyone can claim gates. We can show a
journal that logged 46 declines and one trade.

---

## Shot list

| # | Time | On screen | Say |
|---|---|---|---|
| 1 | 0:00–0:18 | Dashboard, open SPY position | "This agent traded once today. It ran 46 times and declined 45 of them. That ratio is the product." |
| 2 | 0:18–0:45 | `docs/WRITEUP.md`, thesis paragraph | "Before writing strategy code I priced a real spread on Alpaca. Expected value was negative by almost exactly the bid-ask. A fair chain hands you nothing. So the agent claims one edge and names it — the variance risk premium — and refuses to trade when it is absent." |
| 3 | 0:45–1:12 | `brain.py` lines 1–12 | "One model call per tick. It picks a ticker and a direction. It cannot pick a strike, a size, a price, or a threshold. No tools, no filesystem, no broker credential. If it returns malformed JSON or a prompt injection, the answer is the same: no proposal, never a crash." |
| 4 | 1:12–1:45 | Command A below | "Here is today's decision log. Four proposals, one fill. Twice the model proposed SPY and its own risk layer blocked the order — already at max positions for that underlying. The model does not get to argue." |
| 5 | 1:45–2:05 | Command B | "The order that did fill. Both legs at the same broker timestamp, so there is never a naked leg. Negative price means credit — that is Alpaca's convention and we verified it against the raw order, not our own log." |
| 6 | 2:05–2:30 | Command C | "A second scheduled job reconciles the broker's own view against our journal over Alpaca's MCP server. Two read tools allowed, all ten write tools denied by name. It cannot place an order. The thing that verifies the books is not the thing that writes them." |
| 7 | 2:30–2:58 | Command D | "Thursday the book must be flat. That path is mandatory and had never run, so the agent can rehearse it against a fabricated clock. Watch — it is Monday, it thinks it is Thursday afternoon, and it picks the first rung of the force-close ladder on the real open position. Dry run, sandboxed journal, the real audit trail untouched." |
| 8 | 2:58–3:15 | **Thursday only** — dashboard, flat | "Book is flat. Every position closed by the agent's own ladder, not by hand. [N] trades, [P&L]. Too small a sample to prove edge — and the write-up says so." |

---

## Commands, in order

Run each fresh so the screen is clean. Output is verified as of 31 Aug.

**A — the refusals (Shot 4)**

```bash
.venv/bin/python3 - <<'PY'
import json, collections
ev = [json.loads(l) for l in open('data/journal.jsonl')]
today = [e for e in ev if e['ts'].startswith('2026-08-31')]
print(collections.Counter(e['event'] for e in today))
for e in today:
    if e['event'] == 'no_trade' and e.get('reason') != 'outside_entry_window':
        print(e['ts'][11:19], e['reason'])
PY
```

**B — the fill (Shot 5)**

```bash
.venv/bin/python3 -c "
import json
for l in open('data/journal.jsonl'):
    d = json.loads(l)
    if d['event'] == 'entry_filled': print(json.dumps(d, indent=2))"
```

**C — MCP reconciliation (Shot 6)**

```bash
sed -n '45,64p' scripts/mcp_reconcile.py     # the allow / deny lists
.venv/bin/python3 -c "
import json
for l in open('data/journal.jsonl'):
    d = json.loads(l)
    if d['event'] == 'mcp_reconciliation': print(json.dumps(d, indent=2))" | tail -20
```

**D — force-close rehearsal (Shot 7) — the money shot**

```bash
.venv/bin/python3 loop.py --once --dry-run --as-of "2026-09-03T14:30:00" --profile submission
```

Verified output on 31 Aug: banner naming the sandboxed journal and HALT file,
then `"signal": "force_close: past the flatten deadline"`, `"rung":
"force09031430"`, `"git": {"skipped": "rehearsal"}`. Takes a few seconds —
do not cut, the pause is the point.

---

## Thursday insert

After the 14:30 ET ladder completes and the book is confirmed flat:

1. Re-record Shot 8 only.
2. Refresh the deck's four `\PLACEHOLDER` stats (`deck/theta-gate.tex:422-425`).
3. Fill the bracketed numbers in `social/drafts/06-results-and-flat.md`.

All three read from the same source, so do them in one sitting and they cannot
disagree.

## If a shot fails on camera

Shot 7 is the only one that touches the network. If it errors, the fallback is
`.venv/bin/python3 -m pytest -q test_loop.py -k force_close -v` — the same four
rungs, covered by name. Less dramatic, still true.
