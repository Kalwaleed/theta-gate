# Theta Gate — one-page write-up

An autonomous options agent that sells short-dated put credit spreads on SPY
and QQQ, and refuses to trade far more often than it trades.

**The thesis in one line:** a fairly priced option chain has zero arithmetic
edge, negative by exactly the bid-ask cost. Verified live on 26 Aug 2026:
credit/width is not a fixed band, it tracks roughly 0.8 x short delta and
falls as width grows. So the only edge Theta Gate claims is the variance risk
premium — sell premium only when implied vol is measurably richer than
realised. Everything else in the system exists to stop the agent from trading
when that condition is absent.

## AI logic

There is exactly **one** LLM call per tick, and it is deliberately the least
powerful component in the system.

`brain.py:propose()` may choose an underlying, a direction, and write a short
thesis. It may not choose a strike, an expiry, a quantity, a price, or a gate
threshold. `spread.py` and `risk.py` own every one of those deterministically,
and read nothing from the model except five validated fields.

The model runs with no tool access at all — empty tool list, `mcp_servers={}`,
`strict_mcp_config=True`, no filesystem or project settings, no broker
credential, no news feed, no web search. It sees only the same market numbers
already computed for the gates. `brain.py` cannot import `alpaca.py`,
`store.py`, or `execution.py`, and does not.

Every failure mode collapses to the same outcome: malformed JSON, a schema
violation, a timeout, an SDK exception, an empty response, or a proposal that
reads back an injected instruction all produce **no proposal, never a crash**.
The exit and reconciliation paths keep running when the model returns nothing.
A bearish proposal is a no-trade — V1 is put-side only and never substitutes a
call spread.

## Risk gates

`risk.py` has the last word on every order. It runs **21 gates** — 18
state-only, 3 requiring a sized position — and returns the first failure
rather than a score.

The load-bearing ones:

| Gate | Threshold |
|---|---|
| Variance risk premium | ATM IV ≥ 10-day realised vol, by ≥ 1.0 vol point |
| Regime | VIX < 30, VIX9D < VIX3M, intraday move < 2% |
| Structure | $5 wide, 6–9 DTE, short delta 0.16–0.25, 2 contracts |
| Credit quality | ≥ 10% of width, and within 40% of the 0.8 × delta curve |
| Concurrency | 2 open positions, 1 per underlying, 1 fill per underlying per session |
| Loss caps | $1,000 max loss per trade, $3,000 total open risk |
| Buying power | floor of $25,000, and ≥ 5 × max loss |
| Drawdown halt | −1% daily, or equity below $98,000 |

Position size is fixed at two contracts, not computed from a budget. At the
$5 width and the 10%-of-width credit floor, the worst case a position can
carry is $900 against a $1,000 per-trade cap — so the cap cannot be reached
by sizing alone. Two contracts is more variance, not more edge.

Regime filters block **new entries only**. A volatility spike never
liquidates an open position or blocks an exit.

Exits are equally deterministic: take profit at 50% of credit, stop at a
closing debit of 2× credit, time exit at 2 DTE, and a mandatory four-rung
force-close ladder on the final trading day — mid at 14:30 ET, cross the
spread at 15:00, market-multileg at 15:30 capped at width − $0.01, and at
15:45 reconcile-and-alert only, which submits nothing because a fresh order
15 minutes before the close can half-fill and leave a naked leg overnight.

## Alpaca infrastructure implementation

Theta Gate uses all three Alpaca surfaces, and uses them for different jobs
on purpose. It runs as a scheduled GitHub Actions tick on a fresh $100,000
paper account.

**The CLI places every order.** Entry, exit and the force-close ladder all go
through it — one write path, so there is one place to audit.

**The MCP server never places anything.** It runs a separate scheduled job
that reconciles the broker's own view of positions and orders against the
journal. Two read tools are allowed (`get_all_positions`, `get_orders`); all
ten write tools in the trading toolset are denied by name, and the permission
mode denies anything unlisted, so the deny list is redundancy rather than the
control. It reads structured tool results only, never the model's prose,
writes one journal event per run, and exits non-zero on a mismatch — the job
goes red rather than reporting a clean book it cannot prove.

Separating them is the point: the component that verifies the books is not
the component that writes them.

- **Paper is re-proved before every order path**, not once at startup.
  Unproven is treated as live and refuses.
- **Idempotency is the client order ID.** A duplicate returns HTTP 422 and
  never a second order — that single behaviour is the whole mechanism.
- **Multi-leg submission is atomic.** Both legs fill at one broker timestamp
  or the position is reconciled; a naked leg trips the kill switch.
- **State survives an ephemeral runner.** The journal is append-only and
  git-published every tick, so `data/HALT.json` and every position are
  recovered by re-reading it, not by trusting runner memory.
- **Reconciliation runs before anything else** each tick: orphan broker
  positions, untracked symbols and assignment are detected and halt entries.
- **A second, independent reconciliation** runs daily over MCP, so a bug in
  the CLI path cannot also be the thing that certifies the CLI path.

## Disclosures

Three, stated plainly because judges should not have to find them.

**The VRP thresholds were re-based on 30 Aug with Friday's marks in view.**
The realised-vol window moved 20 → 10 days and the margin 2.0 → 1.0 points,
because a 20-day window still carried the 3–4 Aug rally and was vetoing every
candidate. The reasoning is recorded in `governance.json` itself, not
reconstructed after the fact — but it was a threshold chosen while looking at
data it would be applied to, and that is worth knowing.

**Commit `96fd434` (1,049 lines) landed 3h40m before kickoff.** The account is
fresh and every trade in it is inside the window; the scaffolding was not.

**Three `mcp_reconciliation_failed` rows sit in the journal at 16:41–16:42 ET
on 31 Aug.** They are development runs of the reconciliation job, made before
its dependency pin was fixed, and they wrote into the live trail because the
job did not yet sandbox its own journal. A second session caught it and it
was fixed the same hour. The rows stay because the trail is append-only —
which is the property that makes it worth trusting.
