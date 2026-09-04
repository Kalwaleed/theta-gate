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

Two generated cards bookend real screen capture. **Nothing generated may stand in
for the agent working.** Judging asks to see the agent in action; synthetic footage
of a fabricated terminal would be the one dishonest frame in an entry whose whole
argument is that it does not overclaim. These are a title card and an outro. Nothing
more.

**Palette is fixed by the deck** (`deck/theta-gate.tex:33-40`) — match it or the cut
to the slides will jar:

| Role | Hex | Where it appears in the scene |
|---|---|---|
| Ink (ground) | `#0B0D0F` | Crushed blacks, the room |
| Accent | `#3F2AC1` KBW Violet | The cursor. The ONLY saturated colour in frame |
| Muted | `#5B5B5B` | Desk, chair, monitor bezels |
| Paper | `#F5F5F5` | Title type, Scene B daylight |

**No amber, no orange, no warm tones anywhere.** The room must read cold and
unattended. Warmth implies a person was recently there, which argues against the
thesis.

---

### SCENE A — cold open · 6 seconds · 0:00–0:06

**Paste this as the prompt:**

> Locked-off cinematic wide shot of an empty financial trading desk before dawn,
> photographed from directly behind an unoccupied ergonomic chair. Three large
> monitors arranged in a shallow arc across the upper two-thirds of frame; the two
> outer monitors are fully dark, the centre monitor shows a black terminal with a
> single small violet rectangular cursor blinking slowly. The chair back is a soft
> dark mass occupying the lower-left third, out of focus in the foreground. A thin
> shaft of cold pre-dawn light enters from a window off-frame left, raking across
> the desk surface and catching slow-drifting dust motes in the air. Deep shadows,
> almost no fill light. The desk is bare — no papers, no cup, no phone. Extremely
> slow push-in, roughly four percent over the shot. Shot on 35mm spherical, T2.8,
> shallow depth of field, focus held on the centre monitor's cursor. Cold desaturated
> grade, crushed near-black, slate and charcoal only, one violet accent from the
> cursor. Fine 35mm grain, gentle halation around the cursor glow. Still, silent,
> unattended. Photorealistic, 4K, 16:9, 24fps.

**Shot specification**

| Parameter | Value | Why |
|---|---|---|
| Lens | 35mm spherical, T2.8 | Wide enough for all three monitors; 35mm keeps the room honest — 24mm would distort and read as a video game |
| Camera height | 1.15 m — seated eye level | Puts the viewer exactly where the absent trader would sit. This is the whole point of the shot |
| Angle | Dead-on, 8–10° off-axis to camera left | Pure symmetry looks artificial; a slight offset reads as a real room |
| Movement | Push-in, ~4% over 6s, linear, slider | Must be barely perceptible. A visible move reads as stock footage |
| Focus | Locked on the centre cursor | No rack focus. A focus pull implies an operator, and there is no operator |
| Duration | 6.0s | Title needs 4s legible; 2s of clean room before it |
| Frame rate | 24fps | Match to the screen capture or the cut will strobe |

**Lighting**

- **Key:** window light, frame left, ~5600K, low intensity, hard-edged shaft. Motivated, with visible atmospheric haze so the beam has body.
- **Practical:** the cursor only. It should glow just enough to bloom slightly.
- **Fill:** almost none. Contrast ratio ~8:1. Let the shadows go to near-black.
- **Forbidden:** overhead office fluorescents, any practical lamp, any screen glow from the dark monitors. A lit room implies occupancy.

**Motion — this is where generators fail**

Only two things move: **the cursor blinks at about 1 Hz**, and **dust drifts in the
light shaft**. Nothing else. No curtain movement, no reflection crawl, no chair
rotation, no monitor flicker. If the generated clip adds motion, regenerate — a
drifting object turns a deliberate shot into stock footage.

**Negative prompt**

