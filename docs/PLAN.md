<!--
Mirrored from the canonical build plan for the team's visibility. Not the
final one-page write-up — that's README.md, written Thursday once there's
real trading history to report. This is the working design doc: updated
in place as decisions get corrected, not append-only.
-->

# Alpaca AI Trading Agents Hackathon — Build Plan

## Context

The Alpaca AI Trading Agents Hackathon runs **28 Aug – 4 Sep 2026**, online, $6,000 prize pool. First hackathon project. We chose **"learn the stack, ship something honest"** — smallest scope, deepest understanding, placing is incidental.

Three hard gates. Miss one and the entry is not judged:

1. An **autonomous AI trading agent** on Alpaca's Trading API.
2. It **must use Alpaca's MCP server or CLI** — the plain REST SDK does not count.
3. **All strategies must incorporate options trading.**

Plus: a **brand-new** paper account at exactly **$100,000**, its ID submitted, a public GitHub repo, a working hosted demo URL, a video (max 5 min; the rubric penalises under 3), PDF slides, a 16:9 cover, and a one-page write-up on AI logic / risk gates / Alpaca infrastructure.

Judging: **P&L Performance · Technology Implementation · Creativity & Originality · Presentation & Execution.**

The honest read on P&L: **six sessions** — Fri 28 Aug from 11:00 ET, Mon 31 Aug, Tue 1 – Thu 3 Sep, and 90 minutes on Fri 4 Sep. No holidays inside it. Eight to twelve trades is statistically zero signal. So: optimise the three criteria we fully control, run a capped-risk strategy so P&L is respectable rather than a lottery ticket, and state the sample size plainly. Claiming the AI "found edge" off six sessions loses any judge who does the arithmetic.

The final submission is made from **Khaled's (`Kalwaleed`) lablab.ai account** — matches the GitHub repo owner and the paper trading account this plan requires be created fresh on his login.

---

## The one idea

**The LLM has read-only tools. Every write goes through deterministic Python.**

The LLM proposes a direction. It never picks a strike, sizes a position, or holds an order credential. A pure-Python risk guard has final say and cannot be argued with — the breach is not reachable, rather than merely forbidden by a prompt.

**Why this lands with these judges specifically.** Alpaca merged their paper-trading skills on **25 Aug 2026 — the day before this plan** — with commit messages reading *"require paper verification on every unattended order path"* and *"route scheduled CLI submissions through the paper-guarded wrapper."* Their own skill mandates human confirmation before every order, which is fundamentally **incompatible with the autonomous agent this hackathon demands.**

That tension is the write-up's argument: **the deterministic risk guard is what replaces the human confirmation step.** It is the thing we must build if we want autonomy without recklessness, and it is the gap their own tooling leaves open.

### Verified facts this rests on

| Fact | Consequence |
|---|---|
| Paper accounts get options **Level 3 by default** | Spreads work with zero setup |
| `mleg`: max 4 legs, market/limit only, **negative `limit_price` = net credit** | The sign convention silently breaks credit spreads |
| ~10% of eligible paper fills return **randomly partial** | 4-leg orders manufacture naked shorts. Biggest P&L killer |
| Free plan gives full chain + **greeks + IV** | No paid data subscription needed |
| Quotes are **"indicative"**, not true OPRA; trades 15-min delayed | Treat mid as a bound; log quoted-vs-filled |
| **0DTE has no greeks and no IV** | A delta-targeting strategy structurally cannot use it |
| **15:30 ET** on expiry day, Alpaca rejects same-day-expiry opens | Hard cutoff in the guard |
| Short legs assigned **randomly, overnight** | Turns a spread into naked stock. Needs a handler |
| Paper non-trade activities land **next day** | Never compute intraday P&L from the activities endpoint |
| Alpaca CLI is **Alpha Preview, no confirmation prompts** | `position close-all` fires instantly |

---

## Architecture

