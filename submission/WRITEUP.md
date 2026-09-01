# Theta Gate — one-page write-up

**An autonomous options agent that cannot place a trade it should not.**
Alpaca paper account `7a013821-9249-4505-8025-fb298f0931a5` · $100,000 ·
every order placed by the agent, none by a human.

## The problem this solves

Alpaca shipped its paper-trading skills on 25 August. The docs require human
confirmation before every order, and five operations demand it even in unattended
mode. That breaks the autonomous-agent brief this hackathon set — a cron job at
10:30 on a Tuesday has no one to ask.

A "confirmation" is really two things: seeing what's about to happen, and deciding
whether it's allowed. Alpaca drops the second part whenever no human is around and
swaps in a fail-closed assertion. Theta Gate does the same thing, just with 21
assertions instead of one.

## AI logic

One bounded model call per entry window. `brain.py` runs Claude Opus 5 with:

```python
ClaudeAgentOptions(system_prompt=…, model=…, max_turns=1,
                   tools=[], allowed_tools=[], mcp_servers={},
                   strict_mcp_config=True, setting_sources=[])
```

No tools, no MCP servers, one turn. It only sees the scalar market numbers already
computed for the gates, and returns five fields: `underlying`, `direction`,
`confidence`, `thesis`, `invalidation`.

Why not a read-only allowlist instead of zero tools? An allowlist still holds a
live network client that has to stay correct forever. `tools=[]` can't reach
anything, and `strict_mcp_config=True` stops a stray `.mcp.json` from quietly
re-arming it. A test asserts this — the breach isn't forbidden by a prompt, it's
unreachable.

Any failure — bad JSON, a schema violation, a timeout, a thesis that echoes an
injected instruction — kills the proposal instead of raising an exception.

The model never picks a strike, expiry, price, or size, and never holds a
credential. A bearish read comes back NO_TRADE, not a call-side swap.

## Risk gates

`risk.py` is pure functions: no I/O, no network, `now` passed in. First rejection
wins and is final — no gate gets re-checked after a veto, and nothing downstream
calls the model again.

| Group | Gates |
|---|---|
| Environment | paper asserted before *every* order; kill switch; account status; options level ≥ 3 |
| Regime *(entry-only, never blocks an exit)* | VIX < 30; VIX9D < VIX3M; \|intraday move\| < 2%; FOMC/CPI/PCE/NFP blackout |
| Contract | both legs need delta *and* IV (the 0DTE guard — structural, not a date check); DTE window; short delta 0.16–0.25; quote age ≤ 60s; spread ≤ 15% of mid |
| Price | credit within ±40% of 0.8 × short delta; floor at 10% of width; ATM IV − realised vol ≥ 1.0 pt |
| Exposure | max loss per trade; total open risk; ≤ 2 concurrent, ≤ 1 per underlying; buying power ≥ $25k *and* ≥ 5× max loss |
| Drawdown | −1% on the day, or equity ≤ $98k → no new entries. Neither closes a position; exits stay on their own signals |

Every number lives in `governance.json` and shows up unchanged on the dashboard.
No LLM can write to it: `brain.py` can't import the broker, and a test walks the
AST to prove it.

## Alpaca infrastructure

**The CLI is the integration.** Every broker call shells out through `alpaca.py`,
including `order submit --order-class mleg` for the two-leg vertical. `alpaca-py`
is left out of `requirements.txt` on purpose.

**The MCP server places nothing.** A separate scheduled job reconciles the
broker's positions and orders against the journal — two read tools allowed, all
ten write tools denied by name, non-zero exit on any mismatch. The thing that
checks the books isn't the thing that writes them.

**Durability without a database.** A deterministic `client_order_id` gets looked
up before every submit, so Alpaca rejects a duplicate with a 422 instead of
creating a second order. That's the whole mechanism. The broker stays the source
of truth, refetched every tick. The journal itself is append-only JSONL, written
before the network call that might place an order, committed to git each tick,
and replayed into SQLite under a SHA-256 hash chain.

## Results

Realised P&L **[P&L]** · **[n]** trades · win rate **[%]** · max drawdown **[%]**
across **[s]** sessions.

What [n] trades can't show: edge. Swept from 0.15 to 0.45 delta, expected value
comes out negative every time, by exactly the bid-ask cost. Delta is the
risk-neutral probability, so a fairly priced chain can't yield edge by
arithmetic alone.

What it can show: that the guard held. Which gates fired, how often, that no
order slipped through outside them, that max loss was capped at entry by
construction, and that the whole history can be rebuilt from a hash-chained
journal the agent wrote itself.

## Disclosures and limitations

- VRP thresholds were re-based on 30 Aug with Friday's marks already in view:
  window went 20 → 10 days, margin 2.0 → 1.0 points, because the 20-day window
  still carried the early-August rally and vetoed every candidate. Chosen while
  looking at the data it would be applied to.
- Commit `96fd434` (1,049 lines) landed 3h40m before kickoff. The account is
  fresh and every trade is inside the window; the scaffolding was not.
- Three `mcp_reconciliation_failed` rows sit in the journal at 16:41–16:42 ET on
  31 Aug: dev runs made before that job sandboxed its own journal, caught in the
  same hour. They stay — the trail is append-only, which is the point.
- The agent filters, it doesn't select. All 21 gates answer *should I trade*,
  none *what should I trade* — `bullish` and `neutral` resolve to the same put
  spread.
- No automated single-leg repair. A naked leg HALTs and journals CRITICAL for a
  human.
- Paper fills are optimistic: indicative quotes, no NBBO size check. Measured
  performance is biased upward.
