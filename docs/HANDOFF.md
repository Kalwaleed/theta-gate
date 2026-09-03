# HANDOFF — Friday 4 Sep 2026

**One-shot document. Read it, act on it, delete it.** Rolling state lives in
`docs/STATUS.md`. Written Thu 3 Sep 16:00 ET / 23:00 Riyadh.

---

## The clock

**Submission closes Fri 4 Sep, 11:00 ET = 18:00 Riyadh.**
Source: `docs/hackathon-rules-2026-08-30.md:9`.

The market opens Fri 09:30 ET — only 90 minutes before the deadline. **Friday
gives you almost nothing new.** Treat everything below as work for your morning,
not your afternoon.

---

## Trading is OVER. Nothing left to do on the agent.

- **Entries closed permanently Wed 2 Sep 10:45 ET.** No new trade is possible.
- **The book is flat.** Broker confirms 0 legs open.
- Both positions closed themselves **09:37 ET Thu 3 Sep on `take_profit`**, five
  hours before the mandatory flatten.

**Final numbers — quote these, they are verified:**

| | |
|---|---|
| Realised P&L | **+$95.00** |
| Trades | **2 placed, 2 closed, 2 wins** |
| Win rate | **100% (2/2)** — meaningless at n=2, and the deck says so |
| Max drawdown | **-0.15%** (peak mark-to-market, -$151 on 1 Sep 14:46) |
| Sessions | 6 (29 Aug – 3 Sep) |
| Broker equity | $100,094.54 (journal says $100,095.00 — $0.46 is fees) |

**The force-close ladder never ran.** It is tested and was rehearsed against all
four rungs with a simulated clock, but take-profit closed the book first. **Do not
claim it executed.** The journal is public and a judge can check in one grep. Every
artifact has already been corrected to say this — do not let it creep back in.

---

## DONE — do not redo

| Item | Where | Evidence |
|---|---|---|
| Agent, 6 sessions, all orders agent-placed | live | 573 journal events, hash chain intact |
| Repo public | github.com/Kalwaleed/theta-gate | public since 31 Aug |
| Dashboard live | Streamlit | URL in `submission/LABLAB-FORM.md` |
| Tests | 344 passing, CI on every push | `pytest -q` |
| Deck | `deck/theta-gate.pdf` | 13 pages, stats filled, 7:1 footer corrected |
| Cover image | `cover/cover.png` | 105 KB |
| Write-up | `submission/WRITEUP.md` | numbers filled, drawdown defined |
| Form answers | `submission/LABLAB-FORM.md` | every field, ready to paste |
| Video script + 2 scene prompts | `submission/VIDEO-SCRIPT.md` | rewritten, numbers match the journal |
| Social posts 02–05 | posted, in-window | links in `social/README.md` |

---

## LEFT — in this order

### 1. Record the video — the only long pole
`submission/VIDEO-SCRIPT.md` has the full spoken script, 8 shots, 4 commands, and
two generatable scene prompts with camera specs.

**Before Shot 1, run this and say the number it prints:**
```bash
git pull && PYTHONPATH=. .venv/bin/python3 -c "
import json, collections
ev=[json.loads(l) for l in open('data/journal.jsonl')]
print('events:', len(ev), ' ticks:', sum(e['event']=='tick_completed' for e in ev))"
```
**The tick count climbs every 5 minutes the market is open.** It was 173 on Thu
afternoon and will be higher Friday. Shot 1 quotes it. A number that disagrees with
the journal is exactly the error this entry is built to avoid.

Fallback if the generated scene cards look synthetic: photograph your own desk
before sunrise, monitors off, and add a 4% digital push. Said so in the script.

### 2. Post the final social post — full text below, copy it as-is

Verified **275 characters** (X cap is 280), both required tags present. Do not
reword it: the "ladder never fired" line is deliberate and correct, and the numbers
are read from the journal.

**X:**

```
Book is flat. Six autonomous sessions, $100k paper account.

2 trades · 2 closed · +$95 · max drawdown -0.15%

Both closed on take-profit at 09:37 ET, five hours before the flatten. The force-close ladder never fired.

n=2 proves no edge. Posting anyway.

@AlpacaHQ @lablabai
```

**LinkedIn:** (add the repo link at the end — `https://github.com/Kalwaleed/theta-gate`)

```
Theta Gate is flat. Final results from my Alpaca AI Trading Agents Hackathon entry with lablab.ai.

Six sessions on a fresh $100,000 paper account. 2 trades placed, 2 closed, realised P&L +$95, maximum drawdown -0.15%.

Both positions closed themselves at 09:37 ET this morning on the agent's take-profit rule — 50% of credit captured — five hours before Thursday's mandatory flatten deadline. No human placed or closed an order all week.

Worth being precise about one thing, because the journal is public and anyone can check it: the four-rung force-close ladder I built for Thursday afternoon never executed. It is tested, and it was rehearsed against all four rungs, but the take-profit rule got there first. I am not going to describe a code path as proven when it has never run live.

What I will not claim: that 2 trades says anything about edge. It does not. A variance risk premium strategy needs hundreds of samples before the number outruns the noise around it. Max drawdown is peak mark-to-market, not the flattering realised-only figure that would have read 0.0%.

What six sessions do show is whether the machinery holds — whether every refusal was logged with a reason, whether the kill switch stayed reachable, whether a multi-leg order ever left a naked leg. Those are answerable at this sample size. Edge is not.

Full write-up and the repository are linked below.

#AlpacaHackathon #BuildInPublic
```

Then paste the resulting URL into `social/README.md` and into the form. That gets
you to **5 of 5 eligible**, because post 01 does not count.

### 3. Fill the lablab.ai form
Everything is in `submission/LABLAB-FORM.md`. Paste it.

**SUBMIT POSTS 02–06. DO NOT SUBMIT POST 01.** It published 27 Aug 03:37 ET, 31
hours before the 28 Aug 11:00 ET kick-off — decoded from its X snowflake ID, and it
matches the date recorded by hand. Submitting it spends one of five slots on a post
that cannot score.

### 4. Submit with hours to spare, not minutes
Uploads fail. A deadline in a foreign timezone is where people lose an entry they
had already won.

---

## Traps that have already bitten once

1. **`make` skips a rebuild when the PDF and `.tex` share an mtime.** A stale PDF
   with the old 4:1 line was committed once. If you touch `deck/theta-gate.tex`,
   run `cd deck && make distclean && make`, then confirm `git status` shows the PDF
   as modified.
2. **`scripts/fill_results.py` writes into both a `.md` and a `.tex`.** LaTeX
   escaping is fixed now, but if you re-run it, **build the deck before trusting
   it** — an unescaped `%` silently truncated the PDF to 9 pages once.
3. **The agent commits to `main` every ~5 minutes while the market is open.** Your
   push will need `git pull --rebase`. This is normal.
4. **`alpaca` profiles `paper` and `submission` are the SAME account**
   (`7a013821-…`). There is no sandbox. Any broker write hits the competition
   account.
5. **The Thursday watcher dies with that session and does not need re-arming.**
   The book is flat and entries are closed; it has nothing left to watch.

---

## Verify before trusting any of this

```bash
git log --oneline -5
.venv/bin/python3 -m pytest -q                       # expect 344
PYTHONPATH=. .venv/bin/python3 scripts/journal_watch.py --flat   # expect FLAT
gh api repos/Kalwaleed/theta-gate --jq .private      # expect false
cd deck && make check                                # expect a clean build
```

If this file disagrees with the repo, **the repo is right.**