```
GitHub Actions cron  ──▶  python loop.py --once      (:07 :22 :37 :52, 13:30–20:00 UTC, Mon–Fri)
        │
        ├─ 1. CLOCK      alpaca clock              → closed? journal a line, exit
        ├─ 2. ORPHAN     alpaca position list      → any EQUITY line = overnight assignment
        │                                            flatten via explicit order. Blowup path closed.
        ├─ 3. EXITS      deterministic, no LLM     → 50% credit / 2× stop / 2 DTE / deadline
        ├─ 4. STATE      account + positions + journal
        │
        ├─ 5. ENTRY  (first tick after 10:30 ET, and after 13:30 ET)
        │       ├─ PROPOSER  Claude + read-only MCP  → {underlying, direction, conviction, dte, thesis, invalidation}
        │       ├─ RESOLVE   pure Python             → target delta ⇒ real OCC symbols from live chain
        │       ├─ CRITIC    Claude, fresh context   → re-fetches the CHOSEN legs, judges thesis only
        │       └─ GUARD     pure Python, no LLM     → first rejection wins, and is final
        │
        ├─ 6. EXECUTE    alpaca api POST /v2/orders  (mleg, 2 legs, limit, client_order_id)
        └─ 7. JOURNAL    append journal.jsonl → git commit → push
                                │
                                ▼
                    Streamlit reads the committed journal. No database.
```

The journal-commit-per-tick earns its keep three times: state for Streamlit, audit trail for the write-up, and genuine commit-spread evidence. lablab's guidance flags a single final push as a red flag.

**GitHub Actions cron is best-effort** — 5–30 min delays are normal, runs can be dropped, and sub-5-minute intervals silently fail. Three mitigations: schedule off the hour (:07 :22 :37 :52), always include `workflow_dispatch` for manual recovery, and log tick staleness when a gap exceeds 45 minutes.

**The important point: the loss cap does not depend on the scheduler.** Max loss is the spread width, fixed at entry. A dropped run cannot exceed it.

### Why both MCP and CLI, genuinely

**MCP is the agent's perception.** Proposer and critic call `get_news`, `get_market_movers`, `get_option_snapshot`. The critic re-verifies delta and credit from a fresh snapshot — the agent that generated the idea does not get to validate it, nor to validate it from cached data. Run via `uvx alpaca-mcp-server` with a **read-only tool allowlist**: `place_option_order` and `close_position` are never exposed to the model.

**CLI is the deterministic hands.** `clock`, `account get`, `position list`, `data option chain`, `api POST /v2/orders`, plus explicit single-symbol closes — never a bulk operation. See "Constraints adopted from Alpaca's own skills" below.

Bonus: the MCP server ships `search_alpaca_docs` / `get_alpaca_endpoint_docs` as always-on tools — authoritative Alpaca docs, better than any general docs MCP for this API.

---

## Strategy

**Short credit vertical on SPY/QQQ. $5 wide. 4–9 DTE. Short leg at 0.16–0.25 delta.** Direction from the LLM; strikes from Python.

| Choice | Why |
|---|---|
| **2-leg vertical, never a condor** | Half the legs, half the fills to win. 4-leg orders are where partial fills manufacture a naked short. Non-negotiable. |
| **4–9 DTE** | 0DTE has no greeks, so the delta rule has no input. Under 4 DTE gamma dominates. Over 9 DTE it won't resolve in six sessions. |
| **SPY + QQQ only** | Deepest books, daily expiries, indicative quotes least wrong on liquid strikes. Two names so the per-underlying gate does real work. |
| **Limit only, negative price** | Market orders with no NBBO size check fill far off fair value. |
| **Entry 10:30 / 13:30 ET** | Avoids the auctions. Unfilled at next tick → cancel, no chase. |
| **Exit: 50% credit, 2× stop, 2 DTE** | Deterministic. No LLM near an exit. |

**The edge, plainly:** there isn't a predictive one. The defensible claim is structural — index implied vol has historically priced more movement than realises, so systematically selling a ~20-delta defined-risk vertical collects that premium with a capped loss. The LLM is a direction filter and a veto, not the edge.

**The failure mode, plainly:** roughly 4:1 against — about eight ~$100 wins per one ~$800 loss. One 2% adverse gap inside six sessions erases the book. Second: paper fills at your limit without checking NBBO size, on indicative quotes, so measured performance is biased optimistic. Third: random overnight assignment.

### Flatten Thursday, not Friday

**Sep 4 is the first Friday of the month — Non-Farm Payrolls at 08:30 ET, ninety minutes before the deadline.** VERIFIED against the BLS release calendar. A force-close into an NFP gap leaves no room to react.