```
people, person, human, hands, fingers, face, silhouette, reflection of a person,
readable text, legible code, visible numbers, charts, graphs, candlesticks, logos,
brand marks, warm light, amber, orange, gold, tungsten, sunset, lens flare, bokeh
balls, rack focus, handheld, camera shake, orbit, dolly zoom, crane move, timelapse,
fast motion, neon, cyberpunk, cluttered desk, coffee cup, plant, RGB keyboard
```

**Title treatment, over the last 4s:** lower third, left-aligned to match the deck's
margin. `THETA GATE` in IBM Plex Mono, letter-spaced, `#F5F5F5`. Below it, smaller,
IBM Plex Sans in `#5B5B5B`: *an agent that cannot place a trade it should not.*
Fade the type in over 0.5s. No slide, no typewriter effect.

**Why this shot:** the empty chair is the thesis. Autonomy means nobody is sitting
there at 10:30 on a Tuesday. Say Shot 1's line over it, then **cut hard** — no
dissolve — to the live dashboard. The jump from the empty room to a populated
journal makes the argument before you finish the sentence.

---

### SCENE B — outro · 4 seconds · 2:56–3:00

**Paste this as the prompt:**

> The identical empty trading desk from the identical camera position, now in flat
> overcast midday daylight. All three monitors are switched fully off — dark grey
> matte screens with no glow, no cursor, no image. The chair is still empty and
> unmoved. The desk is still bare. The shaft of light is gone; the room is evenly
> and softly lit, ordinary and unremarkable. No haze, no dust. Completely static
> locked-off camera, absolutely no movement. Shot on 35mm spherical, T4, slightly
> deeper focus than before. Neutral desaturated grade, soft contrast, cool grey and
> charcoal. Fine 35mm grain. Photorealistic, 4K, 16:9, 24fps.

**What changes from Scene A, and what must not**

| | Scene A | Scene B |
|---|---|---|
| Camera position | Identical | **Identical** — this is what makes it land |
| Movement | 4% push-in | **None at all** |
| Light | Hard cold shaft, 8:1 | Flat overcast, ~2:1 |
| Monitors | Centre one live, violet cursor | All off, no glow |
| Aperture | T2.8 | T4 |
| Haze / dust | Yes | None |

Same framing is non-negotiable. If the second shot is even slightly reframed, the
pairing reads as two stock clips instead of one room at two times of day.

**Title, held 3s:** `github.com/Kalwaleed/theta-gate` and below it
`7a013821-9249-4505-8025-fb298f0931a5`, both IBM Plex Mono, `#F5F5F5`, left-aligned
to the same margin. Long enough to read at a comfortable pace — a judge may pause here.

**Why:** you open on an empty room before the market and close on an empty room after
it. Nobody came. That is the claim, made twice, without saying it.

---

### Generating these

**Done 4 Sep 2026.** Both clips are in `submission/video/`: `scene-a.mp4` (6 s, push-in, violet cursor) and `scene-b.mp4` (4 s, static, monitors off, generated from Scene A's first frame so the framing matches). One alternate of each sits beside them. Seedance 2.5, 1920x1080, 24 fps, silent. Titles are not burned in; add them in the edit. The steps below are what produced them.

1. **Generate Scene A first and get it right before attempting B.** B must match A's
   framing, so A is the reference.
2. **Run 4–6 variations.** The failure mode is added motion and invented screen
   content, not composition.
3. **Reject any take with readable text on a monitor.** Invented code or fabricated
   numbers in a submission about auditability is the one own goal you cannot recover
   from. The centre screen is black with a cursor. Nothing else.
4. **Reject any take with a person, a hand, or a human reflection**, however small.
5. **Check the grade against `deck/theta-gate.pdf` side by side** before you cut.
   Violet `#3F2AC1`, never amber.

**If the generated takes look synthetic — and they may — shoot it practically.** A
still photograph of a real empty desk with a 4% digital push-in, graded cold, beats
an obviously artificial clip. The shot is deliberately simple so that a photograph
carries it. Your own desk before sunrise, monitors off, one terminal open, phone on
a tripod, is a legitimate and probably better answer.
