# Theta Gate — Trading Strategy, 28 Aug – 4 Sep 2026

**Status:** operating plan for the agent. Every number here is either already in `governance.json` or proposed for it in §11. The agent trades what this file says and nothing else.

**Source:** `docs/research/best-options-traders-1996-2026.md` (67-agent research run, adversarially verified) plus the Downloads comparison (28 Aug). The strategy family is the one with the only public, reproducible 40-year record on this instrument class: fully-collateralised index put-writing (Cboe PUT), gated the way the surviving institutional sellers gate it (Capstone, Dominicé, Warrington), managed with the retail rule set that has three independent replications (tastylive 16–25Δ / 50% take-profit).

---

## 1. Thesis, in four sentences

1. Index implied volatility has exceeded realised volatility by ~4.2 points on average since 1990. Selling a defined-risk put vertical collects that gap.
2. The gap is not always present. The agent sells only when it measures the gap on the day, on the surface it is selling.
3. On a fairly priced chain the arithmetic edge is zero minus the bid-ask. Every rule below exists to avoid paying the bid-ask for nothing.
4. Six sessions cannot measure edge. The deliverable is a process that survives, logs, and reports its sample size honestly.

---

## 2. Instrument

| Item | Rule | Why |
|---|---|---|
| Structure | 2-leg credit vertical. Never 3 or 4 legs. | ~10% of paper fills come back partial. A 4-leg order that half-fills is a naked short. Verified. |
| Underlyings | SPY, QQQ. Nothing else. | Deepest books, daily expiries, indicative quotes least wrong. Treated as **one correlated bucket** (§6). |
| Side | **Put credit spread by default.** Call credit spread only under §4.7. | Put-side premium is thicker (PUT beat BXM by 0.65–2.11%/yr, 1986–2014). Rallies killed Catalyst (2017) and 3 of Dominicé's 4 losing periods. |
| Width | $5. | Credit/width falls as width rises (5-wide 0.12 → 25-wide 0.056, verified). $5 is the best ratio and the margin is `width × 100`. |
| Short delta | 0.16–0.25, prefer the **upper half (0.20–0.25)**. | Israelov–Tummala: moderately OTM pays best per unit of stress loss. At 0.16 with the relative credit tolerance the credit can be ~$0.38 — too thin. |
| Long leg | Exactly one $5 strike further OTM. | Defined risk = width − credit. |
| DTE | 4–9. Prefer 7–9 at entry. Never open on expiry day. | Accepted violation of the evidence (tastylive 45/21, Dominicé 1–3 months, WPUT underperforms PUT). The six-session window forces it. Expected cost: more rolls, more gap exposure, bid-ask a larger share of credit. Logged as a constraint, not a finding. |
| Order | `mleg`, limit only, **negative `limit_price` = credit**, `client_order_id` set. | Market orders fill far off fair value on indicative quotes. |

---

## 3. Calendar — the five sessions

Times are ET. Entry windows are the first tick after **10:30** and after **13:30**. Nothing opens outside those windows.

| Date | Session | Entries | Exits | Notes |
|---|---|---|---|---|
| Fri 28 Aug | Kickoff 11:00 | **None** unless `loop.py` is live and passes `--dry-run`. Realistically none. | — | Create the fresh $100,000 account. Record the ID. No manual orders on it, ever. |
| Sat–Sun | Closed | — | — | Build `brain.py` + `loop.py`. Commits count. |
| Mon 31 Aug | Full | 10:30 and 13:30 windows. Max 2 new. | Deterministic exits every tick. | First autonomous cycle. First spread should be **1 contract** (§6.3). |
| Tue 1 Sep | Full | 10:30 and 13:30 windows. Max 2 new. | Every tick. | ISM Manufacturing 10:00 — the 10:30 window is after the print. Verify the calendar Monday night. |
| Wed 2 Sep | Full | **10:30 window only.** 13:30 window closed. | Every tick. | A spread opened at 13:30 Wed has ~1 session before forced close; the round-trip bid-ask (~$7/contract, verified) exceeds the theta it can collect. ADP 08:15 — before the window. |
| Thu 3 Sep | Flatten | **None.** | 15:00 limit at mid → 15:30 cross the spread → 15:50 market `mleg`. Position by position, explicit orders, never a bulk endpoint. | Jobless claims 08:30, ISM Services 10:00 — before flatten. Media block. |
| Fri 4 Sep | Monitor-only | **None.** | Only if something is still open (it must not be): close at 09:35. | NFP 08:30, 90 min before the 11:00 deadline. Verified against bls.gov. |

