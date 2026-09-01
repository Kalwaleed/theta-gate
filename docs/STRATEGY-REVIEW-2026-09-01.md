# Strategy review — decision tree, 1 Sep 2026

Written pre-market Tuesday, at PK's request, after a fair criticism: *"you have a
very weak decision tree where you should be able to use the data you're
collecting and have different strategies."*

That is correct. This is the review.

---

## 1. The finding, stated plainly

**The agent has 21 gates and no strategy selector.**

Every gate answers *"should I trade?"* Not one answers *"what should I trade?"*
There is exactly one terminal outcome in the whole tree:

```
risk.py:  return "bull_put"   x1
          return "bear_call"  x0
```

`resolve_direction` maps the model's three possible answers like this:

| model says | agent does |
|---|---|
| `bullish` | sell a put credit spread |
| `neutral` | sell a put credit spread |
| `bearish` | **no trade** |

Two of three answers produce the identical position. The model is not choosing a
strategy — it is choosing whether to trade at all. And over four live proposals
on 31 Aug it answered `neutral` every time, with confidence 0.60, 0.60, 0.60,
0.62. **The AI's output has so far carried no information the system acted on.**

That is the weakness. It is real, and the criticism landed.

---

## 2. Why it is locked — three layers, not one

Enabling a second strategy is not one function call:

| # | Location | What it does |
|---|---|---|
| 1 | `market.py:281` | `option_type="put"` is **hardcoded**. The call chain is never fetched. |
| 2 | `risk.py:71-74` | `resolve_direction` refuses `bear_call` — `HARD_SAFETY`, canonical §6.1 |
| 3 | `loop.py:428` | The exit path assumes `option_type` is always a put |

Layer 1 is the important one and it is easy to miss. **Because calls are never
fetched, put/call skew cannot be computed at all** — the single most useful
signal for choosing *which side* to sell is not merely unused, it is never
collected.

The good news: `spread.py` already builds `bear_call` verticals completely
(`pick_spread`, `closing_mleg_body`, the strike geometry), and `gate_delta_band`
and `gate_credit_quality` already use `abs(delta)`, so they are sign-agnostic and
would accept call-side plans unchanged. The strategy is roughly 70% built and
switched off.

---

## 3. Data collected every tick, and what is done with it

| Field | Collected | Used for |
|---|---|---|
| `spot`, `prior_close` | yes | intraday move |
| `intraday_move_pct` | yes | `gate_intraday_shock` (binary veto) |
| `realised_vol` (10d) | yes | `gate_vrp_present` (binary veto) |
| ATM IV | yes | `gate_vrp_present` (binary veto) |
| `vix`, `vix9d`, `vix3m` | yes | `gate_vix_zone` (binary veto) |
| Per-strike `delta` | yes | strike selection, `gate_delta_band` |
| Per-strike `iv` | yes | **nothing** — parsed and discarded |
| Per-strike bid/ask | yes | `gate_quote_sanity`, pricing |
| Call-side anything | **no** | — |

Every regime input is reduced to a **boolean veto**. `vix9d < vix3m` is a
yes/no. IV − RV is a yes/no against a 1.0-point floor. The *magnitude* of the
variance risk premium — the one edge this strategy claims — is measured, thresholded,
and then thrown away.

---

## 4. Strategy inventory

| Strategy | State | Assessment |
|---|---|---|
| **Short put vertical** | live | Correct default. Positive theta, ~80% win rate, defined risk. |
| **Short call vertical** | built, blocked | ~70% done. Needs call chain + `resolve_direction` + exit fix. The obvious next branch. |
| **Iron condor** | forbidden | `HARD_SAFETY` §4.7: *"Never both sides on the same underlying — that is a condor by another name."* Correct: 4 legs means partial fills manufacture naked shorts, the largest documented P&L risk. **Do not revisit.** |
| **Long premium (debit spreads, straddles)** | absent | The *correct* trade when IV < RV — precisely the regime `gate_vrp_present` currently answers with "no trade". Today the agent sits out a tradeable condition. |
| **Ratio / broken-wing** | absent | Undefined risk on one side. Incompatible with the entire defined-risk thesis. Do not build. |

---

## 5. The decision tree as it should be

Regimes are all computable from data already collected, **except skew**, which
needs the call fetch.

```
                        ┌─ VIX >= 30 ...................... NO TRADE  (correct today)
                        ├─ event blackout ................. NO TRADE  (correct today)
                        ├─ |intraday move| >= 2% .......... NO TRADE  (correct today)
                        │
  regime ───────────────┼─ backwardation (VIX9D > VIX3M) .. NO SHORT PREMIUM
                        │                                   └─ opportunity: long premium
                        │
                        ├─ VRP < 0 (IV < RV) .............. NO SHORT PREMIUM
                        │                                   └─ opportunity: long premium
                        │
                        └─ contango + VRP > 0 ............. SELL PREMIUM
                                                            │
                            ┌───────────────────────────────┘
                            ├─ put skew rich .............. SHORT PUT VERTICAL   (only branch today)
                            ├─ call skew rich ............. SHORT CALL VERTICAL  (blocked)
                            └─ size ∝ VRP magnitude ....... (currently ∝ model confidence)
```

Two changes carry nearly all the value:

**(a) Side selection from skew.** Fetch the call chain, compute IV at equal
absolute delta on both sides, sell the richer one. This gives the model a real
choice and uses data currently discarded.

**(b) Size on measured VRP, not on self-reported confidence.** Sizing currently
scales with the model's `confidence`, which has been 0.60 on every single
proposal — a constant, carrying no signal. VRP magnitude is *measured*, varies
with the market, and is the actual edge being harvested. Scaling size with it is
strictly more defensible than scaling with a number the model made up about
itself.

---

## 6. What is shippable before the deadline

Last entry window is **Wed 2 Sep, 10:45 ET**. After that, no change to entry
logic can affect a single trade.

| Change | Effort | Risk | Windows it could affect |
|---|---|---|---|
| Size ∝ VRP magnitude | small, `risk.py` only | low — no new data, no new order type | Tue 13:30, Wed 10:30 |
| Call chain + skew + `bear_call` | touches `market.py`, `risk.py`, `loop.py`, exits | **high** — new order shape on a path whose exit logic has never executed once in production | Wed 10:30 only, realistically |
| Long premium branch | new instrument, new exits, new gates | very high | none — cannot land in time |

**Recommendation.** Ship (b) today. Do **not** ship (a) before Thursday's flatten.

The reason is not conservatism for its own sake. As of this morning the agent has
opened one position and **closed zero** — `exit_intent`, `exit_filled` and
`exit_unfilled` are all zero across every session. Thursday's force-close is
mandatory and runs through code that has never executed against a live broker.
Adding a second order shape to that path, for the sake of one entry window, risks
the close-out that determines the final reported number.

Build (a) properly after the deadline, where it belongs.

---

## 7. What the write-up should say

Not *"the agent adapts to market regimes."* It does not, yet.

The honest and still-strong claim: **the agent measures five regime inputs and
refuses to trade in four distinct conditions where premium selling is
unprofitable** — VIX ≥ 30, backwardation, negative VRP, and event blackouts. That
is a genuine, tested, deterministic filter, and it is a real answer to the
question of when *not* to trade.

The selector is the acknowledged gap, and this document is the plan for it.
Saying that plainly is better than claiming an adaptivity the code does not have —
a judge can read `resolve_direction` in thirty seconds.
