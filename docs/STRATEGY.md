# Theta Gate — Strategy and Implementation Plan, 28 Aug – 4 Sep 2026

**Status:** the single operating document. Part I is what the agent trades. Part II is how it gets built, codified, and published this week. Every number in Part I is either already in `governance.json` or is added to it in §14. The agent trades what this file says and nothing else.

**Sources merged here:**
- `docs/research/best-options-traders-1996-2026.md` — 67-agent research run, adversarially verified. Picks the one strategy family with a public, reproducible 40-year record on this instrument class (Cboe PUT), gated the way the surviving institutional sellers gate it (Capstone, Dominicé, Warrington), managed with the retail rule set that has three independent replications (tastylive 16–25Δ / 50% take-profit).
- The Downloads comparison (28 Aug) — contributed the concrete thresholds (VRP ≥ 2 pts, IVR-style richness), the one-correlated-bucket rule, and the LJM "never size up in low vol" guard.
- The implementation plan (28 Aug) — Tracks A/B/C, the two conflict resolutions, the state-field contract between `loop.py` and the pure gates, the skill PR, sequencing and verification.

---

# Part I — The strategy

## 1. Thesis, in four sentences

1. Index implied volatility has exceeded realised volatility by ~4.2 points on average since 1990. Selling a defined-risk put vertical collects that gap.
2. The gap is not always present. The agent sells only when it measures the gap on the day, on the surface it is selling.
3. On a fairly priced chain the arithmetic edge is zero minus the bid-ask. Every rule below exists to avoid paying the bid-ask for nothing.
4. Six sessions cannot measure edge. The deliverable is a process that survives, logs, and reports its sample size honestly.

## 2. Instrument

| Item | Rule | Why |
|---|---|---|
| Structure | 2-leg credit vertical. Never 3 or 4 legs. | ~10% of paper fills come back partial. A 4-leg order that half-fills is a naked short. Verified. |
| Underlyings | SPY, QQQ. Nothing else. | Deepest books, daily expiries, indicative quotes least wrong. Treated as **one correlated bucket** (§6). |
| Side | **Put credit spread by default.** Call credit spread only under §4.7. | Put-side premium is thicker (PUT beat BXM by 0.65–2.11%/yr, 1986–2014). Rallies killed Catalyst (2017) and 3 of Dominicé's 4 losing periods. |
| Width | $5. | Credit/width falls as width rises (5-wide 0.12 → 25-wide 0.056, verified). $5 is the best ratio and the margin is `width × 100`. |
| Short delta | 0.16–0.25, target **0.22**. | Israelov–Tummala: moderately OTM pays best per unit of stress loss. At 0.16 with the relative credit tolerance the credit can be ~$0.38 — too thin. |
| Long leg | Exactly one $5 strike further OTM. | Defined risk = width − credit. |
| DTE | 4–9. Query order **[7, 8, 9, 6, 5, 4]**. Never open on expiry day. | Accepted violation of the evidence (tastylive 45/21, Dominicé 1–3 months, WPUT underperforms PUT). The six-session window forces it. Expected cost: more rolls, more gap exposure, bid-ask a larger share of credit. Logged as a constraint, not a finding. |
| Order | `mleg`, limit only, **negative `limit_price` = credit**, `client_order_id` set. | Market orders fill far off fair value on indicative quotes. |

## 3. Calendar — the five sessions

Times are ET. Entry windows are the first tick after **10:30** and after **13:30**. Nothing opens outside those windows.