**No new entries after Wed Sep 2, 16:00 ET. All positions closed Thu Sep 3 via an escalation ladder. Fri Sep 4 monitor-only.** Costs a day of P&L, buys a settled, honest, judgeable number.

---

## Risk guard

Pure functions, `(state, plan) -> str | None`. No I/O, no network; time is injected. Numbers live in `governance.json`, rendered verbatim in the dashboard beside the line "no LLM can write to this file". Implemented in `risk.py`, 15 passing tests in `test_agent.py`.

| Gate | Rule |
|---|---|
| `gate_paper_env` | Assert paper before **every** order path. Adopted from Alpaca's own 25 Aug commit. |
| `gate_kill_switch` | A `HALT` file rejects everything except closes. `touch HALT` is the human override. |
| `gate_account_ready` | Account status ∈ {ACTIVE, PAPER_ONLY}, not `trading_blocked`, effective options level ≥ 3 (the *minimum* of approved and configured max, not just approved). |
| `gate_greeks_present` | Both legs need non-null delta **and** IV. The 0DTE guard — structural, not a date check. |
| `gate_dte_window` | 4 ≤ DTE ≤ 9, expiry ≠ today, entry before 15:00 ET. |
| `gate_delta_band` | Short leg 0.16 ≤ \|delta\| ≤ 0.25. |
| `gate_credit_quality` | **Recalibrated.** Reject if credit/width deviates more than ±40% from `0.8 × short_delta`. Catches a bad quote without vetoing the strategy — see the live-probe corrections below. |
| `gate_quote_sanity` | Per leg: bid > 0, ask > bid, spread ≤ 15% of mid. |
| `gate_vrp_present` | ATM IV ≥ 20-day realised vol. Operationalises the one edge this strategy claims — sell premium only when it's actually rich. |
| `gate_max_loss_per_trade` | Sized on **max loss**, never premium. `(width − credit) × 100 × qty ≤ $1,000`. |
| `gate_total_open_risk` | Open + proposed ≤ $3,000. |
| `gate_concurrent` | ≤ 3 open, ≤ 1 per underlying, ≤ 2 new entries per session — prevents revenge-doubling. |
| `gate_buying_power_floor` | Post-trade options BP ≥ $25,000 **and** ≥ 5 × max loss. Margin required is `width × 100 × qty` (verified live — NOT max loss). |
| `gate_daily_drawdown` | −2% from session-start → no new entries today. |
| `gate_cumulative_drawdown` | Equity ≤ $96,000 → **write `HALT`, then close each position individually by explicit order.** Never a bulk endpoint. Also fires on `trading_blocked` or three consecutive loop exceptions. |
| `gate_deadline` | Opens blocked after Wed Sep 2, 16:00 ET. From Thu Sep 3, 15:00 ET, exits escalate: limit at mid → 15:30 cross the spread → 15:50 market `mleg`. |

**Partial-fill unwind:** poll order status after submit; not fully filled in 60s → cancel remainder, flatten any orphan leg via an explicit order, then **recompute open risk from actual filled quantity.** This protects the entire "defined risk" claim and is the most important code in the repo.

### Corrections from the live probe, 26 Aug 2026

A real 2-leg SPY credit spread was opened and closed on a paper account with the market open. Three things the original plan had wrong:

**1. The credit/width band of 0.20–0.45 would have vetoed every trade.** Observed on SPY at 765.55, 7 DTE, short leg at −0.197 delta, $5 wide: net credit **0.60 — a ratio of 0.120**. Widening makes it worse, not better; the ratio falls monotonically. Across the chain the relationship holds at roughly **credit/width ≈ 0.8 × short delta**. Recalibrated to a *relative* test.

**2. Margin held is the full width, not the max loss.** The fill consumed exactly **$500** of options buying power on one $5-wide contract — `width × 100 × qty` — while max loss was $443. Two different numbers.

**3. There is no arithmetic edge, and the write-up must say so.** Sweeping every strike from 0.15 to 0.45 delta across five widths, expected value is **negative in every case** — between −$4 and −$8 per contract, precisely the bid-ask cost. Delta *is* the risk-neutral probability, so a fairly-priced chain cannot yield edge by arithmetic. Confirmed live — the round trip cost **$7.10**.

