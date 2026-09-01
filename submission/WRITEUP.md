# Theta Gate

**An autonomous options agent that cannot place a trade it should not.** The model
proposes a direction. Deterministic Python does everything else. A pure-function risk
guard has the last word and cannot be argued with.

Alpaca paper account `7a013821-9249-4505-8025-fb298f0931a5`, $100,000, every order
placed by the agent and none by a human.

Results: **[P&L]** realised across **[n]** trades and **[s]** sessions, win rate **[%]**,
max drawdown **[%]**.

---

## The problem

Alpaca's own paper-trading skills require human confirmation before every order. Five
operations demand it regardless of the unattended-mode setting. That is incompatible with
the autonomous agent this hackathon asks for. A cron job at 10:30 on a Tuesday has nobody
to ask.

A confirmation is two things under one name: *legibility*, showing what is about to
happen, and *authority*, deciding whether it may. Alpaca automates away the authority
when no human is present and replaces it with an assertion that fails closed. Theta Gate
does the same, with 21 assertions instead of one.

## AI logic

**The model has no tools and cannot reach anything.** One bounded call per entry window:

```python
ClaudeAgentOptions(system_prompt=…, model=…, max_turns=1,
                   tools=[], allowed_tools=[], mcp_servers={},
                   strict_mcp_config=True, setting_sources=[])
```

It sees the scalar market numbers already computed for the gates. No chain, no news, no
credential. It returns five fields: `underlying`, `direction`, `confidence`, `thesis`,
`invalidation`.

A read-only allowlist would have been weaker. An allowlist still holds a network client
and depends on someone maintaining it correctly forever. `tools=[]` reaches nothing, and
`strict_mcp_config=True` stops a stray `.mcp.json` re-arming it. A test asserts this,
because widening it would otherwise break nothing else in the repo.

Every failure produces no proposal and no exception: malformed JSON, timeout, or a thesis
that reads back an injected instruction. Exits and reconciliation keep running. The model
never picks a strike, sets a price, sizes a position, or holds a credential.

## Risk gates

**First rejection wins and is final.** No gate is re-evaluated after a veto. No model call
sits downstream of one. `risk.py` is pure functions with no I/O and `now` injected, which
is what makes it testable and what makes it the only component holding a real decision.

| Group | Gates |
|---|---|
| Environment | paper asserted before *every* order; kill switch; account status; options level ≥ 3 |
| Regime *(entry-only, never blocks an exit)* | VIX < 30; VIX9D < VIX3M; \|intraday move\| < 2%; FOMC/CPI/PCE/NFP blackout |
| Contract | both legs need delta *and* IV, which is the 0DTE guard and structural rather than a date check; DTE window; 0.16–0.25 short delta; quote age ≤ 60s; spread ≤ 15% of mid |
| Price | credit within ±40% of 0.8 × short delta; floor at 10% of width; ATM IV − realised vol ≥ 1.0 pt |
| Exposure | max loss per trade; total open risk; ≤ 2 concurrent, ≤ 1 per underlying; buying power ≥ $25k *and* ≥ 5× max loss |
| Drawdown | −1% on the day stops new entries; equity ≤ $98k triggers HALT and close-out |

Every number lives in `governance.json`, rendered verbatim on the dashboard beside the
line *"no LLM can write to this file"*. None does. `brain.py` cannot import the broker,
and a test walks its AST to prove it.

## Alpaca infrastructure

**The CLI is the integration.** Every broker call shells out through `alpaca.py`: `clock`,
`account get`, `position list`, `data option chain`, `stock-bars`, `latest-quote`, the
`order` verbs, and `order submit --order-class mleg` for the two-leg vertical.
`alpaca-py` is excluded from `requirements.txt` deliberately.

**Durability comes from the broker, not a database.** The canonical design called for
Postgres with row-level security, OIDC attestation and fenced leases. We cut it and said
so. Three things replaced it. A deterministic `client_order_id` is looked up before every
submit, verified live: Alpaca rejects a duplicate with 422 rather than creating a second
order, and that fact is the whole mechanism. The broker is the source of truth, refetched
every tick and never carried over. An append-only JSONL journal is written before the
network call that might submit, committed each tick, and replayed into SQLite under a
SHA-256 hash chain so an edited history is detectable.

## What the results show

**They show the guard held. They do not show edge, and we are not claiming it.**

At −0.197 delta the breakeven win rate is 88% against a risk-neutral 80%, so the strategy
needs about eight points of variance risk premium to break even. Six sessions cannot
measure eight points of anything. Swept from 0.15 to 0.45 delta, expected value is
negative in every case by precisely the bid-ask cost, because delta *is* the risk-neutral
probability and a fairly-priced chain cannot yield edge by arithmetic.

What is measurable at n = **[n]**: which gates fired and how often, that no order was
placed outside them, that max loss was capped by construction at entry, and that the whole
history reconstructs from a hash-chained journal the agent wrote itself.

## Disclosures and limitations

- **VRP thresholds were re-based on 30 Aug with Friday's marks in view.** Realised-vol
  window 20 → 10 days, margin 2.0 → 1.0 points, because the 20-day window still carried
  the early-August rally and was vetoing every candidate. Dated reasoning is in
  `governance.json`. It remains a threshold chosen while looking at the data it would be
  applied to.
- **Commit `96fd434`, 1,049 lines, landed 3h40m before kickoff.** The account is fresh and
  every trade is inside the window. The scaffolding was not.
- **Three `mcp_reconciliation_failed` rows sit in the journal at 16:41–16:42 ET on 31 Aug.**
  Development runs made before that job sandboxed its own journal, caught the same hour.
  They stay because the trail is append-only, which is what makes it worth trusting.
- **The agent filters but does not select.** All 21 gates answer *should I trade*. None
  answers *what should I trade*: `bullish` and `neutral` resolve to the same put spread.
  `spread.py` builds call-side verticals already, but enabling them needs the call chain,
  which is never fetched. Reviewed in `docs/STRATEGY-REVIEW-2026-09-01.md`.
- **No automated single-leg repair.** A naked leg HALTs and journals CRITICAL for a human.
- **Paper fills are optimistic.** Quotes are indicative and there is no NBBO size check, so
  measured performance is biased upward.
