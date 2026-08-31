# Theta Gate — one-page write-up

An autonomous options agent that sells short-dated put credit spreads on SPY
and QQQ, and refuses to trade far more often than it trades.

**The thesis:** a fairly priced option chain has no arithmetic edge — verified
live on 26 Aug, expected value came out negative by almost exactly the
bid-ask cost. So Theta Gate claims exactly one edge and names it: the
variance risk premium. Everything else exists to stop it trading when that
premium is absent.

## AI logic

There is exactly **one** LLM call per tick, and it is deliberately the least
powerful component in the system.

`brain.py:propose()` may choose an underlying, a direction, and write a short
thesis. It may not choose a strike, an expiry, a quantity, a price, or a gate
threshold — `spread.py` and `risk.py` own every one of those deterministically
and read back only five validated fields.

The model runs with no tool access at all: empty tool list, `mcp_servers={}`,
`strict_mcp_config=True`, no filesystem, no broker credential, no news, no web
search. It sees the same market numbers the gates see and nothing more.
`brain.py` cannot import `alpaca.py`, `store.py` or `execution.py`.

Every failure collapses to one outcome. Malformed JSON, a schema violation, a
timeout, an empty response, or a proposal echoing an injected instruction all
produce **no proposal, never a crash** — exit and reconciliation keep running
regardless. A bearish proposal is a no-trade; V1 is put-side only.

## Risk gates

`risk.py` has the last word on every order. It runs **21 gates** — 18
state-only, 3 requiring a sized position — and returns the first failure
rather than a score.

| Gate | Threshold |
|---|---|
| Variance risk premium | ATM IV ≥ 10-day realised vol, by ≥ 1.0 vol point |
| Regime | VIX < 30, VIX9D < VIX3M, intraday move < 2% |
| Structure | $5 wide, 6–9 DTE, short delta 0.16–0.25, 2 contracts |
| Credit quality | ≥ 10% of width, within 40% of the 0.8 × delta curve |
| Concurrency | 2 open, 1 per underlying, 1 fill per underlying per session |
| Loss caps | $1,000 per trade, $3,000 total open risk |
| Buying power | floor of $25,000, and ≥ 5 × max loss |
| Drawdown halt | −1% daily, or equity below $98,000 |

Size is fixed at two contracts, not computed from a budget. At the $5 width
and the 10%-of-width credit floor a position tops out at $900 against the
$1,000 cap — the cap cannot be reached by sizing alone. Two contracts is more
variance, not more edge.

Regime filters block **new entries only**; a volatility spike never liquidates
a position or blocks an exit. Exits: take profit at 50% of credit, stop at a
closing debit of 2× credit, time exit at 2 DTE, and a mandatory four-rung
force-close ladder on the final day — mid, cross the spread, capped
market-multileg, then reconcile-and-alert, which deliberately submits nothing,
because a fresh order 15 minutes before the close can half-fill and leave a
naked leg overnight.

## Alpaca infrastructure implementation

All three Alpaca surfaces, each doing a different job on purpose. The agent
runs as a scheduled GitHub Actions tick on a fresh $100,000 paper account.

**The CLI places every order** — entry, exit, force-close. One write path, so
there is one place to audit.

**The MCP server places nothing.** A separate scheduled job reconciles the
broker's own positions and orders against the journal. Two read tools allowed,
all ten write tools denied by name, and the permission mode denies anything
unlisted — so the deny list is redundancy, not the control. It reads structured
tool results only, never model prose, and exits non-zero on a mismatch rather
than reporting a clean book it cannot prove.

The separation is the point: the component that verifies the books is not the
component that writes them.

- **Paper is re-proved before every order path.** Unproven is treated as live
  and refuses.
- **Idempotency is the client order ID.** A duplicate returns HTTP 422 and
  never a second order — that behaviour is the whole mechanism.
- **Multi-leg submission is atomic;** a naked leg trips the kill switch.
- **State survives an ephemeral runner.** The journal is append-only and
  git-published each tick, so positions and `HALT.json` are recovered by
  re-reading it, never by trusting runner memory.

## Disclosures

**VRP thresholds were re-based on 30 Aug with Friday's marks in view** — the
realised-vol window 20 → 10 days, the margin 2.0 → 1.0 points, because the
20-day window still carried the early-August rally and was vetoing every
candidate. Dated reasoning is in `governance.json`. It remains a threshold
chosen while looking at the data it would be applied to.

**Commit `96fd434` (1,049 lines) landed 3h40m before kickoff.** The account is
fresh and every trade is inside the window; the scaffolding was not.

**Three `mcp_reconciliation_failed` rows sit in the journal at 16:41–16:42 ET
on 31 Aug** — development runs made before that job sandboxed its own journal.
Caught by a second session and fixed the same hour. They stay because the
trail is append-only, which is the property that makes it worth trusting.
