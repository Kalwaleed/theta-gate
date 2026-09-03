# Video — script, shot list, and the scene

**Target 3:00.** Our archived rules (`docs/hackathon-rules-2026-08-30.md`) list
"Video presentation" as a submission field and state **no duration rule** — no cap,
no minimum. So this stays short rather than padding.

**Rewritten 3 Sep 2026.** The previous version claimed "46 runs, declined 45" and
"every position closed by the agent's own ladder." Both were wrong. Every number
below is read from the live journal, and the ladder never fired — take-profit
closed the book first. Judging includes a public repo; a claim the journal
contradicts is worse than no claim.

## The spine

Every competitor claims deterministic risk gates. **Do not describe the
architecture — show the refusals, then show the one number that proves the
refusals were real.** Anyone can say "guardrails." Few can show a hash-chained
journal where the model asked and the risk layer said no.

## Before you hit record

**Never on camera:** `.env`, a filled-in `env.example`, `alpaca doctor` output,
GitHub secrets pages, any terminal where a key was just pasted. The **Alpaca
account ID is fine** — the submission requires it.

```bash
cd /Users/papasmurf/Documents/Code_Projects/ClaudeCode/Projects/Alpaca_AI_Trading_Agent
set -a; source .env; set +a                    # off camera, before recording
.venv/bin/python3 -m streamlit run app.py      # leave running in a second window
```

Terminal ~120x35, font readable at 720p. One browser tab on the dashboard, one on
the GitHub Actions runs list. Close everything else. Do not resize mid-take.

---

## Shot list

| # | Time | On screen | Say |
|---|---|---|---|
| 1 | 0:00–0:15 | **Scene A** (below), then hard cut to the dashboard, book flat | "This agent ran [TICKS] times over six sessions and placed two trades. That ratio is the product." <br>**[TICKS] drifts — see the warning below. Run Command A and use what it prints.** |
| 2 | 0:15–0:40 | `submission/WRITEUP.md`, the edge paragraph | "Before I wrote any strategy code I priced real spreads on the live chain. Swept 0.15 to 0.45 delta, expected value came out negative every time — by almost exactly the bid-ask. Delta *is* the risk-neutral probability, so a fairly priced chain hands you nothing. So the agent claims one edge, names it, and refuses to trade when it's absent." |
| 3 | 0:40–1:05 | `brain.py`, the `ClaudeAgentOptions` block | "One model call per entry window. `tools` empty, `mcp_servers` empty, one turn. It picks a direction. It cannot pick a strike, a size, a price, or a threshold, and it holds no broker credential. Prompt-inject it and you get no proposal — never a crash. The breach isn't forbidden, it's unreachable, and a test asserts that." |
| 4 | 1:05–1:35 | **Command A** | "The decision log. Nine proposals, two fills. Seven times the model asked and its own risk layer refused — already at max positions for that underlying. Four more died on the variance-risk-premium gate: the premium wasn't there, so there was no trade to make. The model doesn't get to argue." |
| 5 | 1:35–1:55 | **Command B** | "The order that filled. Both legs, one broker timestamp, so there's never a naked leg. Negative price means credit — Alpaca's convention, verified against the raw order, not against my own log." |
| 6 | 1:55–2:20 | **Command C** | "A second scheduled job reconciles the broker's own view against this journal over Alpaca's MCP server. Two read tools allowed, every write tool denied by name. It cannot place an order. The thing that audits the books isn't the thing that writes them." |
| 7 | 2:20–2:45 | **Command D** | "The final afternoon the book had to be flat. That path is mandatory and had never run — so the agent rehearses it against a fabricated clock. It's Thursday morning, it thinks it's half past two, and it walks the force-close ladder on a real position. Dry run, sandboxed journal, the real audit trail untouched." |
| 8 | 2:45–3:00 | Dashboard, flat; then **Scene B** | "Two trades, plus ninety-five dollars, two for two. And both closed themselves on take-profit at 9:37 — five hours before that ladder was due. So the ladder never fired. It's tested, it's rehearsed, it has never run live, and I'm not going to tell you otherwise. Two trades proves nothing about edge. The refusals are the part that's measurable." |

**Shot 8 is the whole submission.** Every other entry will end on a P&L number.
Ending on *"here is the code path I built that never ran"* is the most credible
fifteen seconds available, and it costs nothing because the journal shows it anyway.

---

## Commands, in order

Run each fresh so the screen is clean. Output verified 3 Sep 2026.

