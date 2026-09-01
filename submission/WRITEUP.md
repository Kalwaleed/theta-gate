# Theta Gate — one-page write-up

**An autonomous options agent that cannot place a trade it should not.**
Alpaca paper account `7a013821-9249-4505-8025-fb298f0931a5` · $100,000 ·
every order placed by the agent, none by a human.

## The problem this solves

Alpaca shipped their paper-trading skills on 25 August. Their own guidance requires
**human confirmation before every order**, and five operations demand it regardless of
the unattended-mode setting. That is incompatible with the autonomous agent this
hackathon asks for. A cron at 10:30 on a Tuesday has nobody to ask.

**Our answer:** a confirmation is two things wearing one name — *legibility* (showing
what is about to happen) and *authority* (deciding whether it may). Alpaca automates away
the second whenever a human is absent and replaces it with an assertion that fails
closed. Theta Gate does the same, with **21 assertions instead of one**.

## AI logic

One bounded model call per entry window. `brain.py` runs Claude Opus 5 with:

```python
ClaudeAgentOptions(system_prompt=…, model=…, max_turns=1,
                   tools=[], allowed_tools=[], mcp_servers={},
                   strict_mcp_config=True, setting_sources=[])
```

Zero tools. Zero MCP servers. One turn. It sees only the scalar market numbers already
computed for the gates — no chain, no news, no credential — and returns exactly five
fields: `underlying`, `direction`, `confidence`, `thesis`, `invalidation`.

**Why no tools rather than a read-only allowlist:** an allowlist still holds a network
client and must stay correct forever. `tools=[]` cannot reach anything, and
`strict_mcp_config=True` means a stray `.mcp.json` cannot quietly re-arm it. The breach
is *unreachable*, not forbidden by a prompt — and a test asserts it.

Any failure — malformed JSON, schema violation, timeout, or a thesis reading back an
injected instruction — produces no proposal and never an exception.

**What the model does not do:** pick a strike, an expiry, a price, a size, or hold a
credential. A bearish proposal is NO_TRADE, never a call-side substitution.

## Risk gates

`risk.py` is pure functions — no I/O, no network, `now` injected. **First rejection wins
and is final**; no gate is re-evaluated after a veto, and no model call sits downstream.

| Group | Gates |
|---|---|
| Environment | paper asserted before *every* order; kill switch; account status; options level ≥ 3 |
| Regime *(entry-only, never blocks an exit)* | VIX < 30; VIX9D < VIX3M; \|intraday move\| < 2%; FOMC/CPI/PCE/NFP blackout |
| Contract | both legs need delta *and* IV (the 0DTE guard — structural, not a date check); DTE window; short delta 0.16–0.25; quote age ≤ 60s; spread ≤ 15% of mid |
| Price | credit within ±40% of 0.8 × short delta; floor at 10% of width; ATM IV − realised vol ≥ 1.0 pt |
| Exposure | max loss per trade; total open risk; ≤ 2 concurrent, ≤ 1 per underlying; buying power ≥ $25k *and* ≥ 5× max loss |
| Drawdown | −1% on the day, or equity ≤ $98k → no new entries. Neither closes a position; exits stay on their own signals |

Every number lives in `governance.json`, rendered verbatim on the dashboard. No LLM can
write to it — `brain.py` cannot import the broker, and a test walks its AST to prove it.

## Alpaca infrastructure

**The CLI is the integration.** Every broker call shells out through `alpaca.py`,
including `order submit --order-class mleg` for the two-leg vertical. `alpaca-py` is
excluded from `requirements.txt` on purpose.

**The MCP server places nothing.** A separate scheduled job reconciles the broker's own
positions and orders against the journal: two read tools allowed, all ten write tools
denied by name, non-zero exit on a mismatch. The component that verifies the books is not
the one that writes them.

**Durability without a database.** A deterministic `client_order_id` is looked up before
every submit — Alpaca rejects a duplicate with 422 rather than creating a second order,
and that is the whole mechanism. The broker is the source of truth, refetched each tick.
The journal is append-only JSONL, written *before* the network call that might submit,
git-committed every tick and replayed into SQLite under a SHA-256 hash chain.

## Results

Realised P&L **[P&L]** · **[n]** trades · win rate **[%]** · max drawdown **[%]** across
**[s]** sessions.

**What [n] trades cannot show:** edge. Swept from 0.15 to 0.45 delta, expected value is
negative in every case by precisely the bid-ask cost — delta *is* the risk-neutral
probability, so a fairly priced chain cannot yield edge by arithmetic.

**What it can show:** that the guard held. Which gates fired and how often, that no order
was placed outside them, that max loss was capped at entry by construction, and that the
history is reconstructable from a hash-chained journal the agent wrote itself.

## Disclosures and limitations

- **VRP thresholds were re-based on 30 Aug with Friday's marks in view** — window 20 → 10
  days, margin 2.0 → 1.0 points, because the 20-day window still carried the early-August
  rally and vetoed every candidate. Chosen while looking at the data it would be applied to.
- **Commit `96fd434` (1,049 lines) landed 3h40m before kickoff.** The account is fresh and
  every trade is inside the window; the scaffolding was not.
- **Three `mcp_reconciliation_failed` rows sit in the journal at 16:41–16:42 ET on 31 Aug**
  — dev runs made before that job sandboxed its own journal, caught the same hour. They
  stay: the trail is append-only, which is what makes it worth trusting.
- **The agent filters; it does not select.** All 21 gates answer *should I trade*, none
  *what should I trade* — `bullish` and `neutral` resolve to the same put spread.
- **No automated single-leg repair.** A naked leg HALTs and journals CRITICAL for a human.
- **Paper fills are optimistic** — indicative quotes, no NBBO size check. Measured
  performance is biased upward.
