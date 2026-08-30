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

## Strategy/architecture authority — and Scoped V1's deliberate deviations

**[`docs/THETA_GATE_CANONICAL_PLAN.md`](THETA_GATE_CANONICAL_PLAN.md)** is the strategy and architecture reference — trading spec (§4), gate ordering (§6), exit arithmetic (§8), the LLM boundary (§9). This file mirrors its execution-relevant detail for day-to-day work.

That document also specs a production-grade control system — Postgres with row-level security and 6 credentialed database roles, GitHub OIDC/Sigstore/Fulcio/Rekor release attestation, immutable-tag release promotion with a separate offline break-glass descriptor, fenced distributed leases, hash-chained event sourcing, a no-bypass branch-freeze ruleset, and a test suite requiring concurrent-runner race-condition canaries. Reviewed 29 Aug 2026: that's realistically weeks of distributed-systems engineering, not achievable before Monday 31 Aug's first trading window (its own Phase 2 deadline — the entire Postgres/lease layer — was due the day it was reviewed).

**We are building Scoped V1 instead** — every real correctness fix from the canonical doc's §2 "material corrections" and §4-9 trading spec, none of the control-plane/attestation/chaos-test infrastructure. This is a disclosed, deliberate scope cut, not an oversight:

- **Idempotency** comes from the broker, not a database: a deterministic (non-random) `client_order_id` per order, always looked up before submitting. Verified live 29 Aug 2026 — Alpaca rejects a resubmitted duplicate id with 422 `client_order_id must be unique` rather than creating a second order, which is the fact this whole mechanism leans on.
- **Concurrency** is one GitHub Actions `concurrency:` group (`cancel-in-progress: false`) — a platform feature, not custom infra.
- **Journal** is an append-only local JSONL, written incrementally (intent before every broker call, outcome after — not batched at tick end), git-committed.
- **Queryable history** is SQLite (`store.py`), and only as a *derived read model* — `rebuild()` drops and replays `journal.jsonl` from line 1, so it cannot drift, and it is gitignored so nobody mistakes a committed binary for authority. It exists for the dashboard's aggregates (equity curve, "why no trade" by gate, decision log) and for a `chain_sha256` hash chain that makes an edited history detectable. It is deliberately **not** promoted to the primary store: a binary `.db` in the git-publish path would collide with the one durability mechanism this repo has — five people rebasing onto main while the cron commits the journal several times a day. JSONL merges and diffs; a `.db` does not.
- **HALT** is a local flag file, checked at tick start.
- **The LLM boundary is tighter than specced, not looser:** the proposer runs with `tools=[]` and `mcp_servers={}` rather than a read-only MCP allowlist, and the second-pass critic is cut — `risk.py`'s gates already re-verify delta, credit, greeks and quote age on the resolved legs, deterministically. See [The Alpaca integration is the CLI](#the-alpaca-integration-is-the-cli--corrected-29-aug-2026).

No Postgres/RLS, no OIDC/Sigstore attestation, no immutable-tag promotion, no branch-freeze ruleset, no chaos/race test suite, no 5-way workflow split — one `.github/workflows/agent.yml`.

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
        │       ├─ PROPOSER  Claude, NO tools at all → {underlying, direction, target_dte, thesis}
        │       ├─ RESOLVE   pure Python             → target delta ⇒ real OCC symbols from live chain
        │       └─ GUARD     pure Python, no LLM     → first rejection wins, and is final
        │
        ├─ 6. EXECUTE    alpaca order submit --order-class mleg  (2 legs, limit, client_order_id)
        └─ 7. JOURNAL    append journal.jsonl → git commit → push
                                │
                                ▼
                    Streamlit reads the committed journal, via store.py's
                    SQLite read model (derived, gitignored, rebuilt on demand).