**A — the refusals (Shot 4)**
```bash
PYTHONPATH=. .venv/bin/python3 -c "
import json, collections
ev=[json.loads(l) for l in open('data/journal.jsonl')]
print('events:', len(ev), ' ticks:', sum(e['event']=='tick_completed' for e in ev))
g=collections.Counter(e['reason'].split(':')[0] for e in ev
                      if e['event']=='no_trade' and e.get('reason')!='outside_entry_window')
for k,v in g.most_common(): print(f'{v:3}  {k}')"
```
Expect `7 all_underlyings_at_cap`, `4 vrp_present`, `3 concurrent` — those are
final, entries closed 2 Sep.

> **The tick and event counts are NOT final.** The agent journals every ~5 minutes
> while the market is open, so they climb until 16:00 ET today and again Friday
> 09:30–11:00. They read 571 events / 173 ticks at the time of writing and will be
> higher when you record. **Run `git pull` and then Command A immediately before
> Shot 1, and say the number it prints.** A count that disagrees with the journal
> is exactly the error this submission is built to avoid.

**B — the fill (Shot 5)**
```bash
.venv/bin/python3 -c "
import json
for l in open('data/journal.jsonl'):
    d=json.loads(l)
    if d['event']=='entry_filled': print(json.dumps(d, indent=2))"
```

**C — MCP reconciliation (Shot 6)**
```bash
sed -n '45,64p' scripts/mcp_reconcile.py      # the allow / deny lists
.venv/bin/python3 -c "
import json
for l in open('data/journal.jsonl'):
    d=json.loads(l)
    if d['event']=='mcp_reconciliation': print(json.dumps(d, indent=2))" | tail -20
```

**D — force-close rehearsal (Shot 7) — the money shot**
```bash
.venv/bin/python3 loop.py --dry-run --as-of "2026-09-03T15:00:00" --profile submission
```
Banner names the sandboxed journal and HALT file, then
`"signal": "force_close: past the flatten deadline"`, `"rung": "force09031500"`,
`"git": {"skipped": "rehearsal"}`. Takes a few seconds — **do not cut, the pause is
the point.** The book is flat now, so this walks the ladder and finds nothing to
close; that is honest and worth narrating as such.

**If a shot fails on camera:** Shot 7 is the only one touching the network. Fallback
is `.venv/bin/python3 -m pytest -q -k force_close -v` — the same rungs, covered by
name. Less dramatic, still true.

---

## The scene

Two generated cards, bookending real screen capture. **Nothing generated may stand
in for the agent working** — judging asks to see the agent in action, and synthetic
footage of a fake terminal would be the one dishonest frame in an entry whose entire
argument is that it doesn't overclaim. Keep them to title and outro.

### Scene A — cold open, 0:00–0:06

> A single wide, locked-off shot. Pre-dawn, a trading desk seen from behind: three
> dark monitors, no one present, no chair pulled out. The only light is the cold blue
> of a screensaver and one amber cursor blinking in an otherwise empty terminal.
> Dust hangs in a shaft of early light from a window off-frame left. Nothing moves
> except the cursor. Slow, almost imperceptible push-in. Shallow depth of field,
> the far monitor soft. Muted palette — slate, charcoal, one warm amber accent.
> No people, no hands, no text on screen. 35mm, anamorphic, subtle film grain.
> Silent, or a single low room-tone hum.

Title over it, plain type, lower third: **THETA GATE** — then, smaller,
*an agent that cannot place a trade it should not.*

**Why this shot:** the empty chair *is* the thesis. Autonomy means no one is
sitting there at 10:30 on a Tuesday. Say the first line over it and cut hard to
the live dashboard — the contrast between the empty room and the real, populated
journal does the argument for you.

### Scene B — outro, 2:56–3:00

> The same desk, same angle, now in flat daylight. The monitors are off. The
> terminal is gone. The room is ordinary and still. Hold three seconds. No push,
> no move. Same muted palette, same grain.

Title: the repo URL and the Alpaca account ID, plain, held long enough to read.

**Why:** you opened on an empty room before the market and you close on an empty
room after it. Nobody came. That is the claim.

### If you generate these

- **Locked-off or near-locked-off.** A drifting AI camera reads as stock footage.
- **No people, no hands, no faces.** The moment a person appears the shot argues
  against the thesis.
- **No readable text on the generated screens.** Fake code or fake numbers in a
  submission about auditability is the worst possible own goal. Amber cursor only.
- **Match the deck.** Slate/charcoal ground, one amber accent, IBM Plex for titles.
- 16:9, and match the screen-capture frame rate so the cuts don't jar.