| Date | Session | Entries | Exits | Notes |
|---|---|---|---|---|
| Fri 28 Aug | Kickoff 11:00 | **None.** | — | Create the fresh $100,000 account. Record the ID. No manual orders on it, ever. Track B codification lands today (§14–15). |
| Sat–Sun | Closed | — | — | Build `brain.py` + `loop.py` (§17). Sunday full `--dry-run` rehearsal. Commits count. |
| Mon 31 Aug | Full | 10:30 and 13:30 windows. Max 2 new. | Deterministic exits every tick. | First autonomous cycle. First spread is **1 contract** (§6.3). |
| Tue 1 Sep | Full | 10:30 and 13:30 windows. Max 2 new. | Every tick. | ISM Manufacturing 10:00 — the 10:30 window is after the print. Verify the calendar Monday night. |
| Wed 2 Sep | Full | **10:30 window only.** 13:30 window closed. | Every tick. | A spread opened at 13:30 Wed has ~1 session before forced close; the round-trip bid-ask (~$7/contract, verified) exceeds the theta it can collect. ADP 08:15 — before the window. |
| Thu 3 Sep | Flatten | **None.** | 15:00 limit at mid → 15:30 cross the spread → 15:50 market `mleg`. Position by position, explicit orders, never a bulk endpoint. | Jobless claims 08:30, ISM Services 10:00 — before flatten. Media block. |
| Fri 4 Sep | Monitor-only | **None.** | Only if something is still open (it must not be): close at 09:35. | NFP 08:30, 90 min before the 11:00 deadline. Verified against bls.gov. |

**Minimum hold rule.** A spread needs ≥ 2 sessions before forced close to cover its own bid-ask. This is why Wed 13:30 is closed. Arithmetic: $0.60 credit at 7 DTE ≈ $0.085/day of theta; round trip costs ~$0.07. One session of theta does not pay for the exit.

## 4. Entry gates — deterministic, in order, first rejection wins

The LLM proposes `{underlying, direction, conviction, dte, thesis, invalidation}`. Python does everything else. A rejection is logged with its reason to the "Why no trade" panel. The agent never retries a rejected plan in the same window.

### 4.1 Environment (existing gates)
`gate_paper_env` → `gate_kill_switch` → `gate_account_ready` → `gate_deadline`. Unchanged.

### 4.2 Regime — VIX zone (new: `gate_vix_zone`)
Data: Cboe daily CSVs, prior close. Free, verified reachable 28 Aug:
`https://cdn.cboe.com/api/global/us_indices/daily_prices/{VIX,VIX9D,VIX3M}_History.csv`

| Check | Threshold | Source of rule |
|---|---|---|
| VIX prior close | 12 ≤ VIX ≤ 30 | Warrington sold no puts in Mar 2020; below 12 the credit fails the minimum anyway. |
| Term structure | VIX9D < VIX3M (contango) | Inversion = event or stress being priced short-dated. Warrington/Dominicé sit out. |
| Feed freshness | CSV last row = prior trading day | Stale feed → no entry, log `vix_feed_stale`. |

At 27 Aug close: VIX 14.51, VIX9D 12.10, VIX3M 17.56 — passes.

### 4.3 Regime — intraday shock (new: `gate_intraday_shock`)
From Alpaca bars on the underlying: if |today's move from prior close| > 2.0% at the entry tick → no new entries this session. This **blocks entries; it never liquidates** open spreads (§7.4).

### 4.4 Chain and contract (existing gates)
`gate_greeks_present` (both legs have delta and IV — the structural 0DTE guard) → `gate_dte_window` → `gate_delta_band` → `gate_quote_sanity` (bid > 0, ask > bid, spread ≤ 15% of mid, quote age ≤ 600 s).

### 4.5 Variance risk premium (tightened: `gate_vrp_present`)
Old rule: ATM IV ≥ 20-day realised vol.
**New rule:** ATM IV − RV20 ≥ **2.0 vol points**, computed on the surface being sold (put-side ATM IV for put spreads, call-side for call spreads). RV20 = annualised standard deviation of 20 close-to-close log returns from Alpaca daily bars.

