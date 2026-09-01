# Theta Gate — team brief

**Snapshot as of Tue 1 Sep 2026, 12:50 ET.** This file is *regenerated*, never appended —
it is always the current state and nothing else. For the running history and the reasoning
behind any decision below, read `docs/STATUS.md`.

**Submission closes Fri 4 Sep, 11:00 ET.**

---

## The book right now

| Position | Structure | Qty | Credit | Mark | Unrealised |
|---|---|---|---|---|---|
| `tg-e-20260831-1030-spy` | SPY 754/749P, exp 9 Sep | 1 | $0.61 | 0.86 | **−$25** |
| `tg-e-20260901-1030-qqq` | QQQ 699/694P, exp 4 Sep | 2 | $0.59 | 0.75 | **−$32** |

**Total unrealised −$57 on a $100,000 account (−0.06%).** Both moved against us through
Tuesday morning; both still read `hold`. Stops sit at a 2× closing debit — SPY at 1.22,
QQQ at 1.18 — so neither is close. The −1% daily drawdown halt is $1,000 away.

Book is at capacity: 2 concurrent positions, 1 per underlying. **No further entry is
possible today.** `HALT.json` inactive, no orphans, every tick green.

## Repo

`main` at `c421c1e` · **0 open PRs** · **309 tests passing** · repo still PRIVATE
(flips public Thu 3 Sep 17:00 ET, automated).

## Live configuration — do not change without saying so here

| | |
|---|---|
| Structure | $5 wide, 3–5 DTE, short delta 0.16–0.25, **2 contracts** |
| Risk | $1,000 max loss per trade · $3,000 total open risk · 2 concurrent · 1 per underlying |
| Halt | −1% on the day, or equity ≤ $98,000 → no new entries (neither closes a position) |
| Deadlines | last entry **Wed 2 Sep 10:45 ET** · force-close **Thu 3 Sep from 14:30 ET** |

## Decisions closed this week — please do not reopen these

| Decision | Outcome |
|---|---|
| `fixed_quantity` 1 → 2 | **Done** (`ac714be`), with partial-fill handling on every order path |
| Read-only MCP reconciliation | **Done** (`f810d95`), cron 16:05 ET, runner-verified |
| Tenor 6–9 → 3–5 DTE | **Done** (`2f0472f`). Credit turned out tenor-invariant, so this is free decay capture |
| Aggressive sizing (33 contracts, −6% halt) | **Rejected.** Caps required a $0.556 credit the shorter tenor does not pay |
| Confidence-based sizing | **Rejected.** The model returned 0.60, 0.60, 0.60, 0.62 — a constant carries no signal |
| `width_dollars` 5 → 2 | **Rejected.** See below — this one was studied hard and is closed |

### Why width stays at $5

208 quote observations across four widths and two tenors, then five independent agent
reviews. Two findings decide it:

1. **Bid-ask cost is flat in dollars across widths** — SPY $2.15–$2.38 per contract from
   $1 wide to $5 wide — while credit scales with width ($28.77 at $1 vs $115.69 at $5, at
   qty 2). The "$2 is 20% better" figure came from a ratio that divides by width, i.e. by
   margin. It measured margin efficiency and was read as return. With quantity pinned at 2,
   narrowing just collects less money, and P&L is judged in dollars.
2. **It could not have been applied anyway.** `loop.py:71` hardcodes
   `ENTRY_CONCESSION_FLOOR_DOLLARS = 0.50`. Below about $4.6 of width the entry ladder's
   second rung asks for *more* credit than the first and can never fill. Today's only fill
   came from that rung.

## Known issues, none blocking

- **`ENTRY_CONCESSION_FLOOR_DOLLARS` is an absolute $0.50**, so `width_dollars` is not
  really a single governance value. Fix after the deadline, not before.
- **`gate_credit_quality` headroom is thin at $5** — about 8 points from its 40% deviation
  limit, against ~26 at $2. **This is the one live risk at Wednesday's final window:** the
  proposal may self-veto on credit quality and leave us with two trades instead of three.
  That would be the gate working correctly, not a fault.
- **The deck is stale on at least two counts** and needs a correction pass before Thursday.

## What happens next

| When | What | Owner |
|---|---|---|
| Wed 2 Sep 10:30 ET | **Final entry window.** Watch for a credit-quality veto | agent, watched |
| Wed 2 Sep 10:45 ET | Entries close permanently | — |
| Thu 3 Sep 14:30 ET | Force-close ladder runs; book must end flat | agent |
| Thu 3 Sep, after flat | Deck stats, write-up Results numbers, social post 06 — all from the same source, in one sitting | PK + team |
| Thu 3 Sep 17:00 ET | Repo flips public (automated) | — |
| Fri 4 Sep 11:00 ET | **Submission closes** | PK |

## Still outstanding

- **Video** — not recorded. Shot list and spoken script ready at `submission/VIDEO-SCRIPT.md`;
  shots 1–7 are recordable now, shot 8 needs Thursday's flat book.
- **Demo URL** — no deploy config exists. Plan is a screen recording as the floor, with a
  Streamlit deploy after Thursday's public flip if time allows.
- **Social** — 0 of 5 eligible posts. Post 01 went out 27 Aug, a day before the 28 Aug
  11:00 ET kick-off, so it is outside the window and must not be submitted. Five drafts sit
  in `social/drafts/02-06`; PK posts, the agent never does.
- **Results placeholders** in `submission/WRITEUP.md` — filled Thursday.

## Corrections to figures circulated earlier this week

- Slippage on Tuesday's fill was **6.35%**, not 2.5%. The first number compared the fill to
  the ladder's second rung rather than to the mid actually requested.
- "No gate vetoed across 208 samples" covers only the **2 credit gates** the sampler runs,
  not all 15.
- Social is **0 of 5** eligible, not 1 of 5.

## Where things live

| | |
|---|---|
| `submission/WRITEUP.md` | The required one-page write-up — judge-facing |
| `submission/VIDEO-SCRIPT.md` | Shot list and spoken script |
| `docs/STATUS.md` | Rolling history and the reasoning behind every decision above |
| `docs/STRATEGY-REVIEW-2026-09-01.md` | Why the agent filters but does not select |
| `docs/ANALYSIS-2026-08-30.md` | Sunday's full audit |
| `governance.json` | Every threshold. No LLM can write to it |