The only edge premium selling can claim is the **variance risk premium**: implied vol has historically exceeded subsequent realised vol. At −0.197 delta the breakeven win rate is 88% against a risk-neutral 80%, so the strategy needs roughly eight points of VRP to break even. Real, but thin — and **six sessions cannot measure it.**

This is the honest thesis: the agent does not claim to predict the market. It harvests a documented structural premium under a hard risk cap, and reports its sample size truthfully.

**Validated end to end:** chain fetch with greeks · delta-based strike selection · mleg body with negative limit price · simultaneous 2-leg fill at price improvement · margin behaviour · exit via reverse mleg with positive limit · position closed and margin released.

---

## Constraints adopted from Alpaca's own skills

Read all eight files of their four `trading-api` skills. Three things changed the design after the first draft.

### Bulk and lifecycle operations may never be automated

Alpaca ships a sanctioned unattended mode — `confirmation_mode: off` — but five operations require an explicit human "yes" **regardless of that setting**, because it "governs order entry only": `cancel_all_orders`, `close_all_positions`, `close_position`, `exercise_options_position`, `do_not_exercise_options_position`.

**Theta Gate never calls any of these.** Every close — spread exits, the flatten ladder, and the assignment-orphan handler — is an explicit order submission naming the exact symbol(s). This was a real correction to an earlier draft, whose kill path called `close_position` on a cron.

### Their own reasoning is the write-up's argument

Where Alpaca contemplates the human being absent, they prescribe mechanism, not people:

> "**Every deployed path asserts paper at startup** … There is no operator watching to catch a wrong endpoint, and a live account returns the same response shape as a paper one."

> "**Implement circuit breakers (max daily loss, max orders per day, max position size).**"

That's Alpaca prescribing a risk guard by name for exactly our situation. Framing for the write-up: confirmation splits into **legibility** (the preview, always rendered) and **authority** (the approval, toggleable). Alpaca automates away the second whenever a human is absent and replaces it with an assertion that fails closed. Theta Gate does the same, with fourteen assertions instead of one.

### Gates hardened from their text

- Paper flag is a **strict membership test** against `{true, 1, yes}`, case-insensitive — never a truthiness cast.
- **Fail-closed on inconclusive**, not just fail/pass. An unreadable config is inconclusive, and inconclusive fails.
- Assert the resolved endpoint **before every submission**, not once per session.
- Ambiguity after a timeout resolves by **`client_order_id` lookup, never a retry**.
- `client_order_id` is written to disk **before** the HTTP call, so a crash mid-submit stays recoverable.

### Artifact contract, adopted wholesale

Their backtest skill already names our architecture — `risk_limits.json`, `alpaca_order_adapter.py`, `reconciliation_plan.md`. Adopting those filenames makes the repo legible to an Alpaca reviewer in ten seconds. Also adopted: `order_log.csv` with their exact header, semantic `client_order_id` (`tg-<date>-<time>-<underlying>-<pcs|ccs>`), and a `chain_fingerprint.json` per decision for reproducibility.

