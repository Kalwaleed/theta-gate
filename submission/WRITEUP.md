# Theta Gate — one-page write-up

**An autonomous options agent that cannot place a trade it should not.**
Alpaca paper account `7a013821-9249-4505-8025-fb298f0931a5` · $100,000 ·
every order placed by the agent, none by a human.

---

## The problem this solves

Alpaca shipped their paper-trading skills on 25 August. Their own guidance requires
**human confirmation before every order**, and five operations demand it *regardless*
of the unattended-mode setting: `cancel_all_orders`, `close_all_positions`,
`close_position`, `exercise_options_position`, `do_not_exercise_options_position`.

That is fundamentally incompatible with the autonomous agent this hackathon asks for.
A cron at 10:30 on a Tuesday has nobody to ask.

Their docs say why they demand it: *"Every deployed path asserts paper at startup…
There is no operator watching to catch a wrong endpoint, and a live account returns
the same response shape as a paper one."*

**Our answer:** a confirmation is two things wearing one name — *legibility* (showing
what is about to happen) and *authority* (deciding whether it may). Alpaca automates
away the second whenever a human is absent and replaces it with an assertion that
fails closed. Theta Gate does the same, with **21 assertions instead of one**.

## AI logic

One bounded model call per entry window. `brain.py` runs Claude Opus 5 with:

```python
ClaudeAgentOptions(system_prompt=…, model=…, max_turns=1,
                   tools=[], allowed_tools=[], mcp_servers={},
                   strict_mcp_config=True, setting_sources=[])
```

Zero tools. Zero MCP servers. One turn. No filesystem, user or project settings. It
sees only the scalar market numbers already computed for the gates — no chain, no
news, no broker credential — and may return exactly five fields: `underlying`,
`direction`, `confidence`, `thesis`, `invalidation`.

**Why no tools rather than a read-only allowlist:** an allowlist still holds a network
client and still depends on being maintained correctly forever. `tools=[]` cannot reach
anything, and `strict_mcp_config=True` means a stray `.mcp.json` in the working
directory cannot quietly re-arm it. The breach is *unreachable*, not merely forbidden
by a prompt — and a test asserts it, because a read-only tool added here would
otherwise break nothing else in the repo.

Any failure — malformed JSON, schema violation, timeout, or a thesis that reads back
an injected instruction — produces no proposal and never an exception. Exit and
reconciliation logic keeps running.

**What the model does not do:** pick a strike, choose an expiry, set a price, size a
position, or hold a credential. `resolve_direction` is an explicit assertion, not an
accident of code that never constructs the other case: a bearish proposal is NO_TRADE,
never a call-side substitution.

## Risk gates

`risk.py` is pure functions — no I/O, no network, `now` injected by the caller. That
is what makes it unit-testable and what makes it the only component in the system
holding a real decision. **First rejection wins and is final.** No gate is re-evaluated
after a veto, and no model call sits downstream of one.

| Group | Gates |
|---|---|
| Environment | paper asserted before *every* order; kill-switch file; account status; options level ≥ 3 |
| Regime *(entry-only — never blocks an exit)* | VIX < 30; VIX9D < VIX3M; \|intraday move\| < 2%; FOMC/CPI/PCE/NFP blackout |
| Contract | both legs need delta *and* IV (the 0DTE guard — structural, not a date check); DTE window; short leg 0.16–0.25 delta; quote age ≤ 60s; spread ≤ 15% of mid |
| Price | credit within ±40% of 0.8 × short delta; absolute floor 10% of width; ATM IV − realised vol ≥ 1.0 point |
| Exposure | max loss per trade; total open risk; ≤ 2 concurrent, ≤ 1 per underlying; buying power ≥ $25,000 *and* ≥ 5× max loss |
| Drawdown | −1% on the day → no new entries; equity ≤ $98,000 → HALT and close out |

Every number lives in `governance.json`, rendered verbatim on the dashboard beside the
line *"no LLM can write to this file"*. No LLM does — `brain.py` cannot import
`alpaca.py`, `store.py` or `loop.py`, and a test walks its AST to prove it.

## Alpaca infrastructure

**The CLI is the integration.** Every broker call shells out through `alpaca.py`:
`clock`, `account get`, `position list`, `data option chain`, `data stock-bars`,
`data latest-quote`, `order get`/`get-by-client-id`/`list`/`cancel`, and
`order submit --order-class mleg` for the two-leg vertical. `alpaca-py` is excluded
from `requirements.txt` on purpose.

**Durability without a database.** The canonical design called for Postgres with
row-level security, six credentialed roles, OIDC attestation and fenced distributed
leases. We cut it, on the record, and said why. What replaced it:

- **Idempotency from the broker.** A deterministic `client_order_id` per order, always
  looked up before submitting. Verified live: Alpaca rejects a resubmitted duplicate
  with 422 rather than creating a second order — that single fact is the whole mechanism.
- **The broker is the source of truth**, refetched every tick, never trusted from a
  prior tick's memory.
- **An append-only JSONL journal**, written *before* the network call that might submit,
  git-committed every tick. A SQLite read model replays it with a SHA-256 hash chain,
  so an edited history is detectable.

**Three things live testing corrected**, each a plan that read fine and was wrong:
the original credit gate (0.20–0.45 of width) would have vetoed *every* trade — the real
relationship is credit/width ≈ 0.8 × short delta; margin held is the full **width**
($500 on a $5 spread), not the max loss ($443); and the CLI writes API errors to
**stderr**, which silently killed every submit path until it was found.

## Results

Realised P&L **[P&L]** · **[n]** trades · win rate **[%]** · max drawdown **[%]**
across **[s]** sessions.

**What [n] trades cannot show:** that this strategy has edge. At −0.197 delta the
breakeven win rate is 88% against a risk-neutral 80% — it needs roughly eight points of
variance risk premium just to break even, and six sessions cannot measure that. Sweeping
every strike from 0.15 to 0.45 delta across five widths, expected value is negative in
every case, by precisely the bid-ask cost. Delta *is* the risk-neutral probability, so a
fairly-priced chain cannot yield edge by arithmetic. The live probe's round trip cost $7.10.

**What it can show:** that the guard held. Which gates fired and how often; that no order
was ever placed outside them; that max loss was capped by construction at entry and a
dropped cron run could not exceed it; and that the whole history is reconstructable from a
committed, hash-chained journal the agent wrote itself.

That is the number worth judging, and it is measurable at n = **[n]**. Edge is not.

## Honest limitations

- **The agent filters; it does not yet select.** All 21 gates answer *should I trade*.
  None answers *what should I trade* — `bullish` and `neutral` both resolve to the same
  put spread. `spread.py` builds call-side verticals already; enabling them needs the
  call chain, which is never fetched. Documented in `docs/STRATEGY-REVIEW-2026-09-01.md`.
- **No automated single-leg repair.** A naked leg HALTs and journals CRITICAL for a human.
  `alpaca.py` has no single-leg option primitive and shipping one untested was the larger risk.
- **Paper fills are optimistic.** Quotes are indicative, not OPRA, and paper fills at the
  limit without an NBBO size check. Measured performance is biased upward and reported as such.
