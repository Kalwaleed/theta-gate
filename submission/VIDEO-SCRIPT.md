# Video script — 4:10 target

Max 5 minutes; **the rubric penalises under 3**, so 4:10 leaves room to breathe
without risking the ceiling. Word counts assume ~150 wpm — comfortable narration,
not rushed. Read it aloud once with a timer before recording; if you land under
3:30, slow down rather than adding material.

**Record Wednesday.** Everything except §5 works without final numbers, and Thursday
already holds the flatten, the deck fill-in, the write-up and the repo flip. Do not
leave this to Thursday.

**Placeholders** `[P&L]` `[n]` `[%]` `[s]` are the same tokens as the deck and the
write-up — fill all three from `python store.py --summary` in one pass.

---

## 0:00–0:35 · The tension (85 words)

> Alpaca shipped their paper-trading skills on the 25th of August. Their own guidance
> requires a human confirmation before every order — and five operations demand it
> regardless of the unattended-mode setting.
>
> This hackathon asks for an autonomous agent. Those two things are incompatible. A cron
> job at 10:30 on a Tuesday has nobody to ask.
>
> So the question this project answers isn't "can an LLM trade options." It's: **what do
> you replace the human's approval with, when there is no human?**

*On screen:* the five forbidden operations, then the hackathon's "autonomous agents"
requirement beside them.

## 0:35–1:15 · The answer (95 words)

> A confirmation is really two things wearing one name. **Legibility** — showing what is
> about to happen. And **authority** — deciding whether it may.
>
> Alpaca automates away the authority whenever a human is absent, and replaces it with an
> assertion that fails closed. Theta Gate does the same thing, with twenty-one assertions
> instead of one.
>
> The model proposes a direction. Deterministic Python does everything else — every
> strike, every price, every exit. A pure-function risk guard has the last word, and it
> cannot be argued with.

*On screen:* the architecture diagram from `docs/diagrams/architecture.html`. Hold on
the dashed `brain.py` box.

## 1:15–2:05 · The boundary, in code (120 words)

> This is the whole LLM boundary.
>
> `tools` — empty. `allowed_tools` — empty. `mcp_servers` — empty.
> `strict_mcp_config` — true. `setting_sources` — empty. One turn.
>
> Not a read-only allowlist. An allowlist still holds a network client, and still depends
> on someone maintaining it correctly forever. This can't reach anything at all — and
> `strict_mcp_config` means a stray config file in the working directory can't quietly
> re-arm it.
>
> The model sees the same market numbers the gates already computed. No chain. No news.
> No broker credential. It returns five fields: underlying, direction, confidence,
> thesis, invalidation.
>
> It never picks a strike. Never sets a price. Never holds a credential.
>
> The breach isn't forbidden. It's **unreachable** — and there's a test that fails if
> anyone widens it.

*On screen:* `brain.py` lines 235–244 on screen, then the test that pins them.

## 2:05–2:50 · The guard doing its job, live (105 words)

> Monday, 10:33 Eastern. The model proposes SPY. Every gate passes. The agent fills a
> put credit spread at sixty-one cents — nine and a half seconds, at the limit.
>
> Nine minutes later it proposes SPY again. Then twice more in the afternoon window.
>
> All three times, pure Python says no. *Concurrent: already at max positions for SPY.*
>
> That's the entire thesis, running live, in a journal the agent committed itself. The
> model asked four times. It got one position. Nobody was watching, and nothing was
> negotiable.

*On screen:* the real journal lines, timestamped. Then the dashboard's "why no trade"
panel counting the vetoes by gate.

## 2:50–3:30 · What live testing corrected (95 words)

> Three things in the original plan read fine and were wrong.
>
> The credit gate would have vetoed every single trade — we specified a fixed band, and
> the real relationship is credit over width ≈ 0.8 times the short delta.
>
> Margin held is the full width — five hundred dollars on a five-wide spread — not the
> max loss of four-forty-three. Two different numbers.
>
> And the Alpaca CLI writes API errors to **stderr**. That one silently killed every
> order path until we found it.
>
> Each of those came from running the thing, not from reading about it.

*On screen:* the three corrections as text; the live probe's fill confirmation.

## 3:30–4:10 · Results, and what they don't show (110 words)

> Realised P&L: **[P&L]**. **[n]** trades, across **[s]** sessions.
>
> That is not enough to demonstrate edge, and we're not going to claim it is. At a
> nineteen-delta short strike, the breakeven win rate is 88% against a risk-neutral 80%.
> It needs about eight points of variance risk premium just to break even — and six
> sessions cannot measure eight points of anything.
>
> What it does show is that the guard held. Which gates fired, how often, and that no
> order was ever placed outside them. That loss was capped by construction at entry — a
> dropped cron run couldn't exceed it. And that every decision is reconstructable from a
> hash-chained journal the agent wrote itself.
>
> That's the number worth judging. And unlike edge, it's measurable at this sample size.

*On screen:* the live dashboard — equity curve, positions, "why no trade", then
`governance.json` beside the line *"no LLM can write to this file."*

---

## Production notes

- **Screen recording, voice-over.** No talking head — the artifacts are the story.
- **Show the real dashboard**, not slides of it. It's the hosted demo URL and judges
  will open it anyway; let the video be the tour.
- **Nothing fabricated.** Every number on screen comes from `data/journal.jsonl`. If a
  panel is empty because nothing happened, show it empty and say why — the "why no
  trade" panel is *more* persuasive than a P&L number here.
- **Total: ~610 words ≈ 4:05 at 150 wpm.** Timing check before the first take.