**Minimum hold rule (new).** A spread needs ≥ 2 sessions before forced close to cover its own bid-ask. This is why Wed 13:30 is closed. Sizing math: $0.60 credit at 7 DTE ≈ $0.085/day of theta; round trip costs ~$0.07. One session of theta does not pay for the exit.

---

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
Current rule: ATM IV ≥ 20-day realised vol.
**New rule:** ATM IV − RV20 ≥ **2.0 vol points**, computed on the surface being sold (put-side ATM IV for put spreads, call-side for call spreads). RV20 = annualised standard deviation of 20 close-to-close log returns from Alpaca daily bars.

Why 2.0: long-run average gap is 4.2 (Bondarenko 1990–2018); both reports independently landed on ≥ 2 as the floor. If IV and RV are both elevated and roughly equal (Dominicé's 2022 case), this rejects.

### 4.6 Strike outside the realised move (new: `gate_strike_outside_sigma`)
Distance from spot to the short strike must be ≥ RV20 × √(DTE/252) × spot. Peterffy: trade only where the market is out of line with your model. Prevents a 0.25-delta strike that sits inside a one-sigma realised move on a quiet-IV, jumpy-price day.

### 4.7 Direction and the call side (new: `gate_call_side`)
- Proposer direction `bullish` or `neutral` → put credit spread.
- Proposer direction `bearish` with conviction ≥ 0.7 → **no put spread on that underlying this window.** A call credit spread is permitted only if §4.5 passes on the call-side ATM IV **and** `gate_credit_quality` passes on the call chain. Otherwise: no trade, log `bearish_no_call_edge`.
- Never both sides on the same underlying (that is a condor by another name).

### 4.8 Credit (existing gates)
`gate_credit_quality` (credit/width within ±40% of 0.8 × short delta) → `gate_minimum_credit` (credit ≥ 10% of width = $0.50 on a $5 spread).

### 4.9 Size and exposure (existing gates, §6 arithmetic)
`gate_max_loss_per_trade` → `gate_total_open_risk` → `gate_concurrent` → `gate_buying_power_floor` → `gate_daily_drawdown` → `gate_cumulative_drawdown`.

### 4.10 Low-vol sizing guard (new: `gate_no_size_up_in_low_vol`)
Contracts on any new spread ≤ contracts on the previous spread in the same underlying **unless** RV20 today ≥ RV20 at that previous entry. The LJM rule: never increase size because realised vol fell.

### 4.11 Critic
Fresh-context LLM call re-fetches the **chosen legs** from a fresh snapshot and judges thesis and invalidation only. It cannot change strikes or size. A `reject` is final for the window.

---

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

Query order was changed from `[4..6 then 7..9]` to `[7,8,9,6,5,4]`. Reason: with flatten on Thursday, a Monday 7–9 DTE spread holds through Thursday and is never at 2 DTE; a Monday 4-DTE spread hits the 2-DTE time exit Wednesday and pays two bid-asks for two days of theta. `gate_dte_window` still enforces 4–9 as the hard bound.

---

## 6. Sizing — width-at-expiry, not the stop

### 6.1 Definitions
- **Max loss per contract** = (width − credit) × 100. On a $5 spread with $0.60 credit: **$440**.
- **Stop loss per contract** = 2 × credit × 100 = $120 (§7.2). The stop is where the agent *tries* to exit; the width is what it *can* lose on a gap.
- **Margin per contract** = width × 100 = $500 (verified live — not max loss).

### 6.2 Limits
| Limit | Value | Arithmetic |
|---|---|---|
| Max loss per spread | $1,000 | ⌊1000 / 440⌋ = **2 contracts** at $0.60 credit. `size_position()` already does this. |
| Max total open risk | $3,000 → **$2,000** (proposed) | SPY and QQQ are one bucket. Two spreads × $1,000 = $2,000. A third position in the same bucket adds correlated risk, not diversification. |
| Max concurrent | 3 → **2** (proposed) | One per underlying, two underlyings. |
| Max new per session | 2 | Unchanged. |
| Options BP floor | $25,000 and ≥ 5 × max loss | Unchanged. |
| Daily drawdown halt | −2% of session-start equity | Unchanged. Blocks new entries only. |
| Cumulative halt | Equity ≤ $96,000 | Unchanged. Writes `HALT`, closes position by position. |

### 6.3 First-trade rule (new)
The first spread the agent ever opens is **1 contract** regardless of what `size_position()` returns. It proves the fill path, the negative-price convention, the margin debit and the exit path with the smallest possible stake. Every spread after that uses the computed size.

### 6.4 Portfolio stress (new, informational)
Before each entry, compute and log the book's loss at underlying −5%, +5%, and at every open spread's full width. No gate — the width cap already bounds it — but the number goes in the journal and on the dashboard so the judges see the agent knows its worst case.

---

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
Keep 50% flat. (The research suggests scaling down near expiry; with the 2-DTE time exit and Thursday flatten there is no tail of the curve to scale into. One fewer knob.)

---

## 8. Execution

| Step | Rule |
|---|---|
| Price | Limit at the spread mid, rounded to $0.01. Maximum concession: $0.05 below mid on entry (credit), $0.05 above mid on exit. **Never chase beyond that.** |
| Sign | Entry: `limit_price` **negative** (credit). Exit: positive (debit). Test asserts this; keep the test. |
| Unfilled | 60 s → cancel. Re-propose next window, not next tick. |
| Partial fill | Cancel the remainder → if one leg filled alone, flatten it by explicit single-leg order immediately → recompute open risk from **actual filled quantity** → log `partial_fill_unwound`. This is the most important code in the repo. |
| Dry run | `alpaca order submit --dry-run` before every live submit. |
| Bulk endpoints | Never. `close_all_positions`, `cancel_all_orders`, `close_position` are not called anywhere. |
| Quote check | Both legs' quotes ≤ 600 s old at submit. Older → refetch, re-gate. |

---

## 9. The LLM's job, exactly

**Proposer** (read-only MCP: `get_news`, `get_market_movers`, `get_stock_snapshot`, `get_option_snapshot`, `get_clock`, `get_calendar`, docs tools). Returns one JSON object:

```json
{"underlying": "SPY|QQQ", "direction": "bullish|neutral|bearish",
 "conviction": 0.0-1.0, "dte": 4-9, "thesis": "<=60 words",
 "invalidation": "<=30 words, a price or event"}
```

It picks a direction and an underlying. It does not pick strikes, size, price or expiry beyond a DTE preference. It cannot see the order endpoint. A malformed object = no trade this window.

**Critic** (fresh context, same read-only tools). Receives the resolved `SpreadPlan`, re-fetches the two legs, returns `{"verdict": "accept|reject", "reason": "<=40 words"}`. It judges whether the thesis still holds against the fresh snapshot and whether the invalidation is already true. It cannot amend anything.

**Neither model** is consulted on exits, sizing, or during the regime rule. Both are logged verbatim.

---

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

---

## 11. Proposed `governance.json` changes

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

New gates to add to `risk.py`, each a pure `(state, plan, gov, now) -> str | None` with one test: `gate_vix_zone`, `gate_intraday_shock`, `gate_strike_outside_sigma`, `gate_call_side`, `gate_no_size_up_in_low_vol`. The tightened `gate_vrp_present` changes one comparison. Estimated: ~80 lines of code, 6 tests.

---

## 12. What can go wrong, and what the agent does

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

---

## 13. What is claimed, and what is not

**Claimed.** The agent harvests the put-side variance risk premium on SPY/QQQ, only when it measures the premium on the day, with loss capped at spread width by construction, and every exit by rule. The evidence for the premium is real and long-dated (Bondarenko 1990–2018, Bakshi–Kapadia, AQR 1996–2016, Cboe PUT 1986–2018).

**Not claimed.** That the premium is large — the retail-accessible versions (WPUT, CNDR, tastytrade replications, Warrington's audited funds, Dominicé's UCITS) earned 0–5%/yr gross before costs and several closed. That 4–9 DTE is the right tenor — it is not; the window forces it. That five sessions measure anything — at 50% take-profit each winner captures ~0.06 of width and one stop-loss costs ~4 winners; one full-width loss costs ~15. The number the judges see is a sample of n ≤ 8 and the write-up says so.

**The defensible deliverable** is the process: the gates, the width-defined sizing, the block-not-liquidate regime rule, the deterministic stops, and a journal a reader can grade without looking at P&L.
