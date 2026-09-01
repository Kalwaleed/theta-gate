# Theta Gate — one-page write-up

**An autonomous options agent that cannot place a trade it should not.**
Alpaca paper account `7a013821-9249-4505-8025-fb298f0931a5` · $100,000 ·
every order placed by the agent, none by a human.

---

## The problem this solves

Alpaca's paper-trading skills require **human confirmation before every order**, and five
operations demand it *regardless* of the unattended-mode setting. That is incompatible
with the autonomous agent this hackathon asks for: a cron at 10:30 on a Tuesday has
nobody to ask.

A confirmation is two things wearing one name — *legibility* (showing what is about to
happen) and *authority* (deciding whether it may). Alpaca automates away the second
whenever a human is absent and replaces it with an assertion that fails closed. Theta
Gate does the same, with **21 assertions instead of one**.

## AI logic

One bounded model call per entry window:

```python
ClaudeAgentOptions(system_prompt=…, model=…, max_turns=1,
                   tools=[], allowed_tools=[], mcp_servers={},
                   strict_mcp_config=True, setting_sources=[])
```

Zero tools, zero MCP servers, one turn, no filesystem or project settings. It sees only
the scalar market numbers already computed for the gates — no chain, no news, no
credential — and returns five fields: `underlying`, `direction`, `confidence`, `thesis`,
`invalidation`.

**Why no tools rather than a read-only allowlist:** an allowlist still holds a network
client and depends on being maintained correctly forever. `tools=[]` cannot reach
anything, and `strict_mcp_config=True` means a stray `.mcp.json` cannot quietly re-arm
it. The breach is *unreachable*, not merely forbidden — and a test asserts it, because a
tool added here would otherwise break nothing else in the repo.

Any failure — malformed JSON, timeout, or a thesis that reads back an injected
instruction — produces no proposal and never an exception; exits keep running. The model
never picks a strike, sets a price, sizes a position or holds a credential.

## Risk gates

`risk.py` is pure functions — no I/O, no network, `now` injected. That is what makes it
testable and what makes it the only component holding a real decision. **First rejection
wins and is final**; no gate is re-evaluated after a veto, and no model call sits
downstream of one.

| Group | Gates |
|---|---|
| Environment | paper asserted before *every* order; kill switch; account status; options level ≥ 3 |
| Regime *(entry-only, never blocks an exit)* | VIX < 30; VIX9D < VIX3M; \|intraday move\| < 2%; FOMC/CPI/PCE/NFP blackout |
| Contract | both legs need delta *and* IV (the 0DTE guard — structural, not a date check); DTE window; 0.16–0.25 short delta; quote age ≤ 60s; spread ≤ 15% of mid |
| Price | credit within ±40% of 0.8 × short delta; floor at 10% of width; ATM IV − realised vol ≥ 1.0 pt |
| Exposure | max loss per trade; total open risk; ≤ 2 concurrent, ≤ 1 per underlying; buying power ≥ $25k *and* ≥ 5× max loss |
| Drawdown | −1% on the day → no new entries; equity ≤ $98k → HALT and close out |

Every number lives in `governance.json`, rendered verbatim on the dashboard beside the
line *"no LLM can write to this file"*. No LLM does — `brain.py` cannot import the
broker, and a test walks its AST to prove it.

## Alpaca infrastructure

**The CLI is the integration.** Every broker call shells out through `alpaca.py` —
`clock`, `account get`, `position list`, `data option chain`/`stock-bars`/`latest-quote`,
the `order` verbs, and `order submit --order-class mleg` for the two-leg vertical.
`alpaca-py` is excluded from `requirements.txt` on purpose.

**Durability without a database.** The canonical design called for Postgres with
row-level security, OIDC attestation and fenced leases. We cut it, on the record. What
replaced it: a deterministic `client_order_id` always looked up before submitting
(verified live — Alpaca rejects a duplicate with 422 rather than creating a second
order, which is the whole mechanism); the broker as source of truth, refetched every
tick; and an append-only JSONL journal written *before* the network call that might
submit, git-committed each tick and replayed into SQLite under a SHA-256 hash chain so
an edited history is detectable.

## Results

Realised P&L **[P&L]** · **[n]** trades · win rate **[%]** · max drawdown **[%]**
across **[s]** sessions.

**What [n] trades cannot show:** edge. At −0.197 delta the breakeven win rate is 88%
against a risk-neutral 80% — roughly eight points of variance risk premium just to break
even, and six sessions cannot measure that. Swept from 0.15 to 0.45 delta, expected value
is negative in every case by precisely the bid-ask cost: delta *is* the risk-neutral
probability, so a fairly-priced chain cannot yield edge by arithmetic.

**What it can show:** that the guard held — which gates fired and how often, that no
order was placed outside them, that max loss was capped by construction at entry, and
that the whole history is reconstructable from a hash-chained journal the agent wrote
itself. That is measurable at n = **[n]**. Edge is not.

## Disclosures and limitations

- **VRP thresholds were re-based on 30 Aug with Friday's marks in view** — realised-vol
  window 20 → 10 days, margin 2.0 → 1.0 points, because the 20-day window still carried
  the early-August rally and was vetoing every candidate. Dated reasoning is in
  `governance.json`. It remains a threshold chosen while looking at the data it would be
  applied to.
- **Commit `96fd434` (1,049 lines) landed 3h40m before kickoff.** The account is fresh and
  every trade is inside the window; the scaffolding was not.
- **Three `mcp_reconciliation_failed` rows sit in the journal at 16:41–16:42 ET on 31 Aug** —
  development runs made before that job sandboxed its own journal, caught the same hour.
  They stay because the trail is append-only, which is what makes it worth trusting.
- **The agent filters; it does not yet select.** All 21 gates answer *should I trade*,
  none *what should I trade* — `bullish` and `neutral` resolve to the same put spread.
  `spread.py` builds call-side verticals already; enabling them needs the call chain,
  which is never fetched. See `docs/STRATEGY-REVIEW-2026-09-01.md`.
- **No automated single-leg repair.** A naked leg HALTs and journals CRITICAL for a human.
- **Paper fills are optimistic** — indicative quotes, no NBBO size check. Measured
  performance is biased upward.