**The originality play:** their skill repo has zero coverage of options strategy construction, and two real corrections to their guidance are worth an upstream PR — the missing credit/debit sign convention, and a partial-fill safety hole (their docs say naked shorts can't exist, but their own partial-fill handling can produce one). See `docs/PLAN.md` history / the repo's eventual `alpaca-options-spreads` skill for the write-up.

### Still not building a backtester

Their backtest skill supports `stocks` and `crypto` only — options are explicitly out of scope, and it lists "claiming support for unsupported products" as an anti-pattern. Using it on credit verticals would mean writing our own fill model, greeks and assignment logic. That's a rewrite, not a use.

---

## Repo layout

| File | Contents | Status |
|---|---|---|
| `alpaca.py` | CLI subprocess wrapper, paper asserted at every call | ✅ built |
| `spread.py` | Strike selection + mleg body construction. Pure. | ✅ built |
| `risk.py` | The gates + `check_all()` + `exit_signal()`. Stdlib only. | ✅ built |
| `test_agent.py` | 15 tests, fixtures from the real 26 Aug chain | ✅ built, all passing |
| `governance.json` | Every risk number, one place | ✅ built |
| `brain.py` | The two LLM calls, read-only MCP allowlist, fail-closed validator | not yet — Monday |
| `loop.py` | One tick: clock → orphan → exits → entry → journal | not yet — Monday |
| `app.py` | Streamlit dashboard | not yet — Tuesday |
| `.github/workflows/agent.yml` | The cron + `workflow_dispatch` | not yet |
| `env.example` | Documents the inverted `ALPACA_PAPER_TRADE` / `ALPACA_LIVE_TRADE` trap | ✅ built |
| `README.md` | The one-page write-up deliverable | not yet — Thursday |
| `docs/diagrams/*.html` | Architecture, sequence, flowchart — KBW skin | ✅ built |
| `social/drafts/` | Post drafts, PK posts manually from `@khaledalwaleed` | ✅ built, post 01 live |

**Dependencies — three:** `claude-agent-sdk`, `streamlit`, `pytest`.
**Not building:** a backtester, a database, parallel research agents, streaming, a second strategy.

---

## Demo — Streamlit Community Cloud

Deployed from the repo, auto-redeploying on each push. **Primary view is history, not live state.** Judges review off-hours with the market shut.

1. Equity curve
2. Decision log — thesis, invalidation, critic verdict, proposed vs filled price per leg
3. **"Why no trade"** — gate rejections counted by reason
4. Open and closed positions with entry credit, exit reason, realised P&L
5. `governance.json` verbatim

---

## Timeline

**Fri 28 Aug from 11:00 ET** — create the **fresh submission** paper account, confirm $100,000, record the ID. **No manual orders on it, ever** — its history must be 100% agent-generated, because that history is what judges read as "autonomous." `alpaca.py` + first tests: done. Save a live chain snapshot as the test fixture: done.

**Sat–Sun 29–30 Aug** — market shut, commits still count. `spread.py` + `risk.py` + the full test file: **done**. Author the options skill for the upstream PR.

**Mon 31 Aug** — `brain.py` + `loop.py`. First autonomous cycle, first real spread.
**Tue 1 Sep** — `app.py`, deploy, verify the URL cold from outside.
**Wed 2 Sep** — fix what live trading broke. **Last day for new entries.**
**Thu 3 Sep** — flatten via the escalation ladder. Media block: diagrams → deck → record → cut → write-up. `/security-review` before the repo goes public.
**Fri 4 Sep** — monitor-only. Final push. Submit before 11:00 ET.

Commit and push daily — a single final push reads as pre-built and is flagged in lablab's own guidance.

---

## Open risks

| Risk | Mitigation | Residual |
|---|---|---|
| Partial fill orphans a short leg | 2-leg only + 60s unwind + risk recomputed from filled qty | A fill between poll cycles |
| Overnight assignment → naked stock | Orphan handler flattens via explicit order next tick | Up to ~15 min unhedged |
| Indicative quotes mis-price strikes | Limit only; recalibrated credit gate; quote-sanity gate; log quoted vs filled | P&L stays biased optimistic — reported as such |
| Actions cron drifts or drops a run | Off-hour schedule, `workflow_dispatch`, staleness logging | A skipped session; loss cap is unaffected |
| Streamlit cold start | Actions pings each tick | First-click spinner |
| Secrets in a public repo | `.gitignore` from commit one; Actions Secrets; `/security-review` before going public | — |
| Six sessions is not a sample | Write-up states n and claims nothing about edge | — |

**Rollback:** `touch HALT` stops all opening. Flattening is position by position, by explicit order — never a bulk endpoint. The account is fresh, paper, funded with nothing real.

---

## Verification

1. `pytest -q` — currently 15/15. Null greeks rejected; mleg body has `order_class="mleg"`, **`limit_price < 0`**, top-level `qty`, no top-level `symbol`/`side`, exactly 2 legs, correct sides/intents; `ratio_qty` GCD 1; sizing from max loss; delta band with no silent fallback; deadline blocks opens; cumulative drawdown halts; equity line flags as orphan.
2. `alpaca doctor` reports `https://paper-api.alpaca.markets`. Every session, non-negotiable.
3. `alpaca order submit --dry-run` before any live submit.
4. One full `loop.py --once --dry-run` that logs and sends nothing.
5. Force a veto against each gate; confirm it appears in the "Why no trade" panel.
6. `browse` the Streamlit URL cold, from outside.
7. `/security-review` before the repo goes public.