```

The journal-commit-per-tick earns its keep three times: state for Streamlit, audit trail for the write-up, and genuine commit-spread evidence. lablab's guidance flags a single final push as a red flag.

**GitHub Actions cron is best-effort** — 5–30 min delays are normal, runs can be dropped, and sub-5-minute intervals silently fail. Three mitigations: schedule off the hour (:07 :22 :37 :52), always include `workflow_dispatch` for manual recovery, and log tick staleness when a gap exceeds 45 minutes.

**The important point: the loss cap does not depend on the scheduler.** Max loss is the spread width, fixed at entry. A dropped run cannot exceed it.

### The Alpaca integration is the CLI — corrected 29 Aug 2026

**As built, the agent talks to Alpaca through the CLI only.** `alpaca.py` shells out to the `alpaca` binary for every broker call — `clock`, `account get`, `position list`, `data option chain`, `data stock-bars`, `data latest-quote`, `order get`/`get-by-client-id`/`list`/`cancel`, and `order submit --order-class mleg` for the 2-leg vertical (`alpaca.py:207-215`). That satisfies the hackathon's second hard gate (MCP **or** CLI; the plain REST SDK does not count), and `alpaca-py` is excluded from `requirements.txt` on purpose.

**An earlier draft of this section described MCP as "the agent's perception" — proposer and critic calling `get_news`, `get_market_movers`, `get_option_snapshot`, with the critic re-verifying delta and credit from a fresh snapshot. None of that shipped, and this section previously claimed it did.** What `brain.py` actually does (lines 235-244):

```python
options = ClaudeAgentOptions(
    system_prompt=SYSTEM_PROMPT, model=MODEL_ID, max_turns=1,
    tools=[], allowed_tools=[], mcp_servers={},
    strict_mcp_config=True, setting_sources=[],
)
```

Zero tools, zero MCP servers, one turn, and no filesystem/user/project settings. The model sees only the same market numbers already computed for the gates.

**This is tighter than the plan, not looser** — and it is the honest version of the "the LLM has read-only tools" claim. A proposer with a read-only allowlist still holds a network client and still depends on an allowlist being maintained correctly; a proposer with `tools=[]` cannot reach anything at all, and `strict_mcp_config=True` means a stray `.mcp.json` in the working directory cannot quietly re-arm it. The breach is unreachable rather than forbidden, which is the whole argument this project makes.

**The critic was cut, deliberately.** Its specified job was to re-verify delta and credit on the chosen legs from a fresh snapshot. `risk.py` already does exactly that, deterministically, on the actual selected contracts — `gate_delta_band`, `gate_credit_quality`, `gate_minimum_credit`, `gate_quote_sanity` and `gate_greeks_present` all run against the resolved legs, not against the proposal. A second LLM pass could not veto anything the guard does not already veto, and it could not overrule the guard if it wanted to. It would have added a model call, a failure mode, and a latency budget to buy nothing.

**`.mcp.json` in the repo root is developer tooling, not the agent's runtime.** It configures `uvx alpaca-mcp-server` for a human's Claude Code session while working on this repo. `brain.py` never reads it — `mcp_servers={}` plus `strict_mcp_config=True` is precisely what guarantees that.

**CLI is the deterministic hands.** `clock`, `account get`, `position list`, `data option chain`, `order submit --order-class mleg`, plus explicit single-symbol closes — never a bulk operation. See "Constraints adopted from Alpaca's own skills" below.

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

**No new entries after Wed Sep 2, 10:45 ET (Wednesday is morning-only — see the risk-guard table below). All positions closed Thu Sep 3 via an escalation ladder starting 14:30 ET. Fri Sep 4 monitor-only.** Costs a day of P&L, buys a settled, honest, judgeable number.

---

## Risk guard

Pure functions, `(state, plan) -> str | None`. No I/O, no network; time is injected. Numbers live in `governance.json`, rendered verbatim in the dashboard beside the line "no LLM can write to this file". Implemented in `risk.py`, 44 passing tests across `test_agent.py` and `test_loop.py`.

`resolve_direction(proposal_direction)` runs before any of this, before a chain is even fetched — a bearish proposal is `NO_TRADE`, never a call-side substitution (canonical plan §6.1, `HARD_SAFETY`). Everything below assumes a `bull_put` plan already exists.

| Gate | Rule |
|---|---|
| `gate_paper_env` | Assert paper before **every** order path. Adopted from Alpaca's own 25 Aug commit. |
| `gate_kill_switch` | A `HALT` file rejects everything except closes. `touch HALT` is the human override. |
| `gate_account_ready` | Account status ∈ {ACTIVE, PAPER_ONLY}, not `trading_blocked`, effective options level ≥ 3 (the *minimum* of approved and configured max, not just approved). |
| `gate_vix_zone` | **Added, canonical plan.** VIX < 30 and VIX9D < VIX3M (contango). Entry-only — never blocks exits or liquidates an open position. |
| `gate_intraday_shock` | **Added, canonical plan.** \|intraday move\| < 2%. Entry-only, same as above. |
| `gate_event_blackout` | **Added, canonical plan.** Blocks entries around FOMC/CPI/PCE/NFP (Tier 1) and ISM/ADP/jobless claims (Tier 2), per the hand-verified `data/events_2026-08-31_2026-09-04.json`. A missing calendar fails closed. |
| `gate_greeks_present` | Both legs need non-null delta **and** IV. The 0DTE guard — structural, not a date check. |
| `gate_dte_window` | **6 ≤ DTE ≤ 9** (narrowed from 4–9, canonical plan), expiry ≠ today. |
| `gate_delta_band` | Short leg 0.16 ≤ \|delta\| ≤ 0.25. |
| `gate_credit_quality` | Reject if credit/width deviates more than ±40% from `0.8 × short_delta`. Catches a bad quote without vetoing the strategy — see the live-probe corrections below. |
| `gate_minimum_credit` | Absolute floor: credit ≥ 10% of width. `gate_credit_quality`'s own tolerance can pass a technically-in-band trade too thin to be worth the execution risk — this catches that case. |
| `gate_quote_sanity` | Per leg: bid > 0, ask > bid, spread ≤ 15% of mid, **quote age ≤ 60s (canonical plan; was unenforced dead config).** |
| `gate_vrp_present` | **Tightened, canonical plan.** ATM IV − 20-day realised vol ≥ 2.0 vol points (was a plain IV ≥ RV check). Operationalises the one edge this strategy claims — sell premium only when it's actually rich, not just barely above noise. |
| `gate_max_loss_per_trade` | `(width − credit) × 100 × qty ≤ $1,000`. Sizing itself is now fixed at exactly 1 contract (canonical plan §2.12) — this gate is a safety check, not a scaling formula. |
| `gate_total_open_risk` | Open + proposed ≤ $3,000. |
| `gate_concurrent` | **≤ 2 open** (narrowed from 3, canonical plan — SPY and QQQ are one correlated bucket), ≤ 1 per underlying, ≤ 2 new entries per session. |
| `gate_daily_fill_cap_per_underlying` | **Added, canonical plan.** A filled entry earlier today blocks a same-underlying re-entry later today, even if that spread already closed. |
| `gate_buying_power_floor` | Post-trade options BP ≥ $25,000 **and** ≥ 5 × max loss. Margin required is `width × 100 × qty` (verified live — NOT max loss). |
| `gate_daily_drawdown` | **−1%** from session-start (tightened from −2%, canonical plan) → no new entries today. |
| `gate_cumulative_drawdown` | Equity ≤ **$98,000** (tightened from $96,000, canonical plan) → **write `HALT`, then close each position individually by explicit order.** Never a bulk endpoint. Also fires on `trading_blocked` or three consecutive loop exceptions. |
| `gate_deadline` | Opens blocked after Wed Sep 2, **10:45 ET** (was wrongly 16:00 — Wednesday is morning-only, canonical plan §4.3: a spread needs runway before Thursday's flatten to cover its own bid-ask). From Thu Sep 3, **14:30 ET**, exits escalate: limit at mid → 15:00 cross the spread → 15:30 market `mleg` → 15:45 reconcile and alert (moved 30 min earlier across the board — the old ladder's forceful rung landed 10 minutes before the close). |

**Partial-fill unwind:** poll order status after submit; not fully filled in 60s → cancel remainder, flatten any orphan leg via an explicit order, then **recompute open risk from actual filled quantity.** This protects the entire "defined risk" claim and is the most important code in the repo.

**Idempotency:** every order gets a deterministic (non-random) `client_order_id` — `spread.client_order_id()` — computed from date/window/underlying/stage, always looked up (`alpaca.get_order_by_client_id`) before submitting. Verified live 29 Aug 2026: Alpaca rejects a resubmitted duplicate id with 422 `client_order_id must be unique` rather than creating a second order, which is what makes a crash-and-retry safe without a database — see [Strategy/architecture authority](#strategyarchitecture-authority--and-scoped-v1s-deliberate-deviations) above.

### Corrections from the live probe, 26 Aug 2026

A real 2-leg SPY credit spread was opened and closed on a paper account with the market open. Three things the original plan had wrong:

**1. The credit/width band of 0.20–0.45 would have vetoed every trade.** Observed on SPY at 765.55, 7 DTE, short leg at −0.197 delta, $5 wide: net credit **0.60 — a ratio of 0.120**. Widening makes it worse, not better; the ratio falls monotonically. Across the chain the relationship holds at roughly **credit/width ≈ 0.8 × short delta**. Recalibrated to a *relative* test.

**2. Margin held is the full width, not the max loss.** The fill consumed exactly **$500** of options buying power on one $5-wide contract — `width × 100 × qty` — while max loss was $443. Two different numbers.

**3. There is no arithmetic edge, and the write-up must say so.** Sweeping every strike from 0.15 to 0.45 delta across five widths, expected value is **negative in every case** — between −$4 and −$8 per contract, precisely the bid-ask cost. Delta *is* the risk-neutral probability, so a fairly-priced chain cannot yield edge by arithmetic. Confirmed live — the round trip cost **$7.10**.

The only edge premium selling can claim is the **variance risk premium**: implied vol has historically exceeded subsequent realised vol. At −0.197 delta the breakeven win rate is 88% against a risk-neutral 80%, so the strategy needs roughly eight points of VRP to break even. Real, but thin — and **six sessions cannot measure it.**

This is the honest thesis: the agent does not claim to predict the market. It harvests a documented structural premium under a hard risk cap, and reports its sample size truthfully.

**Validated end to end:** chain fetch with greeks · delta-based strike selection · mleg body with negative limit price · simultaneous 2-leg fill at price improvement · margin behaviour · exit via reverse mleg with positive limit · position closed and margin released.

### Fable 5 strategy review, 28 Aug 2026

Claude Fable 5 independently reviewed the final design (2-leg vertical, live-probe corrections included) as a second opinion before Monday's build. Scored **8/10** — Technology Implementation 9, Presentation & Execution 9, Creativity & Originality 8, P&L Performance 5 ("a coin flip weighted slightly your way by the credit floor and VRP gate; six sessions is noise, the design controls the left tail, not the sign"). Biggest named risk: a correlated SPY/QQQ down-move trips 2x-credit stops on multiple positions the same day — the drawdown gates cap the damage, not the sign of the week.

Five recommendations, two implemented same-day, three deferred to Monday's `brain.py`/`loop.py` build. **Status as of the 29 Aug canonical-plan review:**

- **Implemented:** `gate_minimum_credit` — 10%-of-width absolute credit floor (table above).
- **Superseded, not implemented:** the original DTE-preference recommendation (`dte_preferred_max: 6`, biasing toward 4-6 DTE) is gone. The canonical plan's own costed argument runs the other way — a 4-DTE spread entered Monday hits the 2-DTE time exit Wednesday and pays two bid-asks for two days of theta, while a 7–9 DTE spread held to Thursday's flatten never touches the time exit. `gate_dte_window` now hard-enforces **6–9**, and `loop.py` will enumerate every eligible expiry in that range and rank candidates (lowest quote friction → delta closest to 0.20 → largest DTE) rather than preferring one DTE over another.
- **Deferred — order-pricing discipline:** walk the limit price toward the NBBO mid over the poll window instead of a single static quote, to reduce the vig cost the live probe measured (~$7 round trip). Belongs in `loop.py`'s submission logic, not `risk.py` — it's an execution tactic, not a gate.
- **Killed, not deferred — legged-condor neutral mode:** the canonical plan is explicit (§4.7, `HARD_SAFETY`): *"Never both sides on the same underlying — that is a condor by another name."* A neutral proposal now just resolves to the same put credit spread as bullish (`resolve_direction`, above) — no second leg pair, no linked-exposure accounting needed in `gate_concurrent`.
- **Decided, not the original shape — partial-fill / naked-leg handling:** built in `loop.py`, but as detect-and-HALT, not the automated same-order repair originally sketched here. Every cancel now checks whether it actually won the race against a fill (Alpaca does not guarantee a cancel beats a fill in flight) and, if exactly one leg of a vertical ends up open alone, HALTs and journals CRITICAL rather than firing a fresh single-leg close order. Reason: `alpaca.py` has no single-leg order primitive, and shipping one untested days before the deadline is itself a real-money-shaped risk — a human closing it manually from a CRITICAL journal entry is safer than an unrehearsed auto-repair path for an event rare enough that this codebase has never exercised it live.

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
| `alpaca.py` | CLI subprocess wrapper, paper asserted at every call, one `ALPACA_PROFILE`-env-var mechanism | ✅ built |
| `spread.py` | Strike selection + mleg body construction + deterministic `client_order_id`. Pure. | ✅ built |
| `risk.py` | The gates (18 state-only + 3 sized) + `check_all()` + `exit_signal()` + `resolve_direction()`. Stdlib only. | ✅ built |
| `test_agent.py` + `test_loop.py` | 44 tests (32 + 12), fixtures from the real 26 Aug chain | ✅ built, all passing |
| `governance.json` | Every risk number, one place | ✅ built |
| `data/events_2026-08-31_2026-09-04.json` | Hand-verified FOMC/CPI/PCE/NFP/ISM/ADP/jobless-claims calendar for the trading week, sourced live against federalreserve.gov/bls.gov/ismworld.org/adpemploymentreport.com | ✅ built |
| `market.py` | State builder: bars → RV20, Cboe VIX-family CSV, chain, intraday move | ✅ built |
| `brain.py` | The one bounded proposer call, read-only, scrubbed env, fail-closed validator | ✅ built |
| `loop.py` | One tick: recovery/reconcile → exits → entry window → journal (the largest piece). Built by a 4-phase workflow whose adversarial 3-lens verify pass caught 6 real defects (2 blocker: dry_run didn't gate real cancels, no naked-leg/raced-fill handling existed) before anything was trusted — all 6 fixed directly, see the partial-fill note below. | ✅ built |
| `store.py` | SQLite read model derived from the journal: events + hash chain, folded positions, gate-rejection and equity-curve queries. Rebuildable, gitignored. | ✅ built |
| `test_store.py` | 27 tests — every query asserted against loop.py's own journal scan on identical input, plus chain tamper-detection and rebuild determinism | ✅ built, all passing |
| `app.py` | Streamlit dashboard, reads `store.py`. No network calls, no credentials — history only. | ✅ built |
| `test_app.py` | 23 tests — SVG geometry on the degenerate curves (no trades, one trade, flat), money-sign formatting, and full-page execution via Streamlit's `AppTest` on empty, populated and halted journals | ✅ built, all passing |
| `.streamlit/config.toml` | Theme matched to the diagrams; usage stats off | ✅ built |
| `.github/workflows/agent.yml` | One workflow: cron + `workflow_dispatch` + one `concurrency:` group | ✅ built |
| `env.example` | Documents the inverted `ALPACA_PAPER_TRADE` / `ALPACA_LIVE_TRADE` trap, and `ALPACA_ACCOUNT_ID` (now required for `assert_paper` on the submission profile) | ✅ built |
| `README.md` | The one-page write-up deliverable | not yet — Thursday |
| `docs/diagrams/*.html` | Architecture, sequence, flowchart — KBW skin | ✅ built |
| `social/drafts/` | Post drafts, PK posts manually from `@khaledalwaleed` | ✅ built, post 01 live |

**Dependencies — three:** `claude-agent-sdk`, `streamlit`, `pytest`.
**Not building:** a backtester, a *primary* database (SQLite is a derived read model only — see above), parallel research agents, streaming, a second strategy.

---

## Demo — Streamlit Community Cloud

Deployed from the repo, auto-redeploying on each push. **Primary view is history, not live state.** Judges review off-hours with the market shut.

1. Equity curve
2. Decision log — the proposer's thesis, the gate that vetoed (or that none did), proposed vs filled price per leg
3. **"Why no trade"** — gate rejections counted by reason
4. Open and closed positions with entry credit, exit reason, realised P&L
5. `governance.json` verbatim

---

## Timeline

**Fri 28 Aug from 11:00 ET** — create the **fresh submission** paper account, confirm $100,000, record the ID. **No manual orders on it, ever** — its history must be 100% agent-generated, because that history is what judges read as "autonomous." `alpaca.py` + first tests: done. Save a live chain snapshot as the test fixture: done.

**Sat 29 Aug** — market shut, commits still count. Empirically verified the core idempotency assumption live (a resubmitted duplicate `client_order_id` gets rejected, not duplicated) on the throwaway profile. Canonical-plan correctness fixes landed: `governance.json` + `risk.py` + `spread.py` + `alpaca.py` + the full test file — done, 30/30 passing at the time. Same day: `market.py`, `brain.py`, `loop.py`, and `.github/workflows/agent.yml` built via a 4-phase workflow; its adversarial verify pass caught 6 real `loop.py` defects (2 blocker) before anything was trusted, all fixed same-day — **44/44 passing**.

**Sat 29 Aug, later the same day** — full `--dry-run` rehearsal: ran clean twice, `ok: true`, journal committed and pushed to `origin/main`. Found and fixed one more real gap live: `HALT.json` was never git-published, so any HALT triggered on an ephemeral GitHub Actions runner would've been silently lost before the next tick's fresh checkout — fixed, verified by re-running. Live-gate sanity check: ran the full pipeline (market.py → spread.py → risk.py, plus a real `brain.propose` call — first live confirmation the LLM call works end to end) against real SPY/QQQ chains and real VIX/event data. Zero natural candidates, correctly — current deltas in the 6–9 DTE window (0.04–0.08) don't reach the 0.16–0.25 band given today's low realised/implied vol. Forced one real out-of-band candidate through `risk.check_all` directly to confirm the gate chain fires in order with correct math, through `gate_delta_band`. **Still open for Monday**: a natural pass-through of the later gates (credit_quality, quote_sanity, VRP, sizing) on real data, since nothing today cleared delta_band to reach them. The upstream options-spreads skill PR stays deprioritized behind all of this, per the canonical plan's own priority call.

**Sun 30 Aug** — market shut, no live verification possible. Everything that does not need a live chain: `app.py` and the Streamlit deploy (the hosted demo URL is a hard submission gate and was previously scheduled behind Monday's trading), the slide deck and 16:9 cover.

**Mon 31 Aug** — First autonomous cycle, first real spread (exactly 1 contract).
**Tue 1 Sep** — fix what live trading broke; verify the demo URL cold from outside, on a judge's-eye pass.
**Wed 2 Sep** — fix what live trading broke. **Last day for new entries.**
**Thu 3 Sep** — flatten via the escalation ladder. Media block: diagrams → deck → record → cut → write-up. `/security-review` before the repo goes public.
**Fri 4 Sep** — monitor-only. Final push. Submit before 11:00 ET.

Commit and push daily — a single final push reads as pre-built and is flagged in lablab's own guidance.

---

## Open risks

| Risk | Mitigation | Residual |
|---|---|---|
| Partial fill / naked leg after a cancel | Every cancel re-reads the order rather than assuming it won the race against a fill in flight; any resulting single-leg asymmetry (either side, entry or exit) HALTs and journals CRITICAL rather than being logged and ignored | No automated single-leg repair order — a human closes it manually; bounded by tick cadence (~5 min), not indefinite |
| Overnight assignment → naked stock | Orphan handler flattens via explicit order next tick | Up to ~15 min unhedged |
| Indicative quotes mis-price strikes | Limit only; recalibrated credit gate; quote-sanity gate; log quoted vs filled | P&L stays biased optimistic — reported as such |
| Actions cron drifts or drops a run | Off-hour schedule, `workflow_dispatch`, staleness logging | A skipped session; loss cap is unaffected |
| Streamlit cold start | Actions pings each tick | First-click spinner |
| Secrets in a public repo | `.gitignore` from commit one; Actions Secrets; `/security-review` before going public | — |
| Six sessions is not a sample | Write-up states n and claims nothing about edge | — |
| Ephemeral CI runner loses local state before publishing | Journal and HALT.json are git-published together every tick; a failed push now fails the tick loudly (`ok=False`, non-zero exit); a broker position the journal doesn't account for HALTs | A push failure still loses that tick's local writes -- the loudness only ensures a human notices quickly, not a recovery of the lost tick |

**Rollback:** `touch HALT` stops all opening. Flattening is position by position, by explicit order — never a bulk endpoint. The account is fresh, paper, funded with nothing real.

---

## Verification

1. `pytest -q` — currently 155/155 across `test_agent.py` (gates, mleg body shape, idempotency, chain parsing), `test_loop.py` (journal round-trip, HALT fail-closed, dry-run cancel gating, leg-symmetry/naked-leg HALT, exit attempt-id stability), and `test_store.py` (read-model parity with loop.py, hash chain, rebuild determinism) and `test_app.py` (dashboard geometry and full-page render).
2. `alpaca doctor` reports `https://paper-api.alpaca.markets`. Every session, non-negotiable.
3. `alpaca order submit --dry-run` before any live submit.
4. One full `loop.py --once --dry-run` that logs and sends nothing. **Done, 29 Aug** — twice, `ok: true` both times; found and fixed a real gap along the way (`HALT.json` wasn't being git-published, so it would've been silently lost on an ephemeral CI runner).
5. Force a veto against each gate; confirm it appears in the "Why no trade" panel. **Partly done, 29 Aug** — confirmed for `gate_delta_band` against a real out-of-band contract (correct rejection message, correct gate order up to that point). The remaining gates (credit_quality, quote_sanity, VRP, sizing) are order-verified by code path only, not yet individually forced against real data — closes naturally once a real candidate clears delta_band during Monday's market hours.
6. `browse` the Streamlit URL cold, from outside.
7. `/security-review` before the repo goes public.