Why 2.0: long-run average gap is 4.2 (Bondarenko 1990–2018); both research reports independently landed on ≥ 2 as the floor. If IV and RV are both elevated and roughly equal (Dominicé's 2022 case), this rejects.

### 4.6 Strike outside the realised move (new: `gate_strike_outside_sigma`)
Distance from spot to the short strike must be ≥ RV20 × √(DTE/252) × spot. Peterffy: trade only where the market is out of line with your model. Prevents a 0.25-delta strike that sits inside a one-sigma realised move on a quiet-IV, jumpy-price day.

### 4.7 Direction and the call side (new: `gate_call_side`)
- Proposer direction `bullish` or `neutral` → put credit spread.
- Proposer direction `bearish` with conviction ≥ 0.7 → **no put spread on that underlying this window.** A call credit spread is permitted only if §4.5 passes on the call-side ATM IV **and** `gate_credit_quality` passes on the call chain. Otherwise: no trade, log `bearish_no_call_edge`.
- Never both sides on the same underlying (that is a condor by another name). The earlier "neutral → both sides" idea is dead — see §20.

### 4.8 Credit (existing gates)
`gate_credit_quality` (credit/width within ±40% of 0.8 × short delta) → `gate_minimum_credit` (credit ≥ 10% of width = $0.50 on a $5 spread).

### 4.9 Size and exposure (existing gates, §6 arithmetic)
`gate_max_loss_per_trade` → `gate_total_open_risk` → `gate_concurrent` → `gate_buying_power_floor` → `gate_daily_drawdown` → `gate_cumulative_drawdown`.

### 4.10 Low-vol sizing guard (new: `gate_no_size_up_in_low_vol`)
Contracts on any new spread ≤ contracts on the previous spread in the same underlying **unless** RV20 today ≥ RV20 at that previous entry. The LJM rule: never increase size because realised vol fell.

### 4.11 Critic
Fresh-context LLM call re-fetches the **chosen legs** from a fresh snapshot and judges thesis and invalidation only. It cannot change strikes or size. A `reject` is final for the window.

## 5. Strike and expiry selection — the algorithm

```
for expiry in expiries where 4 <= DTE <= 9, ordered [7,8,9,6,5,4]:      # top of range first
    chain = option chain snapshot(underlying, expiry, side)
    contracts = parse_chain(chain)                                        # drops one-sided quotes
    short = the contract with |delta| closest to 0.22 within [0.16, 0.25]
    if none: continue
    long  = short.strike ∓ 5.00 (puts: minus; calls: plus), must exist with two-sided quote
    if none: continue
    credit = short.mid - long.mid
    plan = SpreadPlan(...)
    if all gates pass: return plan
return None  # log the last rejection reason
```

Query order was reversed from yesterday's `dte_preferred_max: 6` (bias 4–6). With flatten on Thursday, a Monday 7–9 DTE spread holds through Thursday and never touches the 2-DTE time exit; a Monday 4-DTE spread hits it Wednesday and pays two bid-asks for two days of theta. `gate_dte_window` still enforces 4–9 as the hard bound.

## 6. Sizing — width-at-expiry, not the stop

### 6.1 Definitions
- **Max loss per contract** = (width − credit) × 100. On a $5 spread with $0.60 credit: **$440**.
- **Stop loss per contract** = 2 × credit × 100 = $120 (§7.2). The stop is where the agent *tries* to exit; the width is what it *can* lose on a gap.
- **Margin per contract** = width × 100 = $500 (verified live — not max loss).

### 6.2 Limits
| Limit | Value | Arithmetic |
|---|---|---|
| Max loss per spread | $1,000 | ⌊1000 / 440⌋ = **2 contracts** at $0.60 credit. `size_position()` already does this. |
| Max total open risk | **$2,000** (was $3,000) | SPY and QQQ are one bucket. Two spreads × $1,000 = $2,000. A third position in the same bucket adds correlated risk, not diversification. |
| Max concurrent | **2** (was 3) | One per underlying, two underlyings. |
| Max new per session | 2 | Unchanged. |
| Options BP floor | $25,000 and ≥ 5 × max loss | Unchanged. |
| Daily drawdown halt | −2% of session-start equity | Unchanged. Blocks new entries only. |
| Cumulative halt | Equity ≤ $96,000 | Unchanged. Writes `HALT`, closes position by position. |

### 6.3 First-trade rule
The first spread the agent ever opens is **1 contract** regardless of what `size_position()` returns. It proves the fill path, the negative-price convention, the margin debit and the exit path with the smallest possible stake. Implemented as a clamp in `loop.py` (journal shows zero fills ever → qty = 1), not as a gate. Every spread after that uses the computed size.

### 6.4 Portfolio stress (informational)
Before each entry, compute and log the book's loss at underlying −5%, +5%, and at every open spread's full width. No gate — the width cap already bounds it — but the number goes in the journal and on the dashboard so the judges see the agent knows its worst case.

## 7. Exits — deterministic, no LLM, evaluated every tick

Priority order. The first rule that fires wins.

### 7.1 Orphan check (first, always)
Any **equity** line in positions = overnight assignment of a short leg. Flatten it by an explicit order before anything else. Then close the surviving long leg. Log `orphan_flattened`.

### 7.2 Per-position rules
| Rule | Trigger | Order |
|---|---|---|
| Take profit | Spread mark ≤ 50% of entry credit | Reverse `mleg`, limit at mid (positive price = debit) |
| Stop loss | Spread mark ≥ 2.0 × entry credit | Reverse `mleg`, limit at mid; if unfilled 60 s → re-submit crossing the spread |
| Time exit | DTE ≤ 2 | Reverse `mleg`, limit at mid |
| Deadline ladder | Thu 3 Sep 15:00 / 15:30 / 15:50 | mid → cross → market `mleg` |

Marks come from live bid/ask of both legs, never from the activities endpoint (lands next day) and never from indicative model values.

### 7.3 No rolling
A spread that hits its stop is closed. It is never rolled, never widened, never "repaired." No re-entry on the same underlying in the same session. This is the Bruton / Hope Advisors rule and it is absolute.

### 7.4 Regime rule — block, do not liquidate
If VIX (prior close) > 30, or §4.3 fires, or VIX9D > VIX3M: **no new entries.** Open spreads are left to §7.2. Buying back into a spike is the Capstone-2008 / LJM / Malachite mechanism; the width already caps the loss and the 2× stop handles the rest.

### 7.5 Take-profit scaling
Keep 50% flat. The research suggests scaling down near expiry; with the 2-DTE time exit and Thursday flatten there is no tail of the curve to scale into. One fewer knob.

## 8. Execution

| Step | Rule |
|---|---|
| Price | Limit at the spread mid, rounded to $0.01. Maximum concession: $0.05 below mid on entry (credit), $0.05 above mid on exit. **Never chase beyond that.** |
| Sign | Entry: `limit_price` **negative** (credit). Exit: positive (debit). Test asserts this; keep the test. |
| Unfilled | 60 s → cancel. Re-propose next window, not next tick. |
| Partial fill | Cancel the remainder → if one leg filled alone, flatten it by explicit single-leg order immediately → recompute open risk from **actual filled quantity** → log `partial_fill_unwound`. This is the most important code in the repo, and the skill (§18) documents it the same way. |
| Dry run | `alpaca order submit --dry-run` before every live submit. |
| Bulk endpoints | Never. `close_all_positions`, `cancel_all_orders`, `close_position` are not called anywhere. |
| Quote check | Both legs' quotes ≤ 600 s old at submit. Older → refetch, re-gate. |

## 9. The LLM's job, exactly

**Proposer** (read-only MCP: `get_news`, `get_market_movers`, `get_stock_snapshot`, `get_option_snapshot`, `get_clock`, `get_calendar`, docs tools). Returns one JSON object:

```json
{"underlying": "SPY|QQQ", "direction": "bullish|neutral|bearish",
 "conviction": 0.0-1.0, "dte": 4-9, "thesis": "<=60 words",
 "invalidation": "<=30 words, a price or event"}
```

It picks a direction and an underlying. It does not pick strikes, size, price or expiry beyond a DTE preference. It cannot see the order endpoint. A malformed object = no trade this window. Validation is hand-rolled, fail-closed. MCP failure → CLI-context fallback → if that fails too, `no_trade`.

**Critic** (fresh context, same read-only tools). Receives the resolved `SpreadPlan`, re-fetches the two legs, returns `{"verdict": "accept|reject", "reason": "<=40 words"}`. It judges whether the thesis still holds against the fresh snapshot and whether the invalidation is already true. It cannot amend anything.

**Neither model** is consulted on exits, sizing, or during the regime rule. Both are logged verbatim.

## 10. Journal — written before the fill, graded after without P&L

Every proposal, accepted or rejected, appends one line to `journal.jsonl`:

```
ts, underlying, side, direction, conviction, thesis, invalidation,
vix, vix9d, vix3m, rv20, atm_iv, vrp_points, short_delta, short_strike,
long_strike, dte, expiry, quoted_credit, quoted_mid_per_leg,
qty, max_loss, margin, gate_result (pass | first_failing_gate),
critic_verdict, order_id, filled_credit, fill_latency_s, partial (bool),
stress_minus5, stress_plus5, exit_rule, exit_price, realised_pnl
```

After Thursday's flatten, the log is graded on process: did every entry pass every gate, was every exit by rule, were any fills partial, what was quoted-vs-filled slippage. Only after that grade is P&L read. SIG reviews trades outcome-blind for the same reason.

**Benchmark for the write-up:** report the run's return alongside Cboe PUT and PUTY for the same five days and a 50/50 SPY/T-bill mix. State n. Claim nothing about edge.

## 11. What can go wrong, and what the agent does

| Failure | Detection | Response |
|---|---|---|
| Gap through the short strike overnight | Mark ≥ 2× credit at 09:35 tick | Stop-loss exit at mid, then cross. Loss bounded by width. Log it. No re-entry that session. |
| Overnight assignment | Equity line in positions | §7.1 orphan flatten, first thing every tick. |
| Partial fill | Order status ≠ filled at 60 s | §8 unwind. Risk recomputed from filled qty. |
| VIX feed down | CSV last row ≠ prior trading day | No entries. Exits unaffected. |
| Cron dropped a tick | Tick gap > 45 min | Log staleness. Loss cap is unaffected — it was fixed at entry. |
| Three loop exceptions in a row | Counter in state | Write `HALT`. Close positions individually. |
| Human wants it stopped | `touch HALT` | No opens. Closes still allowed. |
| Equity ≤ $96,000 | `gate_cumulative_drawdown` | `HALT` + close position by position. |

## 12. What is claimed, and what is not

**Claimed.** The agent harvests the put-side variance risk premium on SPY/QQQ, only when it measures the premium on the day, with loss capped at spread width by construction, and every exit by rule. The evidence for the premium is real and long-dated (Bondarenko 1990–2018, Bakshi–Kapadia, AQR 1996–2016, Cboe PUT 1986–2018).

**Not claimed.** That the premium is large — the retail-accessible versions (WPUT, CNDR, tastytrade replications, Warrington's audited funds, Dominicé's UCITS) earned 0–5%/yr gross before costs and several closed. That 4–9 DTE is the right tenor — it is not; the window forces it. That five sessions measure anything — at 50% take-profit each winner captures ~0.06 of width and one stop-loss costs ~4 winners; one full-width loss costs ~15. The number the judges see is a sample of n ≤ 8 and the write-up says so.

**The defensible deliverable** is the process: the gates, the width-defined sizing, the block-not-liquidate regime rule, the deterministic stops, and a journal a reader can grade without looking at P&L.

---

# Part II — Implementation

Three tracks, in execution order. **Track B** codifies Part I into `governance.json` and `risk.py` before any code depends on the old numbers. **Track C** builds `brain.py` + `loop.py` on top. **Track A** authors and publishes the options-spreads skill upstream, and vendors it back so the running agent and the public artifact stay in sync.

## 13. Sequencing

| When | What |
|---|---|
| Fri 28 Aug | Track B: §14 governance diff, §15 gates + tests, §16 doc updates. Commit + push. Then Track A draft + verification workflow + PR (§18). Fresh submission account created; untouched until Monday. |
| Sat–Sun 29–30 Aug | Track C build (§17). Sunday `loop.py --once --dry-run` rehearsal against the live read-only chain. Skill live-log updates if verification found anything. |
| Mon 31 Aug | First autonomous cycle. **First spread 1 contract.** |
| Tue 1 Sep | `app.py`, deploy Streamlit, verify the URL cold from outside. |
| Wed 2 Sep | Fix what live trading broke. Last entries (10:30 window). |
| Thu 3 Sep | Flatten via the ladder. Media block: diagrams → deck → record → cut → write-up. `/security-review` before the repo goes public. |
| Fri 4 Sep | Monitor-only. Final push. Submit before 11:00 ET. |

## 14. Track B1 — `governance.json` diff (apply verbatim)

```diff
 "strategy": {
-    "_dte_preference_comment": "... bias expiration selection to 4-6 DTE ...",
-    "dte_preferred_max": 6,
+    "_dte_preference_comment": "STRATEGY.md §5: query order [7,8,9,6,5,4]. Flatten is Thu 3 Sep; a Monday 4-DTE spread hits the 2-DTE exit Wednesday and pays two bid-asks for two days of theta.",
+    "dte_query_order": [7, 8, 9, 6, 5, 4],
+    "short_delta_target": 0.22,
+    "default_side": "put",
+    "call_side_requires_call_surface_gates": true,
+    "bearish_conviction_blocks_puts": 0.7
 },
 "entry": {
     "windows_et": ["10:30", "13:30"],
     "max_new_entries_per_session": 2,
     "no_entries_after_date": "2026-09-02",
-    "no_entries_after_time_et": "16:00",
+    "no_entries_after_time_et": "12:00",
+    "_min_hold_comment": "STRATEGY.md §3: a spread needs >= 2 sessions before forced close to cover its own round-trip bid-ask (~$7/contract verified). Wed 13:30 window closed.",
+    "first_trade_qty": 1,
+    "no_size_up_when_rv20_falls": true
 },
 "risk": {
     "max_loss_per_trade_dollars": 1000,
-    "max_total_open_risk_dollars": 3000,
-    "max_concurrent_positions": 3,
+    "max_total_open_risk_dollars": 2000,
+    "max_concurrent_positions": 2,
+    "_bucket_comment": "SPY and QQQ are one correlated bucket. Two positions max, one per underlying.",
     ...
 },
 "vrp": {
     "realised_vol_lookback_days": 20,
-    "require_atm_iv_gte_realised_vol": true
+    "require_atm_iv_gte_realised_vol": true,
+    "min_iv_minus_rv_vol_points": 2.0,
+    "measure_on_side_being_sold": true,
+    "short_strike_outside_rv_sigma": true
 },
+"regime": {
+    "_comment": "Blocks NEW entries only. Never liquidates open defined-risk spreads (STRATEGY.md §7.4).",
+    "vix_source": "https://cdn.cboe.com/api/global/us_indices/daily_prices/",
+    "vix_prior_close_min": 12,
+    "vix_prior_close_max": 30,
+    "require_contango_vix9d_lt_vix3m": true,
+    "intraday_underlying_move_block_pct": 0.02,
+    "stale_feed_blocks_entry": true
+},
```

## 15. Track B2 — `risk.py` gates and the state contract

Gates stay pure: `(state, plan, gov, now) -> str | None`. `loop.py` fetches everything and puts it in `state`; no gate does I/O. Wired into `_STATE_ONLY_GATES` (or the sized group) in §4's order.

| Gate | Reads | Supplied by | Rejects when |
|---|---|---|---|
| `gate_vix_zone` (new) | `state.vix`, `state.vix9d`, `state.vix3m`, `state.vix_feed_fresh` | `loop.py` from the three Cboe CSVs, prior close | VIX outside [12, 30], or VIX9D ≥ VIX3M, or feed stale |
| `gate_intraday_shock` (new) | `state.underlying_move_pct` | `loop.py` from Alpaca bars (today vs prior close) | \|move\| > 0.02 |
| `gate_strike_outside_sigma` (new) | `state.spot`, `state.realised_vol_20d`, `plan.short.strike`, `plan.dte` | `loop.py` (RV20 from 20 daily closes) | \|spot − short_strike\| < RV20 × √(DTE/252) × spot |
| `gate_call_side` (new) | `plan.direction`, `plan.conviction`, `plan.side`, `state.atm_iv_call`, call-chain credit quality | proposer JSON carried on `SpreadPlan` (extend the dataclass; smallest diff wins) | bearish ≥ 0.7 with a put plan; or a call plan whose call surface fails §4.5 / credit quality |
| `gate_vrp_present` (tightened) | `state.atm_iv` (for the side being sold), `state.realised_vol_20d` | `loop.py` supplies the sold surface's ATM IV | atm_iv − rv20 < 2.0 |
| `gate_no_size_up_in_low_vol` (new, sized group) | `qty`, `state.last_entry[underlying] = {qty, rv20}` | `loop.py` from the journal | qty > last qty and rv20 < last rv20 |
| First-trade clamp (not a gate) | journal fill count | `loop.py` after `size_position()` | zero fills ever → qty = 1 |

**Tests** (`test_agent.py`): one per new gate, one for the tightened VRP, one for the first-trade clamp — ~7 new, on top of 16 existing. `base_state()` extends with the new fields using the real 27 Aug values (VIX 14.51, VIX9D 12.10, VIX3M 17.56 → zone passes). The `GOV` dict gets every field in §14. Risk-cap tests re-checked against 2000 / 2. One end-to-end `check_all` test with all new state fields populated. Estimated ~80 lines of code.

## 16. Track B3 — documentation updates

- `docs/PLAN.md`: point the strategy section at this file as the operating authority; extend the gate table by the five new gates; note the DTE reversal and why; strike the deferred "neutral → both sides" item (§20).
- Commit + push the same day.

## 17. Track C — `brain.py` + `loop.py` (Sat–Sun)

**`loop.py --once` tick order** (mirrors §7 priority):

1. `clock` → closed? journal one line, exit.
2. Orphan check (§7.1) — any equity line → flatten by explicit order.
3. Deterministic exits (§7.2): 50% TP → 2× stop (60 s at mid, then cross) → 2 DTE → Thursday ladder.
4. State build: account, positions, **Cboe VIX/VIX9D/VIX3M CSVs**, **RV20 from Alpaca daily bars**, intraday move, ATM IV per sold side, `last_entry` per underlying from the journal.
5. Entry — only in the 10:30 / 13:30 windows, Wed 10:30 only (§3): proposer → resolve (§5) → critic → `check_all` → first-trade clamp → `--dry-run` → submit → poll → partial-fill unwind (§8).
6. Journal line (§10 schema) written **before** the fill, including stress −5% / +5% (§6.4).
7. `git commit` + `push` with pull-rebase retry.

**`brain.py`** (§9): proposer JSON, read-only MCP allowlist (never `place_option_order`, `close_position`, or any bulk tool), hand-rolled fail-closed validator; critic fresh-context accept/reject that amends nothing; MCP failure → CLI-context fallback → `no_trade`.

**Execution** (§8): limit at mid, max $0.05 concession, never chase; 60 s cancel → re-propose next window; partial-fill unwind exactly as the skill documents it; `--dry-run` before every submit.

**`.github/workflows/agent.yml`**: cron `:07 :22 :37 :52`, 13:30–20:00 UTC, Mon–Fri, plus `workflow_dispatch`. Best-effort scheduler; a dropped tick cannot exceed the loss cap fixed at entry. Sunday: a full `--dry-run` rehearsal run.

## 18. Track A — the `alpaca-trading-options-spreads` skill

### 18.1 Verified upstream constraints (checked live 28 Aug)
- Name **`alpaca-trading-options-spreads`** (validator regex `^alpaca-(trading|broker)-[a-z0-9-]+$`; the old working name fails CI). Path `skills/trading-api/options-spreads/` with exactly `SKILL.md` + `reference.md`.
- Frontmatter: `name` + folded `description` only. Secret scanner rejects `PK[A-Z0-9]{18,}` outside placeholder context.
- Body follows their paper-trading template: `## 0 -` … `## 10 -` sections, two-actor voice, `**Step N** —` continuous numbering, anti-pattern table, byte-identical disclosure blockquote, companion-skills table. Fences: `bash` CLI long-form, `json` string numerics, untagged box-drawing previews.
- No options skill upstream; two open community PRs, neither touches options. The gap is still open.

### 18.2 Content
`SKILL.md` (~600–800 lines): §0 agent-use rules · §1 prerequisites (effective `options_trading_level`, paper defaults to level 3, free plan has greeks/IV) · §2 inputs + 0DTE-no-greeks exclusion · §3 sources · §4 workflow (chain → delta-band strikes → `mleg` body → preview → submit → poll → **partial-fill repair** → reverse-`mleg` close → assignment orphan) · §5 execution rules led by the live-verified corrections (**negative `limit_price` = credit**; **margin = width × 100, not max loss**; **a partial `mleg` fill manufactures the naked short their docs say cannot exist**; 15:30 ET expiry-day cutoff; indicative quotes → limit only) · §6 output contract · §7 validation · §8 disclosures · §9 anti-patterns incl. their MCP `mleg` contradiction · §10 related skills.

`reference.md`: full `mleg` body schema, OCC symbology, margin / max-loss formulas, the credit ≈ 0.8 × |Δ| curve, error table, **dated live-findings log** (starts with the 26 Aug probe; this week's findings append as they happen).

### 18.3 Mechanism
1. **Draft via `skill-creator`** — authoring and structuring passes only; skip its eval-harness / interview loop. The upstream template and validator win every layout conflict.
2. **Workflow verification** (~15–25 agents): claim extraction → 3-lens verify fan-out (vendored skill texts / read-only live paper probes on the throwaway profile / our tested code) → style-compliance audit → `validate_skills.py` + secret grep. Zero WRONG claims survive.
3. Fork `alpacahq/alpaca-skills` as `Kalwaleed`, branch `feat/options-spreads-skill`, add the README table row, CI green, open the PR (their template; hackathon context stated plainly; standard attribution).
4. Vendor back into theta-gate `.agents/skills/` + a `skills-lock.json` entry.

### 18.4 Live-agility protocol
New live finding → dated log entry + section patch → re-run the verify workflow scoped to the changed claims (resume caches the rest) → commit theta-gate **and** push to the PR branch. One mechanism updates the running agent and the public artifact together.

## 19. Verification

1. `pytest -q` green — 16 existing (adjusted to 2000 / 2) + ~7 new.
2. `python3 -c "import json; json.load(open('governance.json'))"` and one end-to-end `check_all` test passing with every new state field.
3. Each new gate force-fed a failing input appears in the journal and the "Why no trade" panel with its named reason.
4. `alpaca doctor` reports `https://paper-api.alpaca.markets`. Every session, non-negotiable.
5. Sunday: `loop.py --once --dry-run` completes a full tick against the live read-only chain, journals, sends nothing.
6. Skill: `validate_skills.py` green in the fork, every claim CONFIRMED or cut, style audit clean, PR open with `skill-check` CI green.
7. `browse` the Streamlit URL cold, from outside (Tue).
8. `/security-review` before the repo goes public (Thu).

## 20. Decisions baked in

| Decision | Resolution | Why |
|---|---|---|
| DTE preference | **Reversed.** Yesterday's `dte_preferred_max: 6` (bias 4–6) → query order `[7,8,9,6,5,4]`. | A Monday 4-DTE spread hits the 2-DTE exit Wednesday and pays two bid-asks for two days of theta; a 7–9 DTE spread held to Thursday flatten never touches the time exit. Concrete and costed. |
| "Neutral → both sides" (legged condor) | **Dead.** Neutral maps to a put credit spread. | §4.7: never both sides on the same underlying. It is a condor by another name, with the 4-leg partial-fill risk delivered in two instalments. |
| Bucket | SPY + QQQ = one correlated bucket: 2 positions, $2,000 open risk. | Feb 2018 precedent; the third position adds correlated risk, not diversification. |
| Hedge sleeve | **Not this week.** Reinstate post-hackathon as a fixed dollar line (one 30–60 DTE SPY put debit spread per month, short leg 7–10% OTM), monetised on a VIX rule, never funded by selling more spreads, never switched off because it bled. | In six sessions it has no exit path and the width already caps every open loss. Over years it is the SIG / Capstone lesson. |
| Skill PR | Opens now, from `Kalwaleed`, hackathon context disclosed; live-week findings land as PR-branch commits. | The gap upstream is open; the live corrections are the value. |
| Probes | All verification probes read-only, throwaway profile only. The submission account is untouched until Monday's first autonomous cycle. | Its history must be 100% agent-generated. |
