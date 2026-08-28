# Theta Gate — Canonical Strategy and Implementation Plan

**Version:** 1.0

**Issued:** 28 August 2026

**Trading timezone:** `America/New_York`

**Implementation status:** approved design target; not yet implemented
**Authority:** this is the sole implementation authority for Theta Gate V1.

This document synchronizes and materially corrects the two source plans:

- supplied `theta-gate-implementation-plan.md`
- supplied `STRATEGY.md`

The source files remain untouched and retain value as historical evidence. For future implementation decisions, this document supersedes their operational instructions and also supersedes the stale operational portions of `docs/PLAN.md` and `docs/STRATEGY.md`. Research files remain evidence inputs, not executable authority.

Source-integrity baseline recorded before this file was created:

| Source | SHA-256 |
|---|---|
| `theta-gate-implementation-plan.md` | `bad9e166a589ea9f59511e597fde8d4377f119ff9ef4ac091005a10ca3673863` |
| Downloaded `STRATEGY.md` | `b2b8b454b1fd086b44ce9e477484b4dec45071628f61eac82b127726d9cfb453` |
| Repository `docs/STRATEGY.md` | `b2b8b454b1fd086b44ce9e477484b4dec45071628f61eac82b127726d9cfb453` |

The downloaded and repository copies of `STRATEGY.md` were byte-identical at the time of review.

---

## 1. Executive decision

Theta Gate V1 will be a paper-only, event-audited agent that may open one-contract, $5-wide SPY or QQQ put credit spreads. One bounded LLM analysis may select an underlying and provide a contextual thesis, but it cannot select strikes, expiry, quantity, price, order type, gates, or exits. Deterministic Python owns every financial and operational decision. The broker is the authority for exposure; an account-scoped Postgres control ledger is the durable authority for intents, idempotency, HALT, leases, baselines, and audit events; Git is publication transport, never a transactional database.

The hackathon objective is not to prove alpha in five sessions. It is to prove that an AI-assisted trading process can:

1. fail closed when inputs or permissions are uncertain;
2. keep the model structurally outside the write path;
3. make every order idempotent and recoverable;
4. reconcile partial, ambiguous, canceled, assigned, and failed states;
5. explain every trade and every no-trade decision;
6. finish with a broker-and-ledger-confirmed `EXACT_FLAT` state as defined in §3; and
7. report the sample honestly without claiming measured edge.

### Success metrics

| Metric | Required outcome |
|---|---|
| Live-capital exposure | Exactly `$0`; paper account only |
| Unmediated model writes | `0` |
| Entry orders without remotely committed intent and client ID | `0` |
| Risk-reducing orders without a deterministic broker-recoverable ID | `0` |
| Duplicate orders after crash/overlap | `0` in tests and paper run |
| Unexplained broker positions or orders | `0` at every completed reconciliation |
| Entries violating a gate | `0` |
| Exits decided by an LLM | `0` |
| Public secrets/account identifiers | `0` |
| Final controlled state | `EXACT_FLAT` is true under the single predicate in §3 |
| Unsupported performance claims | `0` |

---

## 2. Evidence classification and corrections

Every material claim belongs to one of four classes:

| Class | Meaning | How the implementation treats it |
|---|---|---|
| `HARD_SAFETY` | Mechanically required to prevent unintended orders or unbounded process failure | Mandatory; activation blocks if missing |
| `VERIFIED_BEHAVIOR` | Confirmed by current official documentation or a dated paper-account probe | Encoded, but re-probed before activation if account- or version-dependent |
| `ENFORCED_HYPOTHESIS` | A plausible trading filter that is not proven for this exact tenor and structure | Enforced consistently; logged as a hypothesis; never marketed as alpha |
| `OPERATIONAL_POLICY` | A deliberately conservative numeric or workflow choice without a claim of optimality | Enforced for V1; change only through config review and new boundary tests |
| `DIAGNOSTIC_ONLY` | Useful measurement without enough support to veto a trade | Logged and displayed; cannot affect entry |

### Material corrections from the source plans

1. **Stop arithmetic.** A spread entered for `$0.60` credit and closed at a `$1.20` debit loses `$0.60 × 100 = $60` per contract before fees and slippage. `$120` is the closing debit, not the loss. A `$120` loss would require a `$1.80` closing debit. The canonical setting is therefore named `stop_close_debit_multiple`, not `stop_loss_multiple`.
2. **Paper profile selection.** The current adapter calls `alpaca doctor --profile`. The installed Alpaca CLI guidance states that `doctor` ignores `-p/--profile`. The canonical adapter sets `ALPACA_PROFILE` in one subprocess environment used by doctor, preview, submit, lookup, cancel, and repair.
3. **Multi-leg partial fills.** Current official Alpaca MLeg documentation says the legs execute as one unit, while generic paper documentation describes simulated partial fills. Leg-level MLeg imbalance is therefore **unverified**, not an advertised platform fact. The code still defends against every observed broker inventory state and must re-probe the exact behavior on a throwaway paper account.
4. **Buying power.** The source plan's full-width paper-account observation conflicts with current official cost-basis language. Theta Gate does not claim either as universal broker margin behavior. It reserves the full `$500` width internally per spread and validates the actual paper-account buying-power change during the canary.
5. **VRP claim.** `ATM IV - RV20 >= 2 vol points` is a regime hypothesis, not proof that a 6–9 DTE, 20-delta vertical has positive expected value. The horizon, strike, skew, and execution costs do not match perfectly.
6. **DTE logic.** Linear credit-per-day arithmetic is not a valid theta model. V1 uses a deterministic 6–9 calendar-DTE range and a three-calendar-day buffer beyond Thursday's flatten. It does not claim this tenor is optimal.
7. **Strike sigma rule.** A one-realised-sigma minimum conflicts mechanically with much of a 0.16–0.25 delta band. Sigma distance is logged as a diagnostic and is not an entry veto in V1.
8. **Credit/delta curve.** `credit / width ≈ 0.8 × |delta|` came from one observed surface. It is retained as a diagnostic, not a hard gate. Direct executable quote quality is the gate.
9. **Journal timing.** A single pre-fill row cannot contain later fill and exit fields. V1 uses append-only lifecycle events, with the order intent flushed before the broker call and later observations appended.
10. **Durable state and Git workflow.** Local files and Git commits are not execution state on an ephemeral runner. A minimal Postgres control ledger stores account-global leases, window claims, HALT, session baselines, order intents, and append-only events. Push/rebase is removed from the trading loop; an isolated publisher reads a sanitized database view and cannot trigger resubmission.
11. **Call spreads.** Call spreads add a second surface, a second directional branch, and unvalidated switching logic. V1 is put-credit-only. A bearish model result means `NO_TRADE`.
12. **Sizing.** V1 trades exactly one contract per spread for the entire hackathon, not only the first trade. This removes false precision from a sample too small to justify scaling.
13. **Quote freshness.** The source threshold of 600 seconds is reduced to 60 seconds and becomes enforceable because quote timestamps are added to the contract model.
14. **Deadline execution.** The final flatten starts at 14:30 ET and reaches its forceful rung by 15:30 ET, leaving recovery time before the close. The source plan's first market attempt at 15:50 ET was too late.
15. **Track A priority.** The upstream options-spreads skill is useful but nonblocking. It begins only after the core loop, recovery, workflow, dashboard, activation evidence, and submission assets are working.

---

## 3. Non-negotiable system invariants

These are `HARD_SAFETY`. Violating any one is a no-go for submission-account activation.

`EXACT_FLAT(account_key)` is the only flatness predicate in V1. It is true only when one successful, fresh reconciliation attempt (all constituent reads completed within five minutes, with no failed, timed-out, stale, or inconclusive read) proves all of the following for the protected paper account:

1. broker positions are empty;
2. broker open orders are empty and no order is in a working or unknown state;
3. broker recent-order history plus exact-client-ID lookups for the finite durable/reconstructed intent set leave no unresolved `SUBMIT_AUTHORIZED`, `SUBMIT_UNKNOWN`, cancel, exit, repair, assignment, or degraded-recovery intent;
4. no recovery incident for the account is open or terminally unsuccessful; and
5. the durable ledger, imported/reconstructed degraded evidence, broker fills, and position transitions reconcile without unexplained exposure or unresolved audit gap.

An empty positions response by itself is never flatness. A caller must persist the complete reconciliation evidence and its broker-observation timestamps before it may use `EXACT_FLAT` to clear HALT, change or unlock a release, stop recovery, disable schedules, or certify submission.

Recovery avoids a circular dependency on its own open incident. Its broker execution may persist `terminal_reconciliation_evidence` only when clauses 1–3 and 5 above are satisfied for the same account, incident key, attempt, release, and fence. That evidence is not `EXACT_FLAT` and cannot clear HALT or authorize any other control change. After the protected execution job has actually completed with GitHub conclusion `success`, a separate credential-free finalizer verifies the exact repository/workflow/ref/SHA/run/job identities and the successful dependency. Only then does a protected one-purpose resolver job receive the `incident_resolver` credential and call `resolve_recovery_incident(incident_key, attempt_ordinal, execution_job_id, evidence_key)`. The RPC requires fresh evidence from that exact successful attempt, atomically marks only that incident resolved, and appends the resolution event. The caller then performs a fresh complete evaluation; `EXACT_FLAT=true` can be persisted only after that transaction and only if no other incident is open. Failed/canceled/skipped jobs, stale or mismatched evidence, a replayed attempt, or another open incident can never produce `EXACT_FLAT`.

1. The process proves the exact paper endpoint and expected account HMAC at tick start before broker reads, holds one immutable profile environment for the tick, and repeats both proofs immediately before every preview/write, including entries, exits, cancellations, repairs, and assignment handling.
2. No live credential is available to the runner, model process, repository, dashboard, journal, or CI log.
3. Every broker write goes through `alpaca.py`; CI rejects order CLI strings, direct Alpaca HTTP writes, or order SDK calls anywhere else.
4. The model process has no order credentials and receives only a strict read-only tool allowlist.
5. No bulk cancel, close, exercise, or do-not-exercise endpoint is callable.
6. Broker positions, open/recent orders, and fills are authoritative for current exposure.
7. A stop is an exit trigger, not a guaranteed loss cap. Width caps payoff loss only while both option legs remain paired.
8. `HALT` blocks entries but never blocks reconciliation, risk-reducing cancellation, assignment handling, or exits.
9. Missing, stale, malformed, non-finite, contradictory, or unit-ambiguous data blocks entry.
10. No entry occurs while any order is working or unknown, an exit is active, or reconciliation/repair is incomplete.
11. Every entry order intent and stage has a deterministic client order ID committed to the durable control ledger before submission. After dry run, one serializable `SUBMIT_AUTHORIZED` transition validates durable HALT, current fence, HALT version, body hash, and lease expiry; this commit is the control-plane linearization point. Environment values captured at job start are never treated as current control state. A HALT or takeover committed after authorization cannot guarantee that an already-authorized network packet will not reach the broker, so recovery must look up, cancel where possible, and reconcile that exact intent. Risk-reducing exits/repairs normally follow the same durable rule; if the ledger is unavailable, they use the explicitly tested deterministic `dbout` path because reducing broker exposure outranks audit availability.
12. A timeout is ambiguous. It triggers lookup and reconciliation, never blind resubmission.
13. Entry and exit paths are separate: entry price discipline can abandon a trade; an urgent exit cannot be abandoned indefinitely because of the entry concession limit.
14. A run never treats a submit or cancel acknowledgement as proof of fill, cancellation, or flatness.
15. A complete flatten requires `EXACT_FLAT(account_key)`; no weaker or local predicate may substitute.
16. Database-outage recovery is authorized only while the current Gate D evidence proves broker-atomic client-ID uniqueness for the exact order path; an absent or changed invariant blocks Gate F rather than risking a duplicate close.

---

## 4. Canonical V1 trading specification

### 4.1 Scope

| Parameter | Canonical rule | Class |
|---|---|---|
| Account | Fresh `$100,000` Alpaca paper account dedicated to Theta Gate | `HARD_SAFETY` |
| Underlyings | `SPY`, `QQQ` only | `ENFORCED_HYPOTHESIS` |
| Portfolio bucket | SPY and QQQ are one correlated bucket | `OPERATIONAL_POLICY` |
| Structure | One two-leg put credit vertical | `HARD_SAFETY` |
| Width | Exactly `$5.00` | `ENFORCED_HYPOTHESIS` |
| Quantity | Exactly `1` contract per spread | `OPERATIONAL_POLICY` |
| Short delta | `0.16 <= abs(delta) <= 0.25`; target `0.20` | `ENFORCED_HYPOTHESIS` |
| Long strike | Short put strike minus `$5.00` | `HARD_SAFETY` |
| DTE | `6 <= entry_calendar_dte <= 9` | `ENFORCED_HYPOTHESIS` |
| Flatten buffer | Expiry is at least 3 calendar days after 3 Sep 2026 | `OPERATIONAL_POLICY` |
| Entry order | MLeg limit, economic credit positive internally, negative broker limit | `VERIFIED_BEHAVIOR`, re-probe |
| Exit order | Reverse MLeg; positive broker debit | `VERIFIED_BEHAVIOR`, re-probe |
| Calls, condors, rolls | Forbidden | `HARD_SAFETY` |
| Naked option intent | Forbidden; imbalance repair only reduces actual exposure | `HARD_SAFETY` |

### 4.2 Units and formulas

All money and volatility values are parsed to finite `Decimal` values at boundaries. JSON serializes decimals as strings. Internal units are explicit:

```text
entry_calendar_dte   = (expiry_date - entry_trade_date).days
current_calendar_dte = (expiry_date - now_et.date()).days  # recomputed every tick
rv_return[t]     = ln(adjusted_close[t] / adjusted_close[t-1])
RV20_decimal     = sample_stddev_N_minus_1(last 20 completed daily returns) * sqrt(252)
VRP_points       = 100 * (ATM_put_IV_decimal_same_expiry - RV20_decimal)
intraday_move    = current_spot / previous_regular_close - 1
payoff_max_loss  = (width - actual_filled_credit) * 100 * quantity
risk_reserve     = width * 100 * quantity
gross_PnL        = (actual_entry_credit - actual_exit_debit) * 100 * quantity
```

`0.15` means 15% implied volatility. Two volatility points means `0.02` in decimal units or `2.0` in `VRP_points`. Code never compares decimal IV directly to the number `2.0`.

RV20 requires 21 completed, adjusted, regular-session closes to produce 20 log returns. The incomplete current daily bar is excluded. Prices must be ordered, unique by session, finite, and aligned to the exchange calendar.

### 4.3 Entry windows

| Trading date | Eligible windows, ET | Entry policy |
|---|---|---|
| Monday 31 Aug | `[10:30, 10:45)`, `[13:30, 13:45)` | Up to two entries, one per underlying |
| Tuesday 1 Sep | `[10:30, 10:45)`, `[13:30, 13:45)` | Up to two entries, one per underlying |
| Wednesday 2 Sep | `[10:30, 10:45)` | Morning only |
| Thursday 3 Sep | none | Flatten only |
| Friday 4 Sep | none | Confirm flat and submit |

Each window has a stable identifier such as `20260831-1030ET`. Exactly one decision attempt is allowed per window; that decision may create at most two explicitly linked price-stage orders (`s0`, then `s1`) under §7. A delayed tick outside the interval records `window_missed`; it does not catch up. A rejection, model failure, final cancel, no-fill, or reconciliation event is not retried in the same window.

An early-close session has no new entries. Alpaca clock/calendar is checked at runtime; hard-coded weekday logic is insufficient.

### 4.4 Scheduled-event policy

Before the first eligible session, create and verify `data/events_2026-08-31_2026-09-04.json` against primary release calendars. The file records source URL, retrieval time, event timestamp, class, and reviewer. If it is missing, stale, or unverified, entries fail closed.

| Class | Events | Blackout |
|---|---|---|
| Tier 1 | FOMC decision/press conference, CPI, PCE inflation, Non-Farm Payrolls | Reject when `entry_ts < event_ts <= planned_flatten_ts`; also reject inside the inclusive interval from the prior session close through 30 minutes after release |
| Tier 2 | ISM, ADP, jobless claims | Block from 30 minutes before until 30 minutes after release |

All blackout endpoints are inclusive. Tier 2 rejects when `event_ts - 30m <= entry_ts <= event_ts + 30m`. Already-open defined-risk positions are carried across events unless a deterministic exit rule fires. These classifications and durations are safety hypotheses, not demonstrated alpha. A fixture for a 10:00 release must reject at 09:30 and 10:30 exactly and allow the first otherwise eligible time after 10:30.

### 4.5 Risk and exposure caps

| Limit | Value | Inclusive rule |
|---|---:|---|
| Quantity | `1` | Any other quantity rejects |
| Per-trade reserve | `$500` | `risk_reserve <= 500` |
| Total open + pending reserve | `$1,000` | New intent rejects if total would exceed 1,000 |
| Concurrent spread positions | `2` | New intent rejects at 2 |
| Positions per underlying | `1` | New intent rejects if same underlying is open or pending |
| Filled entries per session | `2` | New intent rejects at 2 |
| Filled entries per underlying per session | `1` | A morning fill prevents an afternoon re-entry even if the morning spread has closed |
| Daily entry halt | `-1.0%` from session-start equity | Equality halts entries |
| Cumulative halt | Equity `<= $98,000` | Activates HALT and exit workflow |
| Post-trade options BP floor | `$25,000` | Broker-reported BP after the projected reserve must remain at or above floor |

At `$5.00` width and `$0.60` credit, payoff max loss is `$440`; the internal reserve is `$500`. The plan deliberately uses the more conservative reserve without claiming that it equals Alpaca's universal margin formula.

Pending and ambiguous orders reserve their full width until terminal broker reconciliation proves otherwise. Every numeric cap and threshold in this subsection is an `OPERATIONAL_POLICY`, not a claim of optimal risk sizing.

### 4.6 Entry regime filters

These are `ENFORCED_HYPOTHESIS` rules:

```text
VRP_points >= 2.0
VIX_prior_close < 30.0
VIX9D_prior_close < VIX3M_prior_close
abs(intraday_move) < 0.020
```

Boundaries fail conservatively: VIX exactly `30.0`, flat term structure, or an intraday move exactly `2.0%` yields `NO_TRADE`. The earlier VIX lower bound of 12 is removed because it was not validated for this exact strategy and duplicated the purpose of the direct minimum-credit and VRP checks. The remaining gates do not mathematically guarantee rejection whenever VIX is below 12.

Regime failures block new entries only. They do not decide exits. The system does not claim it “never buys back into a volatility spike”; a deterministic stop or deadline may require exactly that.

### 4.7 Diagnostic-only measurements

These fields are logged and shown but cannot veto V1 entries:

- `credit_delta_curve_ratio = (credit / width) / abs(short_delta)`;
- `rv_sigma_distance = abs(spot - short_strike) / (spot * RV20 * sqrt(remaining_trading_sessions / 252))`; emit `null` plus `diagnostic_unavailable` when RV20 or remaining sessions is nonpositive;
- implied-volatility percentile/rank, if available from a complete verified series;

None is represented as proof of edge.

---

## 5. Data contracts and validation

### 5.1 Typed models

`models.py` owns frozen enums/dataclasses and strict serializers:

| Model | Required fields |
|---|---|
| `Proposal` | proposal ID, `SPY|QQQ`, `bullish|neutral|bearish`, confidence `[0,1]`, thesis `<=60` words, invalidation `<=30` words, prompt/model version, creation time |
| `OptionQuote` | OCC symbol, underlying, `put`, expiry, strike, multiplier, delta, IV, bid, ask, quote timestamp, snapshot timestamp |
| `MarketState` | tick/window IDs, observed time, account summary, positions, orders, spot, prior close, move, RV20, VIX family, event state, freshness flags |
| `SpreadPlan` | stable plan hash, proposal link, immutable leg identities plus decision-time quote snapshots, expiry, entry calendar DTE, width, executable quote values, diagnostics, strategy/config hash |
| `OrderIntent` | purpose, client ID, plan/position link, exact immutable legs, quantity, signed price, TIF, body hash, dry-run hash |
| `BrokerObservation` | normalized status, requested/filled quantity, leg observations if present, fill price, observed time, redacted broker ID hash |
| `GateResult` | ordered gate name, pass/fail, machine reason, sanitized display context |
| `JournalEvent` | schema, IDs, timestamps, config/code hashes, type, severity, payload, previous-event hash |

Unknown keys are rejected at external boundaries. Enum values, word limits, symbol formats, OCC format, dates, quantities, ratios, finite decimals, and timestamp timezone-awareness are validated before use.

### 5.2 Cboe VIX-family data

`market.py` validates:

- HTTP success and expected content type;
- non-empty response and exact required columns;
- parseable, unique, strictly ordered dates;
- finite positive values in plausible configured ranges;
- last row equals the immediately preceding trading session from the exchange calendar;
- no duplicate rows, partial download, changed schema, or future-dated value.

A timestamped last-good snapshot is kept for audit but is never silently used to authorize a new entry when current freshness fails. A Cboe failure cannot block exits.

### 5.3 Bars and RV20

The state builder:

1. obtains the exchange calendar;
2. requests Alpaca stock bars with `adjustment=all` (split and cash-distribution adjustment); activation blocks if the installed CLI/API cannot request and echo that mode;
3. excludes the current incomplete session;
4. validates session date, order, uniqueness, finiteness, and gaps;
5. calculates 20 close-to-close log returns using sample standard deviation with denominator `N-1` and annualizes with `sqrt(252)`; and
6. records raw range dates, provider adjustment mode, formula version, and resulting decimal value in the data fingerprint.

The journal states that backward-looking RV20 does not perfectly match forward 6–9 DTE option risk.

### 5.4 Option chain and spot

Both legs must satisfy:

- correct underlying, put side, expiry, strike, OCC symbol, and `100` multiplier;
- finite bid/ask, `bid > 0`, `ask >= bid`;
- finite IV and delta in expected decimal ranges;
- quote age `<= 60` seconds at preview and again at submit;
- snapshot timestamps within 5 seconds of each other and spot no more than 10 seconds older than the newest leg;
- exact `$5.00` long-leg strike exists;
- immutable identity fields—OCC symbol, underlying, side, expiry, strike, multiplier—match the decision candidate at final refetch.

Mutable quote, IV, delta, and spot fields are expected to change; they are replaced with the final snapshot and fully re-gated. Any failed identity or gate condition yields `NO_TRADE`.

Same-expiry ATM put IV is deterministic. From valid, fresh put quotes for the candidate expiry, let `K1` be the greatest strike `<= spot` and `K2` the least strike `>= spot`. If `spot == K1 == K2`, use that strike's IV. Otherwise require two distinct bracketing strikes and calculate:

```text
ATM_put_IV = IV(K1) + ((spot - K1) / (K2 - K1)) * (IV(K2) - IV(K1))
```

Tie-break duplicate strike records by OCC symbol after rejecting inconsistent duplicates. If spot is not bracketed, either IV is missing/stale/non-finite, or `K2 <= K1`, the entry fails. The final pre-submit refetch reruns quote, delta, current DTE, VRP, event, regime, exposure, buying-power, and paper/account gates.

The exact 60/5/10-second freshness/skew thresholds are `OPERATIONAL_POLICY`. Fresh valid market identity is the safety requirement; these conservative numbers are not claimed optimal.

### 5.5 Executable spread prices

For entry:

```text
natural_entry_credit = short_bid - long_ask
optimistic_credit     = short_ask - long_bid
mid_credit            = (natural_entry_credit + optimistic_credit) / 2
combo_spread           = optimistic_credit - natural_entry_credit
friction_ratio         = combo_spread / mid_credit
```

Hard requirements:

```text
natural_entry_credit > 0
mid_credit >= 0.50
combo_spread <= min(0.10, 0.20 * mid_credit)
```

For an exit:

```text
natural_close_debit = short_ask - long_bid
mid_close_debit     = ((short_bid - long_ask) + natural_close_debit) / 2
```

Entry triggers and gates use unrounded `Decimal` values. V1's order-price tick is `$0.01`, verified by throwaway dry run/canary before activation. Entry credit limits round **down** to the cent; exit debit limits round **up**. Thus an entry credit of `.505` becomes `.50`, while an exit debit of `.305` becomes `.31`.

For entries, a raw value outside `[0, width]` is a data error and vetoes the trade; values are never silently clamped. For exits, invalid, missing, or stale quotes do not clear a latched exit. The engine refetches, then enters the degraded-data exit ladder in §8.2. It never uses a clamped invalid quote as a trigger or price.

---

## 6. Deterministic entry pipeline

Gates run in the following order. The first rejection wins, is journaled, and cannot be overruled by the model.

```text
paper proof
  -> HALT and recovery state
  -> account status/options level
  -> broker reconciliation complete
  -> durable lease and market open/calendar/window claim
  -> event blackout
  -> account drawdown/portfolio reserve/pending-order caps
  -> VIX family freshness and regime
  -> bars/RV20/intraday shock
  -> one proposal schema and direction
  -> underlying-specific daily fill/position cap
  -> expiry and chain validity
  -> delta and exact long-leg existence
  -> quote freshness and executable friction
  -> same-expiry put ATM IV and VRP
  -> final refetch and complete re-gate
  -> durable order intent
  -> durable HALT/fence revalidation
  -> byte-identical dry run
  -> atomic SUBMIT_AUTHORIZED transition
  -> submit
```

### 6.1 Proposal routing

- `bullish` or `neutral`: deterministic put-spread search may proceed.
- `bearish`: `NO_TRADE`; no call-side substitution.
- confidence is logged but never changes size, side, gate thresholds, or priority.
- model failure, malformed JSON, forbidden tool attempt, timeout, rate limit, empty response, unsupported underlying, or injection-like content yields `NO_TRADE`.

### 6.2 Expiry and strike selection

The model does not supply DTE. The resolver enumerates all listed put expiries satisfying:

```text
6 <= entry_calendar_dte <= 9
(expiry_date - 2026-09-03).days >= 3
```

For every eligible expiry, it builds every exact `$5` vertical whose short delta is within `[0.16, 0.25]`, then applies all quote and financial gates. Passing candidates are sorted deterministically by:

1. lowest `friction_ratio`;
2. smallest `abs(abs(short_delta) - 0.20)`;
3. largest entry calendar DTE;
4. short OCC symbol;
5. long OCC symbol.

The first candidate is selected. If none passes, the window ends `NO_TRADE`.

This ranking and its tie-break order are `OPERATIONAL_POLICY`: deterministic and testable, not evidence that the first candidate has the highest expected return.

### 6.3 No-trade behavior

No gate is relaxed. No unsupported expiry, strike, side, quantity, or threshold is substituted. No order is manufactured for the demonstration. “Why no trade” is derived from named journal events, not inferred from absence.

---

## 7. Entry execution contract

### 7.1 Adapter rules

`alpaca.py` is the only broker boundary. It must:

1. set `ALPACA_PROFILE` in one copied, minimal, immutable subprocess environment for the tick;
2. reject any live-intent signal;
3. run `alpaca doctor`, require exit code `0`, parse the exact Trading endpoint, and require exact equality to `https://paper-api.alpaca.markets`;
4. fetch the account and compare `HMAC-SHA256(ACCOUNT_BINDING_KEY, account.id)` with the protected expected HMAC for the selected submission or throwaway profile;
5. use no `-p` or `--profile` CLI flag;
6. check timeout, file-not-found, return codes `0/1/2`, JSON schema, and sanitized stderr;
7. never log the process environment, keys, raw account response, account ID/HMAC material, or secrets;
8. expose explicit methods for read, preview, submit, lookup by client ID, get/list orders, cancel one order, single-leg repair, and exact equity flatten;
9. require the caller to supply the client ID; it may never generate one internally;
10. prohibit bulk operations; and
11. repeat both paper-endpoint and exact-account proof immediately before every preview/write; reject any command whose environment fingerprint differs from the tick-start proof.

### 7.2 Immutable request and idempotency

The economic entry credit is stored as a positive number. Only the order serializer converts it to a negative Alpaca `limit_price`.

The client ID is semantic, deterministic, and broker-bounded. V1 accepts only lowercase ASCII `[a-z0-9-]`, rejects leading/trailing or repeated hyphens, and caps every ID at 48 characters—well below the vendored Alpaca contract's current 128-character maximum. Gate D re-probes the current broker limit and submits the longest valid ID. `<token>` is the first 20 lowercase unpadded Base32 characters (100 bits) of `HMAC-SHA256(CLIENT_ID_KEY, canonical_json)` over account key, purpose, logical parent ID, action/leg, and fixed stage. The readable prefix is never the uniqueness source.

```text
entry:  tg-e-<YYMMDD>-<window>-<underlying>-s<stage>-<token>
exit:   tg-x-<token>-<rule>-<rung>
repair: tg-r-<token>-<leg>-<rung>
assign: tg-a-<token>-<asset>-<rung>
```

`window` is `1030` or `1330`; `underlying` is `spy` or `qqq`; fixed stage/rung values come from validated enums, never free text. Stage `s0` is the midpoint entry attempt and `s1` is the single permitted concession attempt. Each stage has its own durable client ID and parent decision ID. A stage is created only after the prior stage is broker-terminal and reconciliation proves zero exposure. The exact serialized body and SHA-256 hash are persisted before preview. Preview and submit for that stage use the byte-identical immutable argument vector and body; only the `--dry-run` flag differs. A changed price creates a new body hash, new stage ID, and new dry run. Before any normal-mode preview, `(account_key, client_order_id)` is inserted under a unique constraint; if the same ID maps to a different canonical body or logical order, the system HALTs rather than lengthening, salting, or silently regenerating the ID. The no-database `dbout` exception is narrower: quote-derived limit price is not part of its ID, so a found same-ID broker order is authoritative for price. Recovery adopts it only when purpose, symbols/legs, action/sides, exact quantity, order type, TIF, and rung all match; a price difference is logged as `dbout_price_drift_adopted`, while any immutable-field mismatch is critical HALT.

### 7.3 Price ladder

Entry is optional and has a hard give-up point:

1. submit a limit at rounded `mid_credit`;
2. after 30 seconds, if not terminal, cancel, confirm terminal state, reconcile fills/positions, refetch, and—only if no fill or exposure exists—create, dry-run, and submit stage `s1` once at `max(mid_credit - 0.05, natural_entry_credit, 0.50)`;
3. at 60 seconds total, cancel, confirm, reconcile, and end the window;
4. never chase below the natural credit or the `$0.50` floor.

An ambiguous response is resolved by the same stage client ID. Even if an immediate lookup returns no match, Theta Gate does not resubmit that stage in the same window; it records `submit_ambiguous`, ends entry activity, and lets startup recovery repeat the lookup. A new client ID is never used to escape uncertainty.

---

## 8. Exit arithmetic and precedence

Let `C` be actual filled entry credit and `D` the fresh executable midpoint debit to close:

```text
take-profit trigger: D <= 0.50 * C
stop trigger:        D >= 2.00 * C
time exit:           current_calendar_dte <= 2
```

For `C = $0.60`:

| Event | Close debit | Gross P&L per contract |
|---|---:|---:|
| Take-profit trigger | `$0.30` | `+$30` |
| Stop trigger | `$1.20` | `-$60` |
| Full payoff loss | `$5.00` less `$0.60` credit | `-$440` |

Slippage or a gap can make the actual stop loss worse than `$60`. The stop is not a cap.

### 8.1 Tick priority

```text
1. acquire single-flight lock and prove paper
2. replay journal and reconcile broker orders/positions
3. resolve ambiguous, partial, canceled, or repair states
4. detect and handle assignment/unexplained equity
5. forced flatten or cumulative HALT exit
6. stop exit
7. time exit
8. take-profit exit
9. build entry state and evaluate an eligible entry window
10. publish sanitized events and health status
```

Exit and recovery logic runs even when `HALT` exists, entry feeds are stale, the LLM is down, or the event calendar is missing.

### 8.2 Exit order behavior

| Exit reason | Initial order | Escalation |
|---|---|---|
| Take profit | Limit at fresh midpoint | After 60 seconds cancel-confirm-reconcile; continue holding unless another exit rule fires |
| Stop | Limit at fresh midpoint | After 30 seconds cancel-confirm-refetch, then marketable limit at natural close debit; the first trigger latches `EXIT_ACTIVE(stop)` until flat |
| Time exit | Limit at fresh midpoint | After 30 seconds marketable limit at natural close debit; the first trigger latches `EXIT_ACTIVE(time)` until flat |
| Cumulative HALT | Same as stop | Remains active until flat |
| Thursday flatten | See ladder below | Never reverts to hold |

Thursday 3 September ladder:

| Time ET | Action |
|---|---|
| 14:30 | Reverse MLeg limit at fresh midpoint |
| 15:00 | Cancel-confirm-reconcile; reverse MLeg marketable limit at natural close debit |
| 15:30 | Market MLeg only if the exact schema and throwaway-account canary verified support; otherwise the most marketable validated limit bounded by spread width |
| 15:45 onward | Reconcile and retry exact positions; critical alert until broker confirms flat |

No bulk endpoint is used. Every order names the exact legs and position intent. Friday's monitor run independently proves `EXACT_FLAT(account_key)` using the full broker-and-ledger predicate in §3.

Stop, time, cumulative-HALT, assignment/repair, and deadline exits are latched durable states. Later price improvement may improve the fill but cannot return the position to `HOLD`. Only an unfilled take-profit order may be canceled back to `HOLD` when no higher-priority exit has fired.

If quotes are missing, stale, crossed, or economically invalid for a latched stop/time/HALT/deadline exit, the engine performs two bounded refetches over 15 seconds. If valid quotes remain unavailable, it uses the exact forceful exit method proven in Gate D; if that method was not proven, Gate F activation is forbidden. Each attempt is reconciled before the next, and unresolved exposure remains critical rather than silently holding.

---

## 9. LLM boundary and optional MCP isolation

### 9.1 Proposer

The proposer returns exactly:

```json
{
  "underlying": "SPY|QQQ",
  "direction": "bullish|neutral|bearish",
  "confidence": 0.0,
  "thesis": "60 words maximum",
  "invalidation": "30 words maximum"
}
```

Strict JSON Schema rejects missing fields, extra fields, wrong enums, non-finite numbers, out-of-range values, and excessive text.

`confidence` is a JSON number, parsed to a finite decimal in `[0,1]`; strings are rejected. V1 deliberately has one model call. A second critic would add latency and failure surface without adding a financial control that the deterministic gates do not already provide.

### 9.2 Tool and credential controls

- The model process has no Alpaca submission credential, control-ledger credential, shell, filesystem write, configuration write, or broker adapter import. It runs with a minimal scrubbed environment.
- V1 may receive a sanitized snapshot and bounded public-news text without any direct tools. Alpaca CLI usage in deterministic Python satisfies the trading integration and keeps the model outside the broker boundary.
- If Alpaca MCP is used for demonstration or additional context, it runs in a separate process/container with a non-submission paper profile and egress restricted to approved data hosts; Trading API hosts are denied. Tools are discovered and intersected with an exact read-only allowlist. An attempted direct trading call must fail in an integration test.
- Public news and tool content is untrusted, prompt-injection-capable text; it is delimited and never interpreted as an instruction.
- Model text is never interpolated into a shell command, path, client ID, governance field, or executable code.
- Model/provider failure always means `NO_TRADE`; it never blocks exits.
- Prompt version, model version, sanitized response, any approved tool names, and latency are journaled.

The plan claims no established directional alpha from the LLM. Its purpose is a bounded context/thesis veto that is visible, auditable, and unable to breach deterministic controls.

---

## 10. Architecture

### 10.1 System boundary

```text
                  READ-ONLY / PUBLIC DATA
       Alpaca reads | Cboe CSV | event calendar | LLM/MCP
                          |
                          v
                    +-------------+
                    |  market.py  |
                    +------+------+
                           |
                  immutable MarketState
                           |
             +-------------+-------------+
             |                           |
             v                           v
        +----------+                +----------+
        | brain.py |                |spread.py |
        | veto only|                | resolver |
        +----+-----+                +----+-----+
             |                           |
             +-------------+-------------+
                           v
                      +---------+
                      | risk.py |
                      |  pure   |
                      +----+----+
                           |
                    approved plan only
                           v
 +--------------+    +-----------+    +-----------------+
 |  store.py    |<-->|execution.py|<-->| alpaca.py / CLI |
 | durable ctrl |    | state mach.|    | sole broker I/O |
 +------+-------+    +-----+------+    +-----------------+
        ^                  ^
        |                  |
        +--------+---------+
                 |
             +---+----+
             |loop.py |
             +---+----+
                 |
       durable events -> sanitized publisher
                 |
          +------+------+
          v             v
   data/events.jsonl  app.py (read-only)
```

### 10.2 File ownership

| Path | Action | Single responsibility |
|---|---|---|
| `governance.json` | modify | Versioned canonical numbers and feature switches; never runtime state |
| `recovery_policy.json` | generated in release | Minimal hash-pinned account/underlying/exit policy derived from governance; lets `loop.py --recovery-only` run if entry config fails |
| `models.py` | create | Frozen types, enums, validation, serialization, stable hashes |
| `db/schema.sql` | create | Portable Postgres tables, constraints, roles, row security, and sanitized publication view |
| `store.py` | create | Allowlisted durable RPC client for fenced lease, claim, HALT, baseline, intent, authorization, event, and reconstruction transactions |
| `alpaca.py` | harden | Checked CLI transport and paper proof; sole broker boundary |
| `market.py` | create | Build and validate one timestamped market/account snapshot |
| `spread.py` | modify | Pure candidate construction, price math, deterministic selection |
| `risk.py` | modify | Pure ordered gates, caps, and exit signals |
| `brain.py` | create | One bounded proposer, schema validation, scrubbed environment, fail-closed behavior |
| `journal.py` | create | Typed event schemas, canonical hashing, local degraded spool, replay/projections, redaction |
| `execution.py` | create | Order state machine, idempotency, cancellation, reconciliation, repair, assignment |
| `loop.py` | create | One-tick coordinator and sanitized alerts |
| `app.py` | create | Read-only Streamlit dashboard over journal projections |
| `.github/workflows/ci.yml` | create | Candidate-build tests, security checks, and release-manifest promotion; no broker credentials |
| `.github/workflows/scheduler.yml` | create | Secret-free exact active-tag dispatcher |
| `.github/workflows/recovery-watchdog.yml` | create | Secret-free job-level failure/missed-tick validator and incident-deduplicated recovery dispatcher |
| `.github/workflows/agent.yml` | create | Attested active-release recovery/execution job and isolated publication job |
| `.github/workflows/recovery.yml` | create | Offline-preauthorized retained-tag HALT/recovery only; no entry/model path |
| `data/events.jsonl` | generated | Deterministic sanitized publication from the durable ledger; never control state |
| `data/HALT.example.json` | create | Documented human HALT schema; live HALT is held durably in the ledger/protected variable |
| `data/events_2026-08-31_2026-09-04.json` | create | Frozen, sourced event calendar for the hackathon window |
| `tests/` | create/migrate | Unit, contract, lifecycle, recovery, security, workflow, integration tests |

Complexity is controlled by three decisions: one strategy, one-contract quantity, and one broker adapter. The durable store uses portable SQL through a thin interface; Supabase Postgres is the hackathon host, not an application-specific dependency. `journal.py` owns projections; `loop.py` owns default alerts, avoiding separate services until post-hackathon evidence justifies them.

### 10.3 Dependency rules

- `models.py` imports only the standard library.
- `spread.py`, `risk.py`, and journal projections are pure and perform no I/O.
- `brain.py` cannot import `alpaca.py`, `store.py`, or `execution.py`.
- `app.py` cannot import `alpaca.py`, `brain.py`, or `execution.py`, and cannot load `.env`.
- `alpaca.py` contains no strategy decisions.
- `execution.py` cannot alter governance or ask the LLM for a decision.
- `loop.py` is orchestration only; calculations stay in pure modules.

---

## 11. Durable control ledger, journal, and projections

### 11.1 Why a durable store is required

GitHub-hosted runners are ephemeral. Local `fsync`, workflow artifacts, and later Git publication cannot durably protect a pre-submit window claim, HALT, baseline, or intent if the VM disappears. V1 therefore uses an account-scoped Postgres ledger. Supabase is the initial managed host; the schema and access layer remain standard Postgres.

The minimum tables are:

| Table | Durable purpose | Key constraint |
|---|---|---|
| `account_control` | Account label, HALT state/reason/version, audit-only last observed release ref/digest | one row per account key; release fields never authorize execution |
| `run_leases` | Account-global owner, monotonic fence token, DB-time heartbeat, expiry | one current lease and fence per account |
| `session_baselines` | Trade date, broker `last_equity`, source observation | unique `(account_key, trade_date)` |
| `window_claims` | One decision attempt per entry window | unique `(account_key, window_id)` |
| `order_intents` | Purpose/stage, semantic client ID, exact body hash, lifecycle state | unique `(account_key, client_order_id)` |
| `order_observations` | Normalized broker transitions and redacted broker-ID hash | account-scoped unique observation key and foreign key |
| `events` | Append-only typed audit events | bigserial sequence + unique `event_key` |
| `event_chain_heads` | Serialized account-scoped event-chain head | one locked head row per account key |
| `degraded_spool_imports` | Later ingestion or explicit reconstruction of risk-reducing activity during DB outage | unique spool or reconstruction-evidence hash |

Entry authorization requires a committed lease, window claim, valid session baseline, inactive HALT, and committed order intent. A database outage blocks entries. Broker positions remain authoritative for exposure.

Exits, repair, assignment flattening, and cancellation are different: if the database is unavailable, reducing actual broker risk cannot wait for audit availability. The explicit no-database branch proves the pinned recovery policy, paper endpoint, exact account HMAC, and local nonblocking process lock; treats HALT as active; fetches broker open/recent orders and positions; and permits only reconciliation, cancellation, or deterministic risk-reducing orders. Before creating any new `dbout` order, it enumerates every recognized working or unknown entry, exit, repair, assignment, and flatten order that can affect the same inventory; adopts it by exact client ID/lineage; individually cancels working orders where cancellation reduces ambiguity; observes terminal state; and refetches positions. If an affecting order remains unknown or nonterminal, it submits no new close that could cross through flat and instead retries reconciliation with a critical alert. Because a newly triggered stop/time/deadline latch cannot survive loss of both the runner and local spool, once affecting orders are terminally reconciled this branch does not wait for a trigger: it flattens every recognized existing Theta Gate SPY/QQQ exposure under the fixed `dbout` reason. It never evaluates entry data, invokes the model, or opens/replaces exposure. GitHub concurrency is useful but not trusted as exclusive ownership in this branch, so every action first looks up its deterministic client ID and reconciles fresh broker state. Two runners can still race between lookup and submit; therefore activation depends on a dated Gate D proof that Alpaca atomically enforces client-ID uniqueness for concurrent identical IDs. A duplicate-ID response is resolved only by lookup/adoption; it never generates a replacement ID. If that broker invariant is absent, ambiguous, or changes, Gate F is disabled. The recovery executable writes a locally fsynced degraded spool and imports it after the ledger recovers. Every such event stores both `occurred_at` and later `recorded_at`, and the dashboard shows the audit gap.

### 11.2 Access and transaction boundaries

- The execution login role is restricted to one account key and has no direct table or sequence DML. It may execute only fixed `SECURITY DEFINER` transition functions—lease acquire/heartbeat, raise HALT, claim window, record baseline/intent/observation, authorize submit, and append event—each with `search_path=''`, strict argument schemas, account/fence/HALT checks, and least-privilege non-login ownership. It cannot call `clear_halt` and has no repository write permission.
- The `halt_latch` login can execute only `raise_halt_for_recovery_incident(account_key, incident_digest)`. It cannot read tables, acquire a lease, create/authorize an intent, append arbitrary events, or clear HALT; it is exposed only after secret-free recovery-incident validation.
- The `incident_resolver` login can execute only `resolve_recovery_incident(incident_key, attempt_ordinal, execution_job_id, evidence_key)`. It cannot read tables, write broker/control state, raise or clear HALT, resolve another incident, or append arbitrary events. The function locks the incident and evidence rows, verifies unresolved state, exact attempt/job/account/release/fence binding, freshness, clauses 1–3 and 5 of §3, and replay protection, then atomically resolves that incident and appends its typed event.
- The publisher role can read only a sanitized SQL view and execute one fixed-schema, append-only `record_publication_result(run_id, status, commit_hmac, error_code)` security-definer function with `search_path=''`; that function validates its allowlisted arguments and appends a publication event through the same serialized chain function used by the executor. The role has no broker credential or direct table/control write.
- The dashboard reads the generated sanitized file or sanitized read-only view; it has no executor role.
- The model process receives no database credential.
- Entry window claim and intent creation use serializable transactions and database time.
- Lease acquisition locks the account control row, increments a never-reused `bigint` fence token, and stores it on the lease. The owner heartbeats every 30 seconds against a 180-second DB-time TTL. Lease takeover is permitted only after expiry and must begin with full broker reconciliation.
- Every control mutation, claim, baseline, intent, and executor event carries the current fence token and is rejected transactionally when it is lower than the account's current token. Lease ownership and HALT are re-read before entry preview; after the byte-identical dry run, the atomic `SUBMIT_AUTHORIZED` transition revalidates fence ownership, unexpired lease, current HALT version/inactive state, exact body hash, and intent state. Loss of the lease, heartbeat, or database before that transition blocks entry. No later control-plane claim pretends to revoke a broker packet already authorized; later HALT/takeover owns cancellation and reconciliation of that exact ID.
- A failed heartbeat immediately latches `ENTRY_DISABLED` in process. If the ledger remains reachable but ownership changed, the stale process performs no further ledger mutation or broker write and exits after a final read-only broker snapshot. If the ledger is unreachable while exposure exists, it may enter only the no-database recovery branch in §11.1; that branch uses broker-state-derived IDs and cannot submit an entry.
- `HALT` uses optimistic versioning. Only a distinct `halt_admin` login, injected into the protected second job of the manual clear workflow, may call the fixed `clear_halt(expected_version, reconciliation_event_key, reason_code)` function. The function requires an exact current version and a less-than-five-minute-old durable reconciliation event proving `EXACT_FLAT(account_key)`. The first job creates that evidence using broker reads and executor RPCs; the second has the admin DB credential but no broker or repository credential. Executor, publisher, dashboard, and model roles cannot clear HALT even with a correct account/fence/version.
- Tables use lowercase unquoted names, `bigint generated always as identity` for internal event sequences, `timestamptz` for time, `numeric` for exact financial values, and `check`/`not null`/`unique` constraints for every state invariant.
- RLS is enabled and forced on control/event tables. Direct table/sequence DML is revoked from login roles; only audited non-login function owners receive the minimum grants. Default `public`, `anon`, and unrelated authenticated access is revoked. RPCs scope the executor to a protected account-key claim, `halt_latch` to one idempotent raise function, `incident_resolver` to one exact-attempt resolution function, the publisher to its one append function/view, and `halt_admin` to `clear_halt` only.
- Index every RLS/filter/join key: `(account_key, window_id)`, `(account_key, client_order_id)`, `(account_key, trade_date)`, `(account_key, status)`, event sequence, and event key. Every observation and position relationship includes `account_key`; foreign-key columns are indexed.
- Use Supavisor/PgBouncer transaction pooling. Transactions contain only database validation/mutation—never broker, model, HTTP, filesystem, or Git calls—and set a 5-second statement timeout.
- Acquire account, chain-head, and window locks in one documented order. Use a transaction advisory lock for the short claim/intent transaction plus the fenced durable lease row for crash recovery; deadlock, stale-fence, pause-past-TTL, and lease-takeover tests are mandatory.

### 11.3 Event envelope

```json
{
  "schema_version": 1,
  "event_id": "uuid",
  "event_key": "deterministic deduplication key",
  "ts_utc": "2026-08-31T14:37:00Z",
  "ts_et": "2026-08-31T10:37:00-04:00",
  "run_id": "20260831T1437Z-<suffix>",
  "fence_token": 42,
  "tick_id": "20260831T1437Z",
  "window_id": "20260831-1030ET",
  "decision_id": "stable hash or null",
  "position_id": "stable hash or null",
  "client_order_id": "semantic ID or null",
  "code_commit": "git sha",
  "config_hash": "sha256",
  "body_hash": "sha256 or null",
  "data_fingerprint": "sha256 or null",
  "event_type": "gate_vetoed",
  "severity": "info|warning|critical",
  "payload": {},
  "previous_event_hash": "sha256 or null",
  "event_hash": "sha256"
}
```

`payload` is not arbitrary JSON. Every `event_type` has a strict positive allowlist schema, scalar/array length limits, identifier transformation rules, and unknown-key rejection. Account IDs never enter an event. Broker order IDs are stored only as keyed HMACs; model/news text is bounded and escaped; raw responses and environment values are forbidden.

### 11.4 Canonical IDs and hashes

All stable IDs use UTF-8 bytes of:

```text
<domain>:v1\n<canonical_json>
```

then lowercase SHA-256 hex. Canonical JSON is emitted with sorted keys, separators `,` and `:`, UTF-8, no ASCII escaping, no NaN/infinity, and no insignificant whitespace. Money uses exactly two decimal places, price/ratio/volatility fields exactly six, quantities are integers, nulls are explicit, and timestamps are UTC RFC3339 with `Z`. No exponent notation is allowed.

| Domain | Exact preimage fields |
|---|---|
| `config` | Fully validated governance model dump |
| `decision` | account key, window ID, underlying, prompt version, config hash |
| `plan` | decision ID, immutable leg identities, final quote fingerprint, entry DTE, width, quantity, config hash |
| `position` | account key, entry client ID, leg symbols, actual paired quantity |
| `dbout-exposure` | account key; linked entry client ID; lexicographically sorted inventory tuples of asset class, normalized symbol, and signed integer quantity |
| `order-body` | exact immutable normalized CLI argument/body model excluding `--dry-run` |
| `event-key` | type-specific restart-stable fields defined below; `run_id` is excluded except for genuine run events |
| `event-hash` | complete stored envelope excluding its own hash field |

The `dbout-exposure` fingerprint groups only inventory mapped to one known Theta Gate entry lineage. Each tuple is exactly `{asset_class: "option"|"equity", symbol: uppercase OCC symbol or SPY/QQQ, signed_quantity: integer}`. A paired spread contains both sorted option tuples; unpaired inventory contains the observed surviving tuple; assignment contains the signed equity tuple plus any surviving linked protective-option tuple. The fingerprint excludes quote, time, runner, release, order status, and response ordering. A quantity change after a terminally reconciled fill intentionally creates a new exposure fingerprint for the remaining inventory; an unexplained or unlinked tuple cannot be grouped and receives no autonomous order.

Event-key domains are exact: run/tick events use account key, tick ID, event type, and fixed tick ordinal; decision/gate events use account key, decision ID, event type, and gate/transition ordinal; lifecycle events use account key, client/position ID, event type, and the durable entity state version; broker observations use account key, client ID, normalized status, broker `updated_at`, filled quantity, and fill price. `run_id` remains trace metadata and never changes lifecycle deduplication across a restart. Random `event_id` supports tracing but never idempotency. Hash-domain tests include key-order, decimal, null, Unicode, crash-after-commit, paired/unpaired/assignment exposure, multi-account, and restart-stability fixtures.

### 11.5 Event families

| Family | Events |
|---|---|
| Tick | `tick_started`, `recovery_started`, `state_observed`, `tick_completed`, `tick_failed`, `window_missed` |
| Decision | `proposal_received`, `plan_resolved`, `gate_passed`, `gate_vetoed`, `no_trade` |
| Order | `order_intent_recorded`, `dry_run_passed`, `submit_authorized`, `submit_started`, `submit_acknowledged`, `submit_ambiguous`, `order_observed`, `cancel_requested`, `cancel_confirmed`, `order_terminal` |
| Exposure | `fill_reconciled`, `position_opened`, `exit_triggered`, `position_flat` |
| Repair | `partial_fill_detected`, `repair_intent_recorded`, `repair_observed`, `exposure_reconciled` |
| Safety | `assignment_detected`, `unexplained_exposure`, `halt_activated`, `alert_emitted`, `audit_publish_failed`, `spool_lost_reconstructed` |

Payload schema registry:

| Event family | Positive allowlist payload fields |
|---|---|
| Tick | clock open/close booleans, scheduled/actual timestamps, duration, release/config hashes, lease outcome, reconciliation counts |
| Proposal | underlying, direction, numeric confidence, bounded thesis/invalidation, prompt/model versions, latency; no raw tool/news payload |
| Gate | gate name, pass/fail, reason code, finite sanitized operands with explicit units |
| Order intent | purpose, stage, semantic client ID, plan/position hash, redacted leg symbols, quantity, order type/TIF, signed price, body/dry-run hashes |
| Order observation | client ID, broker-ID HMAC, normalized status, requested/filled quantities, sanitized fill price, observed time, per-leg quantities where available |
| Exposure/repair | position hash, redacted symbols, paired/unpaired quantities, reserve, latched exit reason/stage, reconciliation result |
| Safety/alert | fixed reason code, severity, HALT version, retry count, sanitized operator action; no free-form exception dump |
| Spool reconstruction | bounded UTC interval start/end, reconstruction-evidence SHA-256, bounded list of client-ID HMACs and normalized order states, normalized resulting inventory, explicit unknown-field reason-code list, completeness enum fixed to `RECONSTRUCTED_GAP`; no invented timestamp/payload |

All free text has schema-specific length limits; exception classes map to fixed reason codes and sanitized messages. Tests attempt UUID-like account/order IDs, credentials, environment strings, oversized arrays/text, and unknown keys and require rejection before insert.

### 11.6 Write and recovery guarantees

- Append one validated database event per transition; commit every entry intent before the broker call.
- Deterministic unique constraints reject duplicate claims, intents, and logical events.
- Every event append calls one database function that locks the account's `event_chain_heads` row with `SELECT ... FOR UPDATE`, validates the current fence or the publisher/degraded-import capability, assigns `previous_event_hash`, inserts the event, and advances the head in one transaction. The sequence is the audit order; executor, publisher, and degraded-import concurrency cannot create competing successors.
- A degraded exit spool is immutable, locally chained, uploaded as an emergency artifact when possible, and later appended through `degraded_spool_imports` without rewriting the main chain. If the runner and unuploaded spool are lost, the next fenced owner reconstructs order observations from the finite deterministic client IDs, broker recent-order/fill history, and position transitions; records `spool_lost_reconstructed` with the affected time interval, evidence digest, recovered IDs/states, and explicit unknown fields; and labels audit completeness `RECONSTRUCTED_GAP`. It never invents missing occurrence timestamps or payloads. If broker history cannot establish the action and resulting inventory, HALT remains unresolved and Definition of Done cannot pass.
- Unknown schema, broken hash, secret-bearing field, database role violation, or inconsistent control state activates durable HALT for entries and broker reconciliation.
- Replay never treats projected exposure as authoritative without a broker snapshot.
- Dashboard projections include last reconciled time and never label published file state as live.
- If a runner disappears, the next lease owner reads durable claims/intents, enumerates deterministic client IDs, and queries the broker before any entry.
- The degraded recovery path never depends on a local attempt counter or a locally stored exit latch. Its finite client IDs are reconstructed solely from the account key HMAC, broker-observed exposure fingerprint, fixed `dbout` reason, action, and fixed rung (`r0`, `r1`, or `force`). On restart or takeover, any still-recognized exposure independently regenerates the same ID, looks it up, and reconciles broker orders/positions. It may advance to the next rung only after the prior ID is observed terminal and the new broker inventory requires another action; an ambiguous or unavailable status remains on the same rung. Local spool loss therefore cannot erase exit urgency, create a novel ID, or cause a blind retry.
- The exact concurrent same-ID broker canary is a runtime dependency, not a documentary assumption: two independent throwaway runners cross a barrier and submit the same risk-reducing client ID, first with identical bodies and then with different valid quote-derived prices but identical immutable fields. Exactly one broker order may exist in each case; the other runner must reject or resolve to and adopt that same broker body, and final inventory must not cross through flat into opposite exposure. The observed status/error contract is pinned in adapter fixtures and rechecked before submission-account activation.

---

## 12. Order lifecycle and recovery

### 12.1 State machine

```text
INTENT_RECORDED
  -> DRY_RUN_OK
  -> SUBMIT_AUTHORIZED
  -> SUBMITTING
       |-> SUBMIT_UNKNOWN -> LOOKUP_BY_CLIENT_ID
       |                         |-> FOUND -> WORKING
       |                         |-> MISS -> LOOKUP_MISS_PENDING
       |                                      |-> NOT_SUBMITTED_CONFIRMED -> NO_TRADE
       |                                      +-> UNKNOWN_UNRESOLVED -> HALTED
       +-> WORKING
             |-> FILLED -> RECONCILING -> PAIRED_POSITION
             |-> PARTIAL -> CANCEL_REQUESTED -> TERMINAL_OBSERVED
             |                                      |
             |                                      v
             |                                RECONCILING
             |                                  |-> SAFE_PAIRED_POSITION
             |                                  |-> REPAIRING -> RECONCILING
             |                                  +-> HALTED_UNRESOLVED
             |-> PENDING_CANCEL -> TERMINAL_OBSERVED -> RECONCILING
             |-> CANCEL_REQUESTED -> TERMINAL_OBSERVED -> RECONCILING
             |-> REPLACED -> ADOPT_VERIFIED_CHILD -> WORKING
             +-> CANCELED / REJECTED / EXPIRED / DONE_FOR_DAY -> RECONCILING

Any unknown status -> HALT entries -> alert -> broker reconciliation
```

`SUBMIT_AUTHORIZED` is persisted with account key, client ID, body hash, fence token, HALT version, and authorization timestamp. If the authorizing runner disappears or a newer HALT/fence appears before acknowledgement, the current owner treats the intent as possibly submitted, performs client-ID/recent-order/position lookup, cancels a working entry if possible, and reconciles any fill. It does not issue a second entry. The post-authorization/pre-acknowledgement interval is an explicitly recoverable in-flight race, not a promise of zero broker packets.

Status normalization and ownership are explicit:

| Broker status | Internal state | Required action |
|---|---|---|
| `accepted`, `new`, `pending_new`, `accepted_for_bidding` | `WORKING` | Monitor |
| `partially_filled` | `PARTIAL` | Cancel, then reconcile actual leg inventory |
| `pending_cancel` | `PENDING_CANCEL` | Continue monitoring; cancellation is not terminal |
| `filled` | `FILLED` | Reconcile actual positions/fills |
| `canceled`, `expired`, `rejected`, `done_for_day` | terminal | Reconcile before releasing reserve |
| `replaced` | terminal parent | Follow `replaced_by`; adopt child only when the durable intent lineage/body hash matches, otherwise HALT |
| any unrecognized value | `UNKNOWN_UNRESOLVED` | HALT entries, alert, and reconcile |

V1 does not call a broker replace endpoint; normal repricing uses explicit `s0` and `s1` orders. A spontaneously observed `replaced` status is therefore exceptional and must prove child ownership.

After `SUBMIT_UNKNOWN`, perform three client-ID lookups over 15 seconds, then cross-check recent orders and position deltas. A consistent match is adopted. A consistent miss across all sources becomes `NOT_SUBMITTED_CONFIRMED` and ends the window without resubmission. Any unavailable or contradictory source becomes `UNKNOWN_UNRESOLVED`; delayed visibility is rechecked on the next tick. Unknown is never coerced to filled, canceled, or not submitted.

### 12.2 Cancel/fill race

A cancel response means only “request accepted.” The execution engine must:

1. snapshot pre-order positions;
2. monitor the specific order;
3. request cancellation when required;
4. continue polling until a terminal broker state or explicit unknown-state timeout;
5. refetch recent orders and actual positions;
6. detect any fill that arrived after the cancel request; and
7. reconcile actual quantities before deciding the next action.

### 12.3 Partial and imbalanced fills

Official MLeg documentation and generic paper-simulation behavior are not assumed to be identical. The recovery algorithm works from actual inventory:

1. compare each option leg against the pre-submit snapshot;
2. if both correct legs exist in equal signed quantity and no working order remains, adopt the paired defined-risk position;
3. if only the short leg or excess short quantity exists, neutralize that uncovered short first with an explicit `buy_to_close` order;
4. then close any unpaired long with `sell_to_close`;
5. for a partial exit, keep the remaining paired spread under the original exit urgency;
6. monitor every repair order to terminal and refetch positions;
7. if inventory is inconsistent, unrecognized, or cannot be repaired, activate `HALT`, emit a critical alert, and continue reconciliation on subsequent ticks.

Because V1 quantity is one, no sizing decision depends on a partial fill.

All repair orders use `day` TIF, exact actual quantity, purpose-specific client-ID stages, and correct position intent. A repair attempt never opens the opposite exposure.

| Exposure | Stage 0 | Stage 1 after cancel-confirm-reconcile | Terminal stage / persistence |
|---|---|---|---|
| Uncovered short option | `buy_to_close` limit at fresh ask, rounded up; wait 15s | new intent at ask + `$0.05`, rounded up; wait 15s | use the forceful single-leg method proven in Gate D; otherwise remain HALT and retry next tick |
| Unpaired long option | `sell_to_close` limit at fresh bid, rounded down; wait 30s | cancel-confirm; retry next tick at fresh bid | forceful method only at deadline; a long option is bounded but entries stay halted until explained |
| Remaining paired spread after partial exit | Continue the original latched exit as reverse MLeg | use that exit's escalation rung | remains latched until flat |

Each per-tick repair ladder has at most two limit stages plus one pre-verified forceful stage; every stage is terminally reconciled before the next. If the market is closed, record `repair_queued_market_closed`, retain HALT, and resume at the first verified open tick. Missing quotes invoke the degraded exit rule in §8.2 rather than creating an unpriced arbitrary limit.

### 12.4 Assignment

The account is dedicated and options-only, so any equity line is abnormal, but the system still maps it to prior spread/order evidence rather than blindly closing every stock line.

1. activate `HALT` for entries;
2. map symbol, direction, quantity, option legs, and prior events;
3. flatten the exact stock quantity by an explicit order and confirm terminal state;
4. preserve the protective long option until stock exposure is neutralized;
5. close any surviving long option explicitly;
6. reconcile zero stock, explained option inventory, and zero repair orders;
7. non-100-share multiples, wrong direction, unknown stock, broker outage, or failed order remains `HALTED_UNRESOLVED` with critical alerts.

Assignment order ladder:

| Asset | Stage 0 | Stage 1 | Terminal behavior |
|---|---|---|---|
| Long stock to sell | Marketable limit at current bid, rounded down; wait 15s | cancel-confirm, refetch, submit new intent at bid minus `$0.05`; wait 15s | verified market order; otherwise retry each tick and escalate to PK |
| Short stock to cover | Marketable limit at current ask, rounded up; wait 15s | cancel-confirm, refetch, submit new intent at ask plus `$0.05`; wait 15s | verified market order; otherwise retry each tick and escalate to PK |
| Surviving protective long option | Keep until stock is neutral; then use unpaired-long ladder | deadline forceful stage if required | reconcile zero option quantity |

Only SPY/QQQ equity and option inventory that can be linked to the dedicated account's allowed universe may be autonomously flattened. Any other asset, contradictory direction, or unexplained quantity triggers immediate PK escalation and no autonomous order in that asset. After two failed forceful attempts, any unresolved exposure is a human-emergency threshold: PK may intervene, and the intervention must be journaled and disclosed as breaking the fully autonomous-history claim.

### 12.5 Startup recovery

Every tick begins with recovery. The normal branch is:

1. acquire account-global Actions ownership, then the database lease using database time;
2. prove paper endpoint and exact account binding;
3. load durable HALT state, record the already-selected release ref/digest as audit metadata, and validate the durable event chain; the database release observation never selects or gates runtime code;
4. identify unfinished ticks, ambiguous submissions, cancel requests, repairs, and projected positions;
5. enumerate deterministic client IDs for recent windows and open positions;
6. fetch broker open/recent orders and actual positions;
7. adopt known broker orders and reconstruct missing observations;
8. halt entries on any unexplained order or exposure;
9. run exit/repair logic; and
10. only then record/verify the session baseline and consider a new entry window.

If step 1 cannot acquire or renew the ledger lease because the database is unavailable, the tick enters the no-database recovery branch from §11.1 instead of terminating silently: prove the pinned recovery policy and paper/account binding, take the local lock, fetch broker state, enumerate the finite broker-state-derived recovery IDs, reconcile before each action, and perform only cancellation or risk reduction. It must not create an entry, baseline, window claim, model call, or unscoped repair. When the database returns, a new fenced owner imports the degraded spool or executes the explicit `spool_lost_reconstructed` path, serializes the recoverable evidence, and fully reconciles before entries can resume. Activation tests cover database loss before startup, loss after an ambiguous risk-reducing submit, runner death with both preserved and lost local spool, takeover, and stale-owner resumption.

The daily drawdown baseline is the broker account's `last_equity` field from the first valid snapshot at or after 09:30 ET, persisted exactly once as `session_baseline_recorded` under unique `(account_key, trade_date)`. Parse it as finite nonnegative `Decimal`; representations with fractional digits beyond cents are accepted only when those extra digits are all zero, then normalized to exactly two decimal places. A concurrent insert is accepted only when its normalized value equals the persisted value exactly; a one-cent or larger difference is `BASELINE_CONFLICT`, blocks entries, and activates HALT for review. The field and its semantics are reverified in Gate C. If it is absent, invalid, conflicting, or cannot be durably recorded, entries are blocked; current equity is never substituted after trading has begun because doing so could erase a loss.

---

## 13. Scheduling, concurrency, and Git

### 13.1 Workflow

Candidate deployment and live ticks are separate workflows.

`ci.yml` has no brokerage or production-ledger secrets. It runs tests, config/schema validation, dependency/hash checks, secret scans, generates `recovery_policy.json`, and builds a release manifest containing code, config, recovery-policy, dependency-lock, CLI, migration, dispatcher, watchdog, runtime, and break-glass-workflow hashes. A pinned `actions/attest-build-provenance` step signs the manifest digest with GitHub OIDC-backed artifact attestation; there is no long-lived signing key. Runtime verification pins the repository and signer workflow/ref identity and uses a pinned GitHub CLI to verify the digest against GitHub's Sigstore/Fulcio/Rekor trust chain. Missing, forged, stale, wrong-repository, wrong-ref, wrong-workflow, or wrong-digest attestations fail closed. GitHub trust-root or verifier-version changes require a reviewed release and new Gate C probe.

Every releasable commit is fully staged first under a protected, immutable tag named `theta-gate-runtime-<full-40-char-sha>`. The tag, manifest, attestation, environment eligibility, and throwaway/read-only evidence all exist before activation. The single protected selector `ACTIVE_RELEASE_REF` contains exactly one such immutable tag; the manifest digest is obtained from and verified against that tag's attested artifact, not a second mutable selector. Promotion is the one selector update, so a tick sees either the complete old release or the complete new release—never a mixed ref/SHA/manifest tuple. Force-updating or deleting a runtime tag is prohibited by repository rules and tested permissions.

GitHub evaluates scheduled workflow YAML from the default branch, so `scheduler.yml` and `recovery-watchdog.yml` are thin and broker-secret-free. The scheduler has only the permission needed to read `ACTIVE_RELEASE_REF`, verify no unresolved recovery incident exists, and dispatch `agent.yml` on that exact immutable tag. The watchdog runs on workflow completion and at five-minute intervals and queries exact job-level status through the GitHub API. For the named credential-free preflight and broker-execution jobs, `success` is the only safe terminal conclusion. Any other terminal conclusion—including failure, canceled, timed out, skipped, action-required, startup failure, or an absent/skipped execution after successful preflight—qualifies a `run:` incident. A tick counts as satisfied only when both required jobs succeeded. A `missed:` incident requires that no queued/running run or fully successful required-job pair exists within the seven-minute tick-plus-grace threshold. Publisher, summary, artifact, and Git job conclusions are excluded by exact job identity and can never trigger recovery or HALT. A running execution is not declared stale merely by age; `agent.yml` itself has a five-minute hard timeout, whose non-success terminal status triggers failover. The watchdog cannot receive broker/ledger secrets or execute recovery itself. The broker/ledger environments accept deployments only from protected runtime tags; default-branch candidate workflow changes cannot receive those secrets. Promotion protection requires review/CODEOWNERS and the attested manifest to cover dispatcher, watchdog, runtime, and recovery workflow hashes.

Because those two control workflows are still loaded from a mutable ref, Gate F adds a repository ruleset named `theta-gate-control-freeze`. Immediately before entries are enabled, PK records that the default-branch `scheduler.yml` and `recovery-watchdog.yml` hashes equal the active attested manifest, then enables the ruleset with update restriction, deletion protection, and force-push protection and with no actor, app, or administrator bypass. `CODEOWNERS` requires PK review for either control workflow before the freeze is established. From that point until `EXACT_FLAT(account_key)` and the submission receipt are both recorded, default-branch updates, deletion, force pushes, merges, and workflow-file edits are prohibited. Publisher output cannot create an exception because it targets only the separate `theta-gate-publication` branch. Any control-workflow change requires `EXACT_FLAT`, PK disabling the freeze, normal review, a new immutable tag/manifest/attestation, Gate C and Gate D requalification, selector promotion, hash equality verification, and re-enabling the freeze before entries resume. Gate A tests the ruleset definition and no-bypass policy in a rehearsal repository; Gate F live-probes that unauthorized update, deletion, and force-push attempts are rejected while the account is still `EXACT_FLAT`.

`agent.yml` is loaded from the selected immutable tag, checks out its tagged commit, proves that the tag's SHA suffix equals `git rev-parse HEAD`, and verifies the attested manifest in a credential-free preflight job. A separate environment-scoped execution job receives paper credentials only after preflight. It does **not** run candidate tests before recovery. Every scheduled/manual tick invokes `loop.py --recovery-only` from this last-known-good release first, using the generated recovery policy; an invalid entry configuration blocks entries but cannot suppress broker reconciliation or the recovery-only exit path. Recovery is never conditioned on the default branch's `github.sha`. Entry is enabled only when the selected tag, checked-out commit, attestation identity, and every manifest hash agree.

Promotion, selector rollback, and control-workflow unfreezing are forbidden unless `EXACT_FLAT(account_key)` is true. Before changing `ACTIVE_RELEASE_REF`, the old release remains dispatchable; after the single selector update, a credential-free dispatch test and recovery-only Gate C run must pass before entry is enabled. If the new preflight or recovery run fails while `EXACT_FLAT`, PK restores the selector to the still-immutable old tag. The previous tag is retained through submission. A fault rehearsal triggers ticks immediately before and after selector change and proves uninterrupted old-or-new recovery with no missing schedule interval.

`ACTIVE_RELEASE_REF` is the sole authority for entry-capable code. A separate protected canonical-JSON `RECOVERY_RELEASE_DESCRIPTOR` is explicitly **not** an active-release selector. It contains one retained tag ref, full commit SHA, manifest digest, recovery-workflow hash, recovery-policy hash, compatible schema version, and these non-secret credential bindings: `client_id_key_version`/`client_id_key_fingerprint`, `account_binding_key_version`/`account_binding_key_fingerprint`, `paper_keypair_version`/`paper_keypair_fingerprint`, `recovery_db_credential_version`/`recovery_db_credential_fingerprint`, `halt_latch_credential_version`/`halt_latch_credential_fingerprint`, and `incident_resolver_credential_version`/`incident_resolver_credential_fingerprint`. A fingerprint is full lowercase hexadecimal `HMAC-SHA256(secret_material, "theta-gate-secret-fingerprint:v1:<purpose>:<version>")`; multi-field credentials use a canonical length-prefixed byte encoding as `secret_material`. Only high-entropy generated secret material is eligible, and neither a secret nor a reversible derivative appears in the descriptor or logs. Both ordinary execution and recovery recompute every credential fingerprint available to that job and require exact purpose, version, and fingerprint equality before the first broker or control-ledger call; recovery obtains the remaining one-purpose credentials only in their isolated jobs, where the same check precedes use. A mismatch rejects the job before broker access, keeps HALT/incident state unresolved, and emits only the purpose/version mismatch.

The descriptor has this closed schema; unknown or missing keys are invalid:

```json
{
  "descriptor_schema_version": 1,
  "ref": "refs/tags/theta-gate-runtime-<40-hex-sha>",
  "commit_sha": "<40-hex-sha>",
  "manifest_sha256": "<64-lower-hex>",
  "recovery_workflow_sha256": "<64-lower-hex>",
  "recovery_policy_sha256": "<64-lower-hex>",
  "compatible_ledger_schema_version": 1,
  "client_id_key_version": "<immutable-version>",
  "client_id_key_fingerprint": "<64-lower-hex>",
  "account_binding_key_version": "<immutable-version>",
  "account_binding_key_fingerprint": "<64-lower-hex>",
  "paper_keypair_version": "<immutable-version>",
  "paper_keypair_fingerprint": "<64-lower-hex>",
  "recovery_db_credential_version": "<immutable-version>",
  "recovery_db_credential_fingerprint": "<64-lower-hex>",
  "halt_latch_credential_version": "<immutable-version>",
  "halt_latch_credential_fingerprint": "<64-lower-hex>",
  "incident_resolver_credential_version": "<immutable-version>",
  "incident_resolver_credential_fingerprint": "<64-lower-hex>"
}
```

The descriptor is staged and tested only while `EXACT_FLAT`, then its protected value, recovery-environment exact-tag allow rule, and bound secret versions are frozen through exposure. Rotation or replacement of the client-ID key, account-binding key, paper key pair, recovery database credential, halt-latch credential, or incident-resolver credential is forbidden while any position, working/unknown order, unresolved authorized/ambiguous/cancel/repair/assignment intent, recovery incident, or audit gap exists—equivalently, while `EXACT_FLAT` is false. After an allowed rotation, PK issues a new descriptor, reruns credential-binding tests plus Gate C and the complete offline/atomic-ID Gate D rehearsal, promotes the requalified release, and re-establishes the control freeze before Gate F reactivation. `recovery.yml` loads from that retained last-known-good tag, whose workflow and static command allowlist contain no entry, market-selection, or model path. Its credentialed preflight does **not** depend on live GitHub Attestation, Sigstore, Fulcio, or Rekor: it proves tag-suffix-to-HEAD equality and recomputes local manifest/workflow/policy/schema hashes against the preauthorized descriptor. Thus an active online-verifier or trust-service failure cannot disable recovery, while entry trust remains attestation-gated. Gate C and Gate D record the descriptor only after the tag passed online attestation and a complete offline recovery canary; a descriptor, bound credential version, or exact-tag environment change is forbidden while `EXACT_FLAT` is false.

The watchdog auto-dispatches the descriptor's tag on active failure/staleness; PK may also dispatch it manually. Recovery accepts exactly one typed incident key: `run:<github_run_id>`, `missed:<expected_tick_id>`, or `manual:<recovery_dispatch_run_id>`. Before any protected environment or secret is available, automatic preflight queries GitHub and proves a `run:` ID is recent, belongs to this repository's `agent.yml` at the currently selected active tag/SHA, and lacks a successful required preflight-plus-execution pair because either required job has any terminal non-success conclusion or execution is absent/skipped—not merely because a publisher/summary/artifact job failed. For `missed:`, it validates the tick ID against the canonical schedule/current time and proves no valid queued/running run or completed successful required-job pair exists for that tick and active tag. Wrong repository, workflow, ref/SHA, age, healthy required-job pair, publisher-only failure, malformed/future/old tick, or reused incident is rejected before secrets. A `manual:` incident accepts only an allowlisted PK actor and then enters a separate protected manual-recovery environment that requires PK approval; automatic incidents use the exact-tag auto-recovery environment without interactive approval.

After secret-free incident validation and before competing with any broker job, a halt-latch job receives only a dedicated database login allowed to call `raise_halt_for_recovery_incident(account_key, incident_digest)`. It atomically raises/idempotently confirms durable HALT and cannot read tables, clear HALT, or call any other transition. If the database is unavailable, entry authorization is already impossible and the incident remains open; the scheduler suppresses further entry-capable dispatches. Next, a secret-free preemption job cancels every queued/running `agent.yml` execution for the account/active tag—including but not limited to the `run:` source—waits for terminal GitHub status, and never watches or cancels a recovery run. Any previously authorized broker packet is treated as possibly delivered.

The credentialed recovery job uses a dedicated `theta-gate-recovery-submission` Actions group with `cancel-in-progress: false`; ordinary ticks use `theta-gate-agent-submission`. An ordinary pending run therefore cannot replace or starve recovery. The fenced database lease remains the account-global cross-group authority when available; after HALT and preemption, recovery acquires/takes over that lease, or enters the verified `dbout` path if the database is unavailable. It proves the exact paper account and performs exact-ID lookup/reconciliation before any cancel/repair/flatten. Recovery runs only lookup/cancel/reconcile/repair/assignment/flatten operations and receives only the paper and recovery-ledger credentials required for those actions—never publisher/model credentials. Its protected environment accepts only the descriptor's exact retained tag. It remains dispatchable while exposure exists without changing `ACTIVE_RELEASE_REF`. Gate D deliberately breaks the active runtime and the online attestation verifier after opening throwaway exposure and proves watchdog-to-retained-tag offline adoption and flattening without human action. Recovery schema/migrations remain backward-compatible with that retained tag through submission.

Watchdog dispatch is idempotent by the complete typed incident key. A job-level concurrency key `theta-gate-watchdog-<sha256(incident_key)[:20]>` with `cancel-in-progress: false` serializes duplicate completion events and periodic scans. Before dispatch, it queries only runs whose workflow ID/path, descriptor ref/SHA, and validated `run-name` incident digest all match the retained recovery workflow; a lookalike run name is ignored. A queued/running attempt is adopted, not duplicated. The protected recovery execution exits `success` only after it persists fresh `terminal_reconciliation_evidence` satisfying `EXACT_FLAT` clauses 1–3 and 5 for its exact incident/attempt/release/fence; all other outcomes exit non-success and leave the incident open. Because that job cannot prove the absence of its own still-open incident, it never records `EXACT_FLAT`. A separate finalizer runs only after the execution dependency is terminal, validates through the GitHub API that the exact protected job for the exact repository/workflow/ref/SHA/run concluded `success`, and passes the immutable identity/evidence tuple to a protected resolver job. That job has only the `incident_resolver` credential, calls the single RPC in §11.2, and receives no broker, executor, HALT-admin, publisher, model, or repository-write credential. Only after the RPC atomically closes the incident does a fresh complete evaluation persist `EXACT_FLAT=true`; another open incident keeps it false. A failed/skipped/canceled execution, stale/mismatched evidence, finalizer failure, resolver failure, or every other conclusion remains unresolved and eligible for retry. After an ambiguous dispatch response the watchdog polls for the exact workflow/ref/run name and never immediately dispatches again.

Unresolved incidents retry under the same incident key with a monotonic `attempt_ordinal` derived from serialized prior run history and bounded backoff; the ordinal appears in workflow/audit metadata but never in broker client IDs. Only one attempt may be queued/running. The cancellation event caused by preemption maps to the already-claimed `run:` key; repeated scans of a missing tick map to the same `missed:` key; recovery/watchdog workflows are excluded as new source incidents while their unresolved keys remain eligible for retry. The watchdog stays enabled after the last trading tick and through market closure until the broker-confirmed resolution record exists; a closed market queues recovery for the next verified open and keeps critical visibility. Broker outage, failed/timed-out recovery, and the final-session incident therefore cannot be silently deduplicated away.

The runtime workflow uses:

- one ordinary-agent group `theta-gate-agent-submission` and one non-starvable recovery group `theta-gate-recovery-submission`, each independent of branch/ref; the fenced database lease/HALT remains account-global across both;
- `cancel-in-progress: false` within both groups; validated recovery first latches HALT, then explicitly cancels every entry-capable agent run, waits for terminal status, and performs exact-ID reconciliation;
- scheduling only through the protected, secret-free default-branch dispatcher; write-capable runtime only from the tag named by `ACTIVE_RELEASE_REF` and the protected paper environment;
- exact EDT-week cron entries `30,35,40,45,50,55 13 * * 1-5` and `*/5 14-19 * * 1-5`, producing 09:30–15:55 ET ticks; hard dates and Alpaca calendar checks still authorize behavior;
- a 5-minute hard execution-job timeout, per-command network timeouts of 30 seconds or less, and termination handling that spools degraded exit events; queued ticks remain serialized and skip expired entry windows;
- least-privilege repository permissions;
- Python/dependency lock with hashes, exact CLI/MCP and attestation-verifier versions, immutable action SHAs, and protected immutable runtime tags;
- `if: always()` event/artifact persistence and health summary.

GitHub cron is best effort and may be delayed. The code, not cron timing, authorizes entry. PK may disable the scheduler and watchdog only after `EXACT_FLAT(account_key)` and the submission receipt are both durably recorded. Any post-hackathon reuse requires a new DST-aware schedule review.

### 13.2 Layered single flight and recovery priority

1. `theta-gate-agent-submission` serializes ordinary scheduled/manual agent runs across refs.
2. `theta-gate-recovery-submission` serializes recovery runs independently, so an ordinary pending tick cannot replace recovery.
3. A validated incident latches durable HALT before canceling all entry-capable runs; the scheduler suppresses new entry-capable dispatches while the incident is unresolved.
4. A fenced database lease prevents broker-write overlap across both Actions groups and other workflow systems; a local nonblocking file lock prevents two processes in one runner. Heartbeats use database time; a stale fence cannot obtain `SUBMIT_AUTHORIZED`, while an older already-authorized packet is recovered by exact-ID lookup/cancel/reconcile. When the database is unavailable, entries are impossible and Gate-D-proven broker ID uniqueness protects the `dbout` recovery path.
5. A unique durable `window_claim` allows one decision attempt per window; staged intents and deterministic client IDs prevent duplicates across process/runner crashes.
6. A delayed ordinary job still reconciles and executes exits but skips an expired entry window; an unresolved recovery incident remains higher priority until broker-confirmed resolution.

Tests must show that simultaneous cron/manual dispatch and crash-restart produce one decision lineage per window, at most one intent for each entry stage, and at most two entry intents total. Stage `s1` is allowed only after `s0` is broker-confirmed terminal, no working descendant exists, and zero new exposure is broker-confirmed. One mandatory fault test pauses runner A before `SUBMIT_AUTHORIZED`, lets runner B take over, then resumes A; A must fail authorization under its stale fence and make no broker write. A second injects takeover or HALT immediately after authorization but before broker acknowledgement; B must adopt the possibly submitted intent, cancel it where possible, reconcile any fill, and never create a duplicate entry.

### 13.3 Job and secret isolation

- The execution job has paper credentials and the restricted executor-ledger role, but repository `contents: read` only.
- The break-glass job is loaded only from `RECOVERY_RELEASE_DESCRIPTOR.ref`, forces recovery-only/HALT, has paper plus recovery-ledger credentials, and has no model, market-entry, publisher, or repository-write credential/path. Automatic validated incidents use an exact-tag environment without approval; manual incidents require an allowlisted PK actor plus PK-protected environment approval. Its preflight/preemption job is secret-free and receives only Actions read/cancel/dispatch permission.
- The intervening halt-latch job receives only the one-RPC `halt_latch` database credential—no broker, general executor, publisher, model, repository-write, or clear-HALT capability.
- The incident finalizer is credential-free and receives only Actions read permission; only after it validates the exact successful protected execution dependency does the resolver job receive the one-RPC `incident_resolver` credential. Neither job receives broker, executor, `halt_latch`, `halt_admin`, publisher, model, or repository-write capability.
- The publisher job has repository write permission and the sanitized publisher role described in §11.2, but no brokerage secret, account-binding key, executor role, or model credential.
- Jobs exchange only a schema-validated sanitized run identifier; the publisher queries the sanitized view rather than trusting arbitrary execution artifacts.
- Pull requests, forks, unapproved refs, and candidate CI receive no paper or production-ledger secrets.
- The model subprocess receives a scrubbed environment with neither job's privileged credentials.

### 13.4 Git is publication transport

- The trading process never runs `git pull`, `git rebase`, or `git push`.
- After the tick exits, the isolated publisher job renders and commits only the sanitized event/config projection to the dedicated `theta-gate-publication` branch; it has no permission to update the frozen default branch or any runtime tag.
- A push conflict or auth failure never reruns the tick and never blocks exit handling.
- On failure, durable events remain in Postgres; the publisher's fixed append-only RPC records `audit_publish_failed` through the serialized chain-head function and emits an alert. If that RPC is unavailable, the next executor tick records the workflow result from an authenticated status artifact. No hash chain is forked.
- The next tick reconciles the broker and ledger even if repository history is stale.
- Journal commits do not trigger the trading workflow recursively.

### 13.5 API-call budget and priority

One tick prioritizes: paper/account proof → durable lease/HALT → broker orders/positions → active exits/repairs → clock/calendar → entry data → one LLM call. The Alpaca CLI owns its documented 429/5xx retry behavior; Theta Gate adds no blind outer retry loop. Every subprocess is capped at 30 seconds.

Entry work is abandoned if a rate limit, time budget, or tick deadline would threaten recovery. Polling uses the documented bounded cadence. Exit/recovery calls are not displaced by VIX, news, chain enumeration, dashboard, or publication calls; if an urgent exit cannot complete inside the job, its latched state and deterministic ID carry to the next serialized tick.

---

## 14. Governance configuration target

`governance.json` becomes schema-versioned, validated, and hash-pinned. The exact target semantics are:

```json
{
  "schema_version": 1,
  "mode": "paper_only",
  "account": {
    "label": "submission",
    "required_account_hmac_secret_name": "SUBMISSION_ACCOUNT_HMAC",
    "active_release_ref_variable": "ACTIVE_RELEASE_REF",
    "recovery_release_descriptor_variable": "RECOVERY_RELEASE_DESCRIPTOR"
  },
  "strategy": {
    "underlyings": ["SPY", "QQQ"],
    "option_side": "put",
    "structure": "vertical",
    "legs": 2,
    "width_dollars": "5.00",
    "quantity": 1,
    "calendar_dte_min": 6,
    "calendar_dte_max": 9,
    "min_days_after_force_flatten": 3,
    "short_delta_min": "0.16",
    "short_delta_max": "0.25",
    "short_delta_target": "0.20",
    "minimum_mid_credit_dollars": "0.50",
    "max_combo_spread_dollars": "0.10",
    "max_combo_spread_fraction_of_mid": "0.20",
    "order_price_tick_dollars": "0.01"
  },
  "entry": {
    "windows_et": ["10:30/10:45", "13:30/13:45"],
    "wednesday_windows_et": ["10:30/10:45"],
    "max_filled_entries_per_session": 2,
    "max_filled_entries_per_underlying_per_session": 1,
    "no_entries_after": "2026-09-02T10:45:00-04:00",
    "quote_max_age_seconds": 60,
    "snapshot_max_skew_seconds": 5,
    "spot_max_age_seconds": 10,
    "first_limit_wait_seconds": 30,
    "total_entry_wait_seconds": 60,
    "max_concession_dollars": "0.05"
  },
  "regime": {
    "minimum_vrp_points": "2.0",
    "vix_prior_close_max_exclusive": "30.0",
    "require_vix9d_lt_vix3m": true,
    "intraday_move_abs_max_exclusive": "0.020",
    "event_calendar_required": true,
    "tier1_after_release_block_minutes": 30,
    "tier2_before_release_block_minutes": 30,
    "tier2_after_release_block_minutes": 30
  },
  "risk": {
    "risk_reserve_per_contract_dollars": "500.00",
    "max_total_open_and_pending_reserve_dollars": "1000.00",
    "max_concurrent_positions": 2,
    "max_positions_per_underlying": 1,
    "post_trade_options_bp_floor_dollars": "25000.00",
    "daily_entry_halt_pct": "-0.010",
    "cumulative_halt_equity_dollars": "98000.00"
  },
  "exit": {
    "take_profit_close_debit_multiple": "0.50",
    "stop_close_debit_multiple": "2.00",
    "time_exit_calendar_dte": 2,
    "take_profit_limit_wait_seconds": 60,
    "urgent_limit_wait_seconds": 30,
    "degraded_quote_refetch_attempts": 2,
    "degraded_quote_refetch_total_seconds": 15,
    "force_flatten_date": "2026-09-03",
    "force_flatten_ladder": [
      {"at_et": "14:30", "action": "limit_mid", "wait_seconds": 30},
      {"at_et": "15:00", "action": "marketable_limit", "wait_seconds": 30},
      {"at_et": "15:30", "action": "verified_forceful_mleg", "wait_seconds": 15},
      {"at_et": "15:45", "action": "reconcile_retry_alert", "wait_seconds": 0}
    ]
  },
  "repair": {
    "urgent_stage_wait_seconds": 15,
    "long_cleanup_wait_seconds": 30,
    "limit_concession_dollars": "0.05",
    "max_limit_stages_per_tick": 2,
    "forceful_stage_requires_canary": true,
    "human_escalation_after_failed_forceful_attempts": 2
  },
  "operational": {
    "no_bulk_operations": true,
    "fail_closed_on_unknown": true,
    "max_consecutive_tick_failures_before_halt": 3,
    "stale_tick_alert_minutes": 7,
    "max_active_run_minutes_before_recovery": 5,
    "journal_schema_version": 1,
    "database_required_for_entries": true,
    "lease_ttl_seconds": 180,
    "lease_heartbeat_seconds": 30,
    "submit_unknown_lookup_attempts": 3,
    "submit_unknown_lookup_total_seconds": 15
  }
}
```

Comments explaining evidence classification live next to this configuration in the canonical document and test names, not as ambiguous numeric names.

---

## 15. Dashboard, observability, and alerts

### 15.1 Read-only dashboard

```text
sanitized Postgres view -> publisher -> data/events.jsonl
                                  \-> app.py read-only projection
```

`app.py` never contacts Alpaca, invokes the LLM, loads secrets, or places orders. It shows:

- canonical strategy and deployed code/config hashes;
- paper-only status and redacted account label;
- last tick, last successful reconciliation, and staleness banner;
- current **last-reconciled** positions and working-order projection;
- proposals, every named gate, and first veto;
- order lifecycle, quoted/fill slippage, cancel/repair/assignment events;
- reserve, drawdown, feed freshness, and `HALT` state;
- sample size and an explicit “no measured edge” statement.

Invalid journal schema or corruption produces a prominent data-integrity error; records are never silently dropped. All model/news strings are length-bounded and escaped before rendering.

### 15.2 Alert channels

Default, authorization-free channels:

- sanitized structured stderr;
- GitHub error/warning annotations;
- `GITHUB_STEP_SUMMARY`;
- `alert_emitted` journal events.

Optional Telegram/email/webhook transport remains disabled until explicitly configured and approved. Alerts never contain keys, full account IDs, raw broker IDs, raw payloads, or private prompt content.

PK is the named on-call owner during active sessions. Before exposure is allowed, either (a) an explicitly approved real-time outbound alert channel has passed an end-to-end test, or (b) PK continuously monitors the runtime/dashboard with a maximum five-minute polling interval while any order, position, or unknown state exists. Critical acknowledgement target is five minutes. GitHub failure notifications alone and a 15-minute dashboard check are insufficient. Automated HALT/recovery does not depend on the human response; if neither monitoring mode is staffed, activation remains disabled.

| Severity | Conditions |
|---|---|
| Critical | Paper cannot be proven, unexplained exposure, assignment, failed repair, failed forced exit, journal integrity failure, `HALT` |
| High | Partial fill, ambiguous submit, cancel/fill race, unknown order status, three tick failures, tick gap, audit publication failure |
| Informational | Gate veto, normal no-trade, ordinary cancel, successful reconcile/exit |

---

## 16. Security and supply-chain requirements

Before any write-capable paper run:

- only paper keys are installed; throwaway and submission profiles are separate and positively identified by protected account HMAC;
- the model provider receives public market/news data only;
- repository, current staging area, full Git history, workflow logs, artifacts, and dashboard output pass secret scanning;
- `.env` is never committed, printed, uploaded, or read by the dashboard;
- Python dependencies are locked with hashes; CLI/MCP binaries and Python runtime are exact-versioned; GitHub Actions use immutable commit SHAs;
- subprocess calls use an argument array, never `shell=True`;
- symbols, dates, quantities, client IDs, enums, prices, URLs, and schemas are validated at boundaries;
- external skills, model/tool output, and PR content are treated as untrusted inputs;
- the execution job has no repository write token; the publisher has no brokerage, account-binding, executor-ledger, or model secret;
- no Alpaca MCP server receives the submission profile; any optional MCP process uses non-submission credentials plus a network deny on Trading API hosts;
- static CI proves `alpaca.py` is the only write boundary and that forbidden bulk commands do not appear in executable code;
- security review is an activation gate, not a last-day task.

---

## 17. Test strategy and coverage contract

The existing 16 tests are a useful base but cover only spread/risk primitives. The implementation is not complete until every branch below has a test.

### 17.1 Coverage flow

```text
CODE PATHS                                          OPERATOR / SYSTEM FLOWS

models.py                                           Configuration/startup
  |- valid typed payload                              |- valid config -> start
  |- invalid enum/type/bounds -> reject               |- invalid/hash mismatch -> HALT entries
  `- Decimal/hash round trip                          `- secret-like field -> reject

store.py + Postgres                                 Durable control
  |- fenced lease/claim/baseline/intent transaction    |- runner loss -> next lease adopts
  |- duplicate unique key / stale HALT version         |- database down -> entries stop
  `- serialized chain/RLS/sanitized view              `- exits use restart-stable degraded IDs

alpaca.py                                           Paper boundary
  |- doctor exact paper endpoint                      |- profile set through ALPACA_PROFILE
  |- timeout / missing CLI / exit 1 / exit 2          |- live or inconclusive -> zero writes
  |- preview body parity                              `- sanitized diagnostics
  `- every explicit order method

market.py                                           Market-data state
  |- valid calendar/Cboe/bars/chain                   |- complete snapshot -> gates
  |- holiday/early close/DST                          |- stale/malformed/missing -> no trade
  |- 21 closes -> RV20                                `- exit path unaffected by entry feed loss
  `- timestamps/skew/non-finite values

brain.py                                            AI flow [EVAL]
  |- valid single proposal                            |- accepted thesis -> deterministic pipeline
  |- malformed/extra/injected/tool-write attempt      |- rejection/failure -> no trade
  `- timeout/rate-limit/provider failure              `- no model dependency for exits

spread.py + risk.py                                 Decision flow
  |- all expiry/strike candidates                     |- one attempt per exact window
  |- every gate pass/fail/boundary                     |- no candidate -> named no-trade
  |- deterministic tie break                          `- HALT permits exits, forbids entries
  `- TP/stop/time/deadline precedence

journal.py                                          Audit/replay
  |- typed payload/canonical hash/degraded spool       |- normal ledger replay -> projection
  |- invalid chain/schema/secret                       |- corrupt -> durable HALT/integrity state
  `- late degraded-spool import                        `- publication failure -> no chain fork

execution.py [E2E]                                  Order lifecycle [E2E]
  |- preview -> submit -> filled                       |- normal entry and deterministic exit
  |- submit ambiguity -> client lookup                 |- no duplicate after crash
  |- cancel -> late fill -> reconcile                  |- partial/imbalanced repair
  |- unknown/rejected/expired/replaced                 |- assignment cleanup
  `- failed exit -> retained urgency                   `- deadline -> EXACT_FLAT proof

loop.py + workflow [E2E]                            Scheduler
  |- market closed / late / eligible tick              |- cron + manual overlap -> one intent
  |- startup recovery / exits / entries priority       |- stale fence -> zero entry writes
  |- publish success/failure separation                `- Git failure never reruns trade
  `- protected runtime ref / default-ref drift          |- job crash -> next-run adoption

app.py                                               Public demo
  |- valid, stale, empty, corrupt events                |- cold URL renders history
  `- zero broker/model/secret imports                  `- stale state never portrayed as live
```

### 17.2 Required test files

| File | Required cases |
|---|---|
| `tests/test_models.py` | enums, bounds, finite decimals, strict keys, word limits, hashes, round trips |
| `tests/test_store.py` | serializable fenced lease/window/intent/`SUBMIT_AUTHORIZED` RPCs; 30-second heartbeat/180-second TTL; pause, takeover, stale-owner rejection; exact-cent baseline equality and one-cent conflict; unique conflicts; durable HALT/versioning; current executor cannot clear HALT with any account/fence/version; `halt_latch` can only idempotently raise for a validated incident; `incident_resolver` can close only its exact attempt after fresh terminal evidence and cannot make `EXACT_FLAT` true while another incident is open; stale/mismatched/replayed evidence rejects; halt-admin requires fresh `EXACT_FLAT` evidence; direct DML revoked; DB outage; multi-account namespaces; serialized concurrent executor/publisher/import chain; degraded-spool import/reconstruction; row-security roles |
| `tests/test_alpaca.py` | no `--profile`; same env for doctor/command; exact endpoint and account HMAC; bound paper/account/client-ID key version and fingerprint checks occur before any broker call; mismatch invokes zero broker calls and logs no fingerprint/secret; exit codes; timeout; redaction; dry-run parity; semantic client ID required; 48-character/lowercase grammar and longest-ID fixtures; normal collision/body mismatch HALT; dbout same-ID price-drift adoption with immutable-field mismatch HALT; no bulk command; paper/account assertion for every public method |
| `tests/test_market.py` | weekends, holiday, early close, DST, Cboe schema/date failure, 21-close N-1 RV20, current-bar exclusion, `adjustment=all`, stale/skewed quote/spot, exact ATM-IV interpolation |
| `tests/test_spread.py` | 6–9 DTE and flatten buffer; exact `$5` leg; 0.20 target; deterministic friction ranking; missing long; quote formulas; diagnostic-only sigma/curve |
| `tests/test_risk.py` | pass/fail/equality/missing/wrong type/NaN/infinity for every gate; first-failure order; fixed qty; pending reserve; correlated caps; drawdowns; exit precedence and corrected arithmetic |
| `tests/test_brain.py` | numeric confidence; extra fields; malformed JSON; prompt injection; forbidden tool; unsupported symbol; timeout; empty output; no exit influence; scrubbed environment |
| `tests/test_journal.py` | strict per-event payloads including reconstruction interval/digest/IDs/states/unknowns, canonical hashes, crash-after-commit restart-stable event-key dedup, multi-account scope, concurrent chain integrity, secret/identifier rejection, degraded spool/import/reconstruction, replay/projection |
| `tests/test_execution.py` | every allowed transition including `SUBMIT_AUTHORIZED`; HALT/takeover after authorization and before acknowledgement; lookup match/miss/delayed visibility; replacement-child ownership; cancel/late-fill race; short-only, long-only, equal and unequal legs; exact repair ladders; partial exit; latched urgency; invalid-quote degraded exit |
| `tests/test_recovery.py` | crash after every lifecycle transition; deterministic lookup; broker/journal discrepancy; unexplained order/position; zero duplicate submit; canonical paired/unpaired/assignment `dbout-exposure` fingerprints; DB outage adopts/cancels/terminally reconciles affecting entry/exit/repair/assignment orders before flatten; unknown affecting order blocks a new close; crash after local trigger/spool and before submit; DB outage + ambiguous risk-reducing submit + runner loss with preserved or lost spool + takeover/reconstruction; stale-fence resumption |
| `tests/test_assignment.py` | assigned put, partial stock multiple, surviving long, unknown equity, queued/failed close, market-closed discovery |
| `tests/test_loop.py` | priority order; closed market; exact windows; 10:45 rejection; Wednesday cutoff; early close; one decision, at most one intent per `s0`/`s1`, `s1` only after terminal/no-exposure proof; per-underlying daily fill cap; exact-cent session baseline conflict; manual HALT before and immediately after `SUBMIT_AUTHORIZED`; HALT exits; flatten ladder; Friday `EXACT_FLAT`; call budgets |
| `tests/test_app.py` | files only; empty/stale/corrupt states; escaping; no secret/broker imports |
| `tests/test_workflow.py` | candidate CI separated from secret-free scheduler/watchdog and immutable protected tags; Gate-F no-bypass default-branch freeze rejects update/delete/force-push and publisher is publication-branch-only; default SHA drift before freeze still dispatches last-known-good recovery; one active selector old/new promotion and `EXACT_FLAT`-only rollback; strict offline `RECOVERY_RELEASE_DESCRIPTOR` including bound credential versions/fingerprints; pre-broker fingerprint mismatch rejection and `EXACT_FLAT`-only secret rotation/requalification; active online-verifier outage; typed `run:`/`missed:`/`manual:` validation; required-job success-only predicate including skipped/other non-success and preflight-success/execution-skipped; exact ordering terminal evidence -> successful execution -> credential-free finalizer -> one-RPC resolver -> fresh `EXACT_FLAT`, with failed/stale/other-incident negatives; wrong actor/repo/workflow/ref/SHA/age/status and publisher-only failure rejection; repeated-scan/source-cancel recursion dedup; ambiguous dispatch lookup; failed/unresolved recovery retry ordinal; five-minute execution timeout; publisher failure never triggers watchdog; halt-latch before all agent cancellations; scheduler suppression while incident open; independent agent/recovery groups with recovery admission not replaceable; exact UTC cron; scoped environments/permissions/secrets; immutable actions; attestation forged/stale/wrong-repo/ref/workflow/digest cases; manifest/workflow hashes; no recursive trigger |
| `tests/integration/test_replay.py` | full win, stop, no-trade, stale feed, model failure, DB unavailable before startup with immediate flatten, two independent no-DB runners submit same recovery ID with identical and price-different bodies, affecting working/unknown order reconciliation, DB outage after trigger and before submit, ambiguous exit and runner death/takeover, stale-fence resume before/after authorization, source timeout with next tick pending/running and repeated schedules while recovery is pending, HALT before every later authorization, active-runtime/online-verifier failure and hung-after-authorization timeout plus exactly-once deduplicated watchdog/offline retained-tag flatten, terminal evidence then successful-job incident resolution then fresh `EXACT_FLAT` ordering, failed/stale/other-open-incident resolution negatives, failed recovery then broker restoration/retry, last-session unresolved incident across market close, repeated missed-tick scan, manual HALT during entry, partial fill, assignment, broker timeout, concurrent event appenders, Git failure without watchdog, deadline flatten, two simultaneous stops, two-position flatten, repair plus other exit, unknown order plus exposed position |

### 17.3 Minimum numeric fixtures

| Fixture | Expected result |
|---|---|
| `C=.60`, `D=.30/.31/1.19/1.20` | TP / hold / hold / stop; stop target loss `$60`, not `$120` |
| Width `$5`, `C=.60`, qty `1` | Max payoff loss `$440`; reserve `$500` |
| Any passing spread | Qty remains `1` |
| Two open/pending one-contract spreads | Reserve `$1,000` passes; third rejects |
| Aug 31 entry, Sep 4 expiry | Reject: DTE/buffer rule |
| Fixture explicitly lists Sep 8 expiry for Aug 31 | DTE and flatten-buffer predicates pass; a separate unlisted-expiry fixture rejects |
| Position opened Aug 31 with Sep 8 expiry; ticks Aug 31/Sep 1/Sep 6 | `entry_calendar_dte=8` stays immutable; `current_calendar_dte=8/7/2` and time exit fires Sep 6 |
| Sep 2 at 10:37 / 13:37 ET | Eligible / rejected |
| 10:45 ET | Rejected; no catch-up |
| Short `1.60/1.64`, long `1.00/1.04` | Natural `.56`, midpoint `.60`, combo spread `.08`; quote gate passes |
| Entry credit `.505`; exit debit `.305` | Order limits `.50` and `.31`; triggers use unrounded values |
| Quote age `61s` | Reject |
| Mid credit `.49` | Reject |
| IV `.15`, RV `.12` | `3.0` points; pass |
| IV `.135`, RV `.12` | `1.5` points; reject |
| Fewer than 21 completed closes | Reject |
| VIX `30`, equal VIX9D/VIX3M, move `2%` | Reject each |
| Bearish at confidence `.01/.69/.99` | No trade; never substitute a call |
| Submit timeout followed by client-ID match | Adopt; never duplicate |
| Submit timeout, three misses, zero position/order evidence | `NOT_SUBMITTED_CONFIRMED`; end window; no resubmit |
| Morning SPY fill closes before 13:30 | Afternoon SPY proposal rejects on per-underlying daily fill cap |
| HALT with open spread | Entries reject; exits run |
| TP also true after Thu 14:30 | Forced flatten has precedence |
| Missing verified event file | No trade |
| Economic credit `.60` | Entry API price `-.60`; exit price positive |

### 17.4 LLM evaluation set

Create a fixed set of at least 30 sanitized market/news contexts:

- 10 clearly bullish/neutral;
- 10 clearly bearish or invalidated;
- 5 malformed/tool-failure cases;
- 5 prompt-injection or irrelevant-news cases.

Evaluate schema validity, unsupported-symbol rate, forbidden-tool rate, correct bearish veto behavior, and stability across repeated runs. Required safety scores are 100% valid schema after validator or fail-closed, 0 forbidden writes, 0 unsupported symbols reaching the resolver, and 0 model influence on sizing/exits. Directional accuracy is reported descriptively, not used as an activation gate.

---

## 18. Implementation plan

Implementation is sequential at the safety boundary, with parallel work only after shared contracts freeze.

### Phase 0 — Freeze authority and configuration

**Accountable owner:** PK; **responsible:** implementation agent

**Deadline:** 28 Aug 2026 ET
**Depends on:** none

Tasks:

1. Point `README.md` and `docs/PLAN.md` to this document as the sole V1 authority without deleting historical text.
2. Add schema-versioned `governance.json` semantics from §14.
3. Add a config loader that rejects unknown/missing keys, wrong units, non-finite values, and hash mismatch.
4. Record the deployed config hash in every event.
5. Add corrected arithmetic and unit tests before implementing broker writes.

Exit criterion: one validated configuration, no contradictory active numeric source, and tests prove volatility/unit and stop arithmetic.

### Phase 1 — Models and paper-safe adapter

**Accountable owner:** PK; **responsible:** implementation agent

**Deadline:** 29 Aug 2026 10:00 ET
**Depends on:** Phase 0

Tasks:

1. Create `models.py` contracts.
2. Rewrite subprocess handling in `alpaca.py` with checked exit codes and sanitization.
3. Select the profile only through `ALPACA_PROFILE`; remove all CLI profile flags.
4. Make client IDs caller-required.
5. Add read, preview, submit, get/list/lookup, single cancel, MLeg close, single-leg repair, and explicit equity-order methods.
6. Add the static forbidden-write-path test.

Exit criterion: all adapter tests pass; live/inconclusive simulations execute zero submit calls; dry-run and submit vectors are identical except `--dry-run`.

### Phase 2 — Durable store, journal, execution state machine, and recovery

**Accountable owner:** PK; **responsible:** implementation agent

**Deadline:** 29 Aug 2026 18:00 ET
**Depends on:** Phase 1

Tasks:

1. Apply `db/schema.sql` with restricted executor/publisher roles and sanitized view.
2. Implement serializable leases, window claims, baselines, HALT, intents, observations, and events in `store.py`.
3. Implement typed journal schemas, canonical hashing, replay, and degraded exit spool in `journal.py`.
4. Implement the complete order state machine in `execution.py`.
5. Implement ambiguous-submit lookup/miss, terminal cancel confirmation, position reconciliation, repair ladders, and assignment flow.
6. Inject a crash after every transition and prove restart does not duplicate.

Exit criterion: lifecycle/recovery suite passes every order state, cancel/fill race, imbalance, assignment, and crash point.

### Phase 3 — Market state, spread resolution, and deterministic risk

**Accountable owner:** PK; **responsible:** implementation agent

**Deadline:** 30 Aug 2026 10:00 ET
**Depends on:** Phase 0 contracts; may begin in parallel with late Phase 2 once `models.py` freezes

Tasks:

1. Build calendar, Cboe, bar, RV20, intraday move, ATM put-IV interpolation, chain, quote-age, and snapshot-fingerprint logic in `market.py`.
2. Replace midpoint-delta selection and call branches in `spread.py` with §6.2.
3. Replace old gates and names in `risk.py` with the canonical sequence and fixed quantity.
4. Keep credit/delta and sigma measures diagnostic only.
5. Freeze and source the scheduled-event file.

Exit criterion: all data/gate boundary tests pass, including missing/stale/non-finite/wrong-date inputs and exact equalities.

### Phase 4 — Deterministic loop and workflow, no LLM

**Accountable owner:** PK; **responsible:** implementation agent

**Deadline:** 30 Aug 2026 15:00 ET
**Depends on:** Phases 2 and 3

Tasks:

1. Implement `loop.py --once` with recovery/exits before entries.
2. Initially use fixture proposals; keep all broker writes disabled.
3. Add candidate-only `ci.yml`, protected secret-free `scheduler.yml`/`recovery-watchdog.yml`, the no-bypass default-branch control-freeze ruleset and `theta-gate-publication` branch, `agent.yml` loaded from the immutable tag named by `ACTIVE_RELEASE_REF`, and a mechanically recovery-only `recovery.yml` loaded from the credential-version-bound `RECOVERY_RELEASE_DESCRIPTOR.ref`, with online-attested entry preflight, offline preauthorized recovery preflight, typed incident validation/deduplication, account-global concurrency, and a monotonic fenced database lease.
4. Isolate execution credentials from the publisher job and render Git evidence from the sanitized ledger view.
5. Run full-session replay with overlapping triggers, stale-runner takeover, manual HALT during an in-flight entry, missed ticks, feed/database/Git failure, HALT, and flatten.

Exit criterion: a full replayed session produces zero duplicate intents, zero broker writes, valid events, and correct exit priority.

### Phase 5 — Single bounded AI layer

**Accountable owner:** PK; **responsible:** implementation agent

**Deadline:** 30 Aug 2026 18:00 ET
**Depends on:** Phase 4

Tasks:

1. Implement the single proposer schema, prompt delimiters, timeouts, logging, and fail-closed behavior.
2. Ensure the model process has a scrubbed environment with no submission, ledger, or repository credentials; isolate any optional MCP deployment as specified in §9.2.
3. Run the LLM evaluation set.
4. Verify model outage cannot block reconciliation or exits.

Exit criterion: no prohibited tool or invalid model output reaches the resolver; all safety eval targets pass.

### Phase 6 — Dashboard and observability

**Accountable owner:** PK; **responsible:** implementation agent

**Deadline:** 1 Sep 2026 before public demo
**Depends on:** Journal schema frozen

Tasks:

1. Build `app.py` from file projections only.
2. Add stale, empty, corrupt, HALT, unresolved-risk, and no-trade states.
3. Add GitHub summaries and sanitized alerts.
4. Deploy and verify the URL cold from outside.

Exit criterion: dashboard makes zero broker/model calls, leaks no protected fields, and renders valid and failed states clearly.

### Phase 7 — Activation gates

**Accountable owner:** PK; **responsible:** implementation agent for evidence

**Deadline:** before first submission-account write
**Depends on:** Phases 0–5; Phase 6 proceeds in parallel and blocks submission, not controlled entry activation

Execute Gates A–F in §20. No gate is waived because the account is paper. The verified live hackathon rules decide whether a replay-only fallback remains eligible; replay is never represented as an actual autonomous trade. If an actual trade is mandatory and Gate F is not passed by the go/no-go cutoff, PK records a no-go rather than submitting a noncompliant claim.

This is a compressed schedule, not authority to weaken controls. Phase 2 is the critical-path checkpoint: if it misses its exit criterion by 29 Aug 18:00 ET, or if any of Phases 3–5 misses its stated exit criterion by 30 Aug 18:00 ET, submission-account activation is canceled. The team may finish a clearly labeled replay-only demo only if the archived live rules allow it; otherwise the outcome is no-go. Partially implemented leases, recovery, workflow isolation, data validation, or model boundaries are never activated.

Hard checkpoints:

- **28 Aug, 18:00 ET:** archive the live submission form/rules and determine whether at least one actual autonomous options trade is mandatory.
- **30 Aug, 18:00 ET:** Gates A–C and the complete failure replay must pass; otherwise submission-account writes remain disabled Monday.
- **31 Aug, before the first entry window:** Gate D must pass through the exact deployed Actions execution job against the throwaway profile, followed by Gate F account binding.
- **3 Sep, 13:00 ET:** if the verified terminal forceful exit method has not passed, activate HALT and flatten early; no new exposure.

### Phase 8 — Hackathon assets and submission, prepared in parallel

**Accountable owner:** PK; **responsible:** implementation agent for artifact production

**Deadline:** 4 Sep 2026 before 11:00 ET
**Depends on:** shell assets begin after Phase 0; final facts depend on activation evidence and externally verified dashboard

During Phases 1–6, prepare the README shell, slide/video storyboard, cover, updated diagrams, replay captures, compliance checklist, and source ledger. After activation evidence exists, replace placeholders with verified facts, independently verify the repository, demo URL, video, slides, cover image, one-page write-up, account evidence, final `EXACT_FLAT` proof, and submission receipt.

### Phase 9 — Upstream options-spreads skill

**Accountable owner:** PK; **responsible:** documentation agent

**Deadline:** post-submission or only after all submission blockers close
**Depends on:** Phase 8 blockers cleared

Draft, verify, and upstream `alpaca-trading-options-spreads`; vendor it back only after its claims match the final tested adapter. This track cannot delay or destabilize the hackathon agent.

---

## 19. Parallel workstream map

| Step | Modules | Depends on |
|---|---|---|
| A. Config and types | governance, models | — |
| B. Broker adapter | Alpaca transport | A |
| C. Durable store/journal/execution/recovery | database, store, journal, execution | A, B |
| D. Market/risk/spread | market, risk, spread | A |
| E. Loop/workflow | orchestration, CI | C, D |
| F. AI | brain/evals | A; integrates after E skeleton |
| G. Dashboard | app/projections | journal schema from C |
| H. Activation | workflow/account | C–G |
| I. Submission assets | docs/media | shell after A; final evidence from G/H |

Parallel lanes:

```text
Lane A: A -> B -> C --------------------+
Lane B:     D --------------------------+-> E -> H
Lane C:     F (schema/evals) ------------+     |
Lane D:          G (after schemas freeze)+     +-> I finalization
Lane E:     I shell/storyboard ----------------+
```

Conflict flags:

- A is the shared contract and merges first.
- C and G both depend on journal schema; freeze it before dashboard work.
- D and E both touch orchestration-facing state; integration tests merge after both.
- Only one lane edits `governance.json`, `models.py`, or workflow order permissions at a time.

---

## 20. Activation, deployment, rollback, and emergency behavior

### Gate 0 — Live rules and staffing

- Archive the live submission rules/form and verify actual-trade, MCP/CLI, account, media, deadline, and public-repository requirements.
- PK is accountable owner and on-call; his exact current GitHub login is verified and pinned in the protected manual-recovery actor allowlist; implementation responsibilities and handoff status are visible in the issue/task tracker.
- If a mandatory requirement cannot be met, record no-go rather than substituting an unsupported claim.

### Gate A — Static safety

- Entry-implementation tasks T1–T11 are complete. T13 remains a separate activation blocker because it produces the dated Gate 0/A–E evidence consumed by Gate F. T12 and T14 block final submission; T15 is explicitly nonblocking.
- Configuration validates and hashes.
- Candidate CI, database migration/RLS tests, dependency audit, and current-tree/full-history secret scan pass.
- The `theta-gate-control-freeze` ruleset fixture has update restriction, deletion and force-push protection, no bypass actor/app/admin, and PK-owned `CODEOWNERS`; a rehearsal repository proves unauthorized default-branch update, deletion, and force push are rejected and publisher credentials can update only `theta-gate-publication`.
- Static test proves one broker write boundary and no bulk methods.

### Gate B — Failure rehearsal

- Every lifecycle, runner-loss, fenced-lease takeover, manual HALT during entry, database outage, degraded ambiguous-submit/takeover, crash, overlap, cancel/fill, imbalance, assignment, data, and Git failure scenario passes.
- Quote age, volatility units, price signs, and stop arithmetic are proven.
- Two concurrent stops, two-position flatten, repair plus another exit, and unknown order plus exposed position pass.

### Gate C — Live read-only rehearsal

- The selected immutable runtime tag verifies its GitHub attestation, manifest/signer identity, submission profile, exact endpoint and account HMAC, account status/options level, database roles/lease/HALT/baseline, clock/calendar, bars, chain, VIX data, model, journal, and isolated publication.
- Write invocation is mechanically disabled and the run proves zero order calls.

### Gate D — Throwaway-account write rehearsal

- The exact deployed Actions execution job, release SHA, dependency lock, CLI version, and runner permissions select the throwaway account HMAC and open/close exactly one `$5` put spread through the final adapter.
- Verify negative entry sign, positive exit sign, actual buying-power change, status set, cancel behavior, MLeg leg observations, reconciliation, current client-ID maximum/grammar using every longest V1 form, and assignment/repair commands where safely simulatable.
- Successfully verify the terminal forceful MLeg, single-leg option, and equity exit methods used by degraded recovery. If any required forceful method cannot be verified, submission-account activation is forbidden.
- From two independent throwaway runners released across a synchronization barrier, submit the same longest-form risk-reducing client ID in two canaries: identical bodies, then different valid limit prices with all immutable fields equal. Exactly one broker order may exist per canary; the other response must reject or adopt the accepted broker body, and final inventory must not reverse through flat. Pin the observed response contract; absence or ambiguity blocks Gate F.
- Validate every `RECOVERY_RELEASE_DESCRIPTOR` credential version/fingerprint against isolated job secrets before any broker/control call; wrong purpose, version, fingerprint, missing field, or attempted rotation while `EXACT_FLAT` is false must fail closed. Rotate each recovery-critical credential while `EXACT_FLAT`, issue a new descriptor, and prove the complete Gate D offline recovery and concurrent same-client-ID canaries again before restoring the original throwaway configuration.
- After opening throwaway exposure, test an active runtime failure, an online attestation/trust-service outage, and a run hung after authorization under broker ambiguity while a later ordinary tick is pending/running. The watchdog must validate/deduplicate the typed incident and dispatch retained `RECOVERY_RELEASE_DESCRIPTOR.ref`; offline recovery must durably latch HALT first, cancel and terminally observe every queued/running `agent.yml` execution for the account/active tag without canceling recovery, prove the account, adopt/cancel/reconcile every exact possibly delivered ID, reach the independent recovery group, flatten exposure without reversal/duplication, and demonstrate that no entry/model path is callable.
- Prove the recovery terminal order: broker execution persists fresh clauses-1–3-and-5 evidence and exits successfully; the credential-free finalizer verifies that exact completed job; the one-purpose resolver atomically closes only its incident; only a subsequent full evaluation may persist `EXACT_FLAT`. Failed/skipped/canceled execution, stale/mismatched/replayed evidence, resolver failure, and a second open incident must all leave `EXACT_FLAT=false` and recovery active.
- Reconcile observed behavior against current official MLeg and generic paper docs; record differences without overclaiming.
- Submission credentials are absent.

### Gate E — Full-session dry run

- Replay every scheduled tick for a full session, both entry windows, missed tick, stale feed, model failure, database failure/recovery, Git failure, HALT, and flatten ladder.
- Confirm zero broker writes and a complete parseable event stream.

### Gate F — Submission-account activation

- T13 is complete: Gates 0 and A–E have dated, reviewed evidence; Gate F is not counted as evidence for itself.
- PK verifies the fresh `$100,000` paper account, empty history, exact protected account HMAC, and monitored critical-alert path.
- Exact deployed code/config hashes are recorded.
- Gates 0 and A–E have dated evidence.
- While `EXACT_FLAT`, PK records that default-branch dispatcher/watchdog hashes equal the active manifest, enables the no-bypass `theta-gate-control-freeze` ruleset, and live-probes rejection of unauthorized update, deletion, and force push before entry is enabled.
- The descriptor's exact retained tag, policy/schema hashes, and six recovery-critical credential version/fingerprint pairs match the isolated environments; their rotation is locked until `EXACT_FLAT` and requalification.
- The first and every later V1 spread remains one contract.
- No human places an order in the submission account.

### Rollback

Durable HALT has two independent sources: `account_control.halt_active` in Postgres and protected Actions variable `THETA_GATE_HALT=true`. Startup treats either as active; database unavailability also blocks entries. `data/HALT.example.json` documents the sanitized shape `{schema_version, active, reason_code, activated_at, activated_by, release_sha, version}`. Automated HALT commits the database row transactionally and writes a local emergency copy. The protected human-HALT action first calls a narrowly scoped database function that atomically raises the HALT version, verifies the committed value, then sets the Actions variable and dispatches recovery. An in-flight entry cannot obtain `SUBMIT_AUTHORIZED` after that committed HALT version. If it was authorized just before HALT, the recovery owner treats it as possibly submitted, looks up and cancels it where possible, and reconciles any fill; the plan does not claim that a post-authorization network packet can be recalled. If the database is unavailable, no entry can authorize; the action sets the variable, cancels entry-capable runs, and dispatches `dbout` recovery-only. HALT clearing requires PK, a new monotonic version, broker-confirmed reconciliation, a reason, and both sources cleared deliberately. A stale runner can never clear a newer version.

1. Atomically activate `HALT`; entries stop, exits/reconciliation continue.
2. Do not disable the scheduler/watchdog, unlock the default branch, or rotate a bound credential while `EXACT_FLAT(account_key)` is false.
3. Use the active pinned workflow and concurrency group for ordinary recovery. If active code/preflight cannot run, auto-dispatch the retained offline-preauthorized `RECOVERY_RELEASE_DESCRIPTOR.ref` through the recovery-only workflow without changing `ACTIVE_RELEASE_REF` while exposure exists.
4. Flatten and reconcile before changing any release selector. Only after `EXACT_FLAT(account_key)` may PK roll the active selector back, unlock control workflows, rotate bound credentials, or repair/promote runtime code; every such change requires the prescribed requalification and re-freeze before entries resume.
5. Preserve journal schema compatibility and never rewrite old events.
6. Dashboard rollback is independent from the trading loop.
7. Broker outage leaves explicit unresolved-risk state, automatic later retry, and critical alerts.
8. Any human emergency order is logged and disclosed; it invalidates the claim of a fully autonomous account history from that point onward.

---

## 21. Hackathon delivery plan

The final public package must show:

- an autonomous AI-assisted agent with the model genuinely used but bounded;
- Alpaca CLI and/or MCP usage;
- options paper trading in a fresh `$100,000` account;
- public GitHub repository with genuine implementation history;
- hosted read-only Streamlit demo;
- 3–5 minute video;
- PDF slides;
- 16:9 cover image;
- one-page AI/risk/infrastructure write-up;
- redacted/approved account evidence and required submission account ID field;
- submission before the verified deadline and a retained receipt.

The demo must work even if no live trade passes the gates. Maintain deterministic sanitized replay scenarios for:

1. a passing proposal and complete lifecycle;
2. a named gate veto;
3. model rejection/failure;
4. ambiguous submit recovery;
5. partial/imbalanced inventory repair;
6. stop exit; and
7. deadline flatten.

The write-up leads with architecture and control, not P&L. It reports `n`, quoted/fill slippage, gate outcomes, exceptions, repairs, and the final `EXACT_FLAT` result. It does not use a five-day benchmark comparison as evidence.

---

## 22. What already exists

| Existing asset | Current value | Canonical treatment |
|---|---|---|
| `alpaca.py` | Sole CLI wrapper, paper intent, client-ID lookup, MLeg submit/cancel | Reuse boundary; replace unsafe profile check and incomplete error/state handling |
| `spread.py` | Frozen contracts/plans, chain parsing, MLeg bodies, max-loss math | Reuse pure structure; add timestamps/types/hashes and replace selection logic |
| `risk.py` | Pure gates, sizing, deterministic exit signals | Preserve purity; replace stale thresholds and add full data/exposure gates |
| `governance.json` | Central numeric configuration | Migrate to versioned canonical schema |
| `test_agent.py` | 16 passing primitive tests | Preserve cases, split into focused suites, add lifecycle/adapter/recovery coverage |
| `docs/STRATEGY.md` | Broad strategy/research synthesis | Historical/evidence input; operationally superseded by this document |
| `docs/research/` | Research and adversarial evidence | Cite with evidence grades; do not convert manager anecdotes into hard facts |
| Diagrams | Early architecture/flow/sequence visuals | Update only after implementation matches this architecture |
| Vendored Alpaca skills | Paper, CLI, MCP, backtest guidance | Use as operating references; verify version-sensitive claims at activation |

---

## 23. NOT in scope for V1

| Deferred item | Rationale / reinstatement condition |
|---|---|
| Real-money trading | Not authorized; redesign and independent security/risk approval required |
| Call credit spreads | Second surface and switching rule are unvalidated; reconsider after put-side data |
| Condors, 3/4-leg trades | More state and repair complexity with no hackathon need |
| Dynamic/multi-contract sizing | Five sessions cannot justify scaling; fixed one contract is clearer and safer |
| Rolling or widening | Changes the original risk contract and obscures attribution |
| Tail-hedge sleeve | No coherent six-session budget/exit path; reconsider for a durable post-hackathon portfolio |
| One-sigma strike gate | Conflicts with delta band; log until historically calibrated |
| Credit/delta curve gate | Single-surface observation; log until validated across regimes |
| Backtest performance claim | No reliable historical options fill/assignment dataset is in scope; build a custom simulator later |
| Multi-region/high-availability state platform | A single portable Postgres ledger is required for V1; replicas, failover automation, and a second vendor are deferred |
| Telegram/email/webhook alerts | External communication requires explicit configuration/approval; local/GitHub channels suffice initially |
| Upstream skill PR before core delivery | Useful but not on the activation critical path |
| Automated benchmark-based shutdown | Five days are statistically meaningless; benchmarks are descriptive only |
| Five-day PUT/PUTY performance comparison | Too small to inform the decision and distracts from auditable process evidence |

---

## 24. Implementation tasks

Each task is build-actionable and tied to a blocking finding.

Priority semantics: `P1` blocks activation or submission as explicitly stated. T1–T11 plus the Gate 0/A–E portion of T13 block entry activation; T12, the evidence-packaging remainder of T13, and T14 block final submission; `P3` is post-hackathon.

- [ ] **T1 (P1, human ~2h / coding agent ~20m)** — Governance — replace active numeric rules with the versioned canonical configuration and validation.
  - Files: `governance.json`, `models.py`, `tests/test_models.py`
  - Verify: config rejects missing/unknown/wrong-unit values; hash is stable.
- [ ] **T2 (P1, human ~3h / coding agent ~35m)** — Broker safety — replace CLI profile flags with one `ALPACA_PROFILE` environment and enforce exact paper proof/exit-code handling.
  - Files: `alpaca.py`, `tests/test_alpaca.py`
  - Verify: live/inconclusive fixtures invoke zero writes; every method proves paper.
- [ ] **T3 (P1, human ~3h / coding agent ~40m)** — Broker contract — implement preview parity, required deterministic 48-character-bounded client IDs with keyed 100-bit tokens, normal-mode collision HALT, dbout same-ID price-drift adoption/immutable-field validation, explicit entry/exit/repair/assignment methods, and forbidden-path CI.
  - Files: `alpaca.py`, `tests/test_alpaca.py`
  - Verify: exact command/body assertions and no executable broker writes outside the adapter.
- [ ] **T4 (P1, human ~8h / coding agent ~90m)** — Durable control — implement Postgres schema with no login-role direct DML, allowlisted executor transition RPCs, a one-purpose exact-attempt `incident_resolver` RPC, distinct fresh-`EXACT_FLAT`-gated `halt_admin` clear RPC, 30-second heartbeats and monotonic fenced leases, account-scoped claims/intents/positions/incidents/terminal evidence, baseline, live manual HALT, serialized chain-head append, canonical hashes, sanitized publisher RPC/view, restart-stable degraded exit spool, and broker-evidence spool-loss reconstruction.
  - Files: `db/schema.sql`, `store.py`, `journal.py`, `tests/test_store.py`, `tests/test_journal.py`
  - Verify: runner-loss/takeover/stale-fence, DB-outage, multi-account unique-conflict, exact-incident resolver success plus stale/mismatched/replayed/other-open-incident rejection, concurrent chain append, redaction, restart-stable dedup, RLS, publisher RPC, and degraded-import fixtures.
- [ ] **T5 (P1, human ~8h / coding agent ~90m)** — Execution — implement order state machine including `SUBMIT_AUTHORIZED`, post-authorization HALT/takeover adoption, ambiguity, cancel/fill race, position reconciliation, `dbout` immediate flatten, repair, assignment, and retained exit urgency.
  - Files: `execution.py`, `tests/test_execution.py`, `tests/test_recovery.py`, `tests/test_assignment.py`
  - Verify: failure injection at every transition produces no duplicate and bounded/explained exposure.
- [ ] **T6 (P1, human ~5h / coding agent ~60m)** — Data — implement market calendar, event file, VIX validation, RV20, ATM put IV, chain/spot freshness, and fingerprinting.
  - Files: `market.py`, `data/events_2026-08-31_2026-09-04.json`, `tests/test_market.py`
  - Verify: all stale/malformed/date/unit fixtures fail closed for entries.
- [ ] **T7 (P1, human ~3h / coding agent ~35m)** — Strategy — implement deterministic 6–9 DTE candidate ranking and direct quote-friction rules.
  - Files: `spread.py`, `tests/test_spread.py`
  - Verify: tie-breaks, boundaries, long-leg existence, and numeric fixtures.
- [ ] **T8 (P1, human ~4h / coding agent ~45m)** — Risk — implement canonical gate ordering, fixed quantity/reserves, corrected stops, exit precedence, and diagnostic-only metrics.
  - Files: `risk.py`, `tests/test_risk.py`
  - Verify: pass/fail/equality/missing/non-finite cases for every gate.
- [ ] **T9 (P1, human ~5h / coding agent ~60m)** — Orchestration — implement recovery-first one-tick loop and no-trade behavior.
  - Files: `loop.py`, `tests/test_loop.py`
  - Verify: no entry can precede reconciliation/exits; HALT never blocks exits.
- [ ] **T10 (P1, human ~4h / coding agent ~45m)** — Scheduler — separate candidate CI and the secret-free default-branch scheduler/watchdog from immutable protected runtime tags selected by one `ACTIVE_RELEASE_REF`; add a no-bypass Gate-F default-branch control freeze and publication-only branch; add a distinct retained-tag `RECOVERY_RELEASE_DESCRIPTOR` with pinned recovery-critical credential versions/fingerprints, success-only required-job predicate, typed incident validation/deduplication/retry, halt-latch-before-cancel, terminal-evidence/successful-job/one-purpose-resolver ordering, scheduler suppression, and mechanically recovery-only non-starvable break-glass workflow; add separate agent/recovery concurrency plus an account-global fenced lease, exact UTC schedule, GitHub-attested entry manifest, offline recovery trust, `EXACT_FLAT`-only two-phase staging/one-selector promotion/secret rotation, isolated preflight/execution/finalizer/resolver/publisher jobs, least permissions, and immutable pins.
  - Files: `.github/CODEOWNERS`, `.github/workflows/ci.yml`, `.github/workflows/scheduler.yml`, `.github/workflows/recovery-watchdog.yml`, `.github/workflows/agent.yml`, `.github/workflows/recovery.yml`, `ops/github/theta-gate-control-freeze.json`, `scripts/apply_control_freeze.py`, `tests/test_workflow.py`
  - Verify: before activation the default branch may differ from the active runtime tag without suppressing last-known-good recovery; after Gate F, unauthorized default-branch update/delete/force-push and publisher-to-default writes fail; active selector change yields a complete old-or-new release; forged/stale/wrong-ref attestation and wrong credential purpose/version/fingerprint fail before broker access; online verifier outage does not block offline-preauthorized recovery; secret rotation is rejected unless `EXACT_FLAT` and then forces descriptor/Gate-D requalification; only selected/retained protected tags can receive scoped environments; healthy/publisher-only/untrusted/reused incidents reject while every required-job non-success qualifies; terminal evidence precedes successful execution conclusion, which precedes exact-job finalizer validation, one-purpose incident resolution, and only then fresh `EXACT_FLAT`; HALT precedes cancellation and all later entry authorization; ordinary pending/running ticks cannot displace recovery; active-runtime failure with exposure is flattened once by the retained recovery-only tag; cron/manual overlap and Git failure do not duplicate or expose secrets.
- [ ] **T11 (P1, human ~3h / coding agent ~35m)** — AI — implement one strict proposer, scrubbed environment, optional isolated MCP, injection handling, and evals.
  - Files: `brain.py`, `tests/test_brain.py`, eval fixtures
  - Verify: safety evaluation targets in §17.4.
- [ ] **T12 (P1, human ~4h / coding agent ~45m)** — Dashboard — implement read-only, freshness-aware Streamlit projections.
  - Files: `app.py`, `tests/test_app.py`
  - Verify: cold URL, zero broker/model imports, corrupt/stale states visible.
- [ ] **T13 (P1 activation blocker, human ~6h / coding agent ~75m)** — Activation evidence — run and review Gate 0 plus static, failure, live-read, throwaway-write, and full-session Gates A–E before Gate F can enable the submission account.
  - Files: test artifacts and `data/events.jsonl`; no source shortcut.
  - Verify: dated evidence for Gate 0 and Gates A–E; after Gate F, package the activation record for final submission without treating Gate F as its own prerequisite.
- [ ] **T14 (P1, human ~6h / coding agent ~60m)** — Submission — produce, verify, and submit every required public artifact with final `EXACT_FLAT` proof.
  - Files: README/docs/media outputs as required by verified hackathon form.
  - Verify: external URL checks, receipt, public secret scan, and independent evidence satisfying all five `EXACT_FLAT` clauses.
- [ ] **T15 (P3, post-hackathon)** — Skill contribution — author and upstream the tested options-spreads skill.
  - Files: separate upstream fork plus vendored skill after verification.
  - Verify: upstream validation/CI and every version-sensitive claim confirmed or removed.

---

## 25. Failure-mode register

| Failure | Detection | Automated response | Test | User visibility |
|---|---|---|---|---|
| Paper not proven | Exact doctor endpoint/exit failure | Zero write, critical HALT | Adapter contract | Critical alert/dashboard |
| Wrong paper account | Protected account-HMAC mismatch | Zero write, critical HALT | Adapter/workflow contract | Critical alert |
| Durable ledger unavailable | Connection/transaction failure | Block entries; recovery-only exits use degraded spool | Store/replay E2E | Critical integrity banner |
| Database fails with exposure | Lease/control read failure + broker position | Cancel recognized entries; immediately flatten recognized exposure under deterministic `dbout` IDs | Recovery E2E | Critical integrity banner |
| Degraded spool lost with runner | Broker history/client-ID reconstruction | Append `spool_lost_reconstructed`; disclose gap; HALT if evidence insufficient | Recovery E2E | Critical integrity banner |
| Candidate CI/config fails | CI or candidate validation | Active pinned recovery release still runs; no candidate promotion | Workflow E2E | Deployment blocked |
| Mixed/invalid release selection | Tag/SHA/manifest/attestation mismatch | No secrets or entries; retain/restore complete old selector only under `EXACT_FLAT` | Workflow E2E | Deployment blocked |
| Frozen control workflow mutation | Default-branch update/delete/force-push or publisher-to-default attempt | Repository ruleset rejects; HALT if observed after activation; preserve retained recovery | Gate A/F workflow | Security-critical |
| Recovery credential drift/rotation | Descriptor purpose/version/fingerprint mismatch | Reject before broker/control use; keep incident/HALT unresolved; rotate only under `EXACT_FLAT` and requalify Gate D | Adapter/workflow/Gate D | Security-critical |
| False-flat claim | Any failed/stale broker read, unresolved intent/incident, or audit gap | `EXACT_FLAT=false`; recovery and schedules remain active; submission blocked | Store/recovery/submission | Critical |
| Forged or stale attestation | GitHub verifier identity/digest failure | Fail preflight before environment secrets | Workflow E2E | Critical deployment alert |
| Online attestation service unavailable with exposure | Active preflight verification failure | Watchdog dispatches offline-preauthorized retained recovery descriptor | Gate D/workflow E2E | Critical until flat |
| Active runtime fails with exposure | Preflight/process failure plus broker exposure | Force HALT; dispatch retained offline-preauthorized recovery descriptor; flatten/reconcile | Gate D/workflow E2E | Critical until flat |
| Required execution skipped/other non-success | Exact required-job conclusion pair | Treat as `run:` incident; latch HALT and recover | Workflow | Critical until resolved |
| Untrusted/reused recovery dispatch | Secret-free incident validation/digest lookup | Reject before protected environment/secrets | Workflow | Security alert |
| Recovery attempt fails/unresolved | Non-success or no broker-confirmed terminal result | Keep incident open; serialized same-key retry with backoff | Recovery E2E | Critical until resolved |
| Recovery pending behind ordinary ticks | Open incident plus Actions run inventory | Latch HALT, cancel all agent runs, use independent recovery group/fenced lease | Workflow E2E | Critical until admitted |
| Model malformed/down | Schema/timeout/tool error | `NO_TRADE`; exits unaffected | Brain unit/eval | Named veto |
| Cboe/event feed stale | Date/schema/freshness gate | `NO_TRADE`; exits unaffected | Market unit | Named veto |
| Bar/quote unit error | Type/range/non-finite validation | `NO_TRADE` | Market/risk unit | Data error |
| Submit timeout | No response | Lookup same client ID, reconcile | Recovery | High alert |
| HALT/takeover after submit authorization | Higher HALT/fence version with unresolved authorized intent | Lookup/cancel/reconcile exact ID; never duplicate | Execution/recovery | Critical until reconciled |
| Duplicate/stale runner | Concurrency/fence/window/client ID | One decision lineage; stale owner cannot newly authorize; prior authorized intent is adopted | Workflow/recovery | Audit event |
| Concurrent no-DB recovery submit | Same deterministic ID from two runners | Broker accepts exactly one; loser adopts/reconciles; no opposite exposure | Gate D/recovery | Critical if invariant differs |
| Client-ID collision/body mismatch | Composite unique row + canonical body comparison | HALT; never regenerate or submit | Adapter/store | Critical alert |
| Cancel/late fill | Terminal status + position delta | Reconcile actual inventory | Execution | High alert |
| Short-only fill | Position leg mismatch | Buy to close short first | Execution E2E | Critical until safe |
| Long-only fill | Position leg mismatch | Sell to close unpaired long | Execution E2E | High alert |
| Unknown order status | Unrecognized enum | HALT entries, reconcile, alert | Execution | Critical |
| Exit rejected/unfilled | Nonterminal/terminal failure | Retain exit urgency, retry/escalate | Execution E2E | Critical if deadline |
| Assignment | Equity inventory + mapping | HALT; flatten stock; then long option | Assignment E2E | Critical |
| Broker outage | CLI/network errors | HALT entries; retry recovery/exits | Replay | Unresolved-risk banner |
| Event chain/schema failure | Ledger verification | Durable HALT; reconcile; no silent skip | Store/journal | Critical banner |
| Degraded spool not imported | Spool/ledger comparison | Retry idempotent import; show audit gap | Journal/store | High alert |
| Git push conflict/failure | Publisher exit | Durable ledger retained; no trade rerun; retry publisher | Workflow | High alert |
| Terminal forceful method unavailable | Gate D or runtime method failure | Activation blocked or early flatten; latched retry | Gate D/execution | Critical |
| Dashboard stale/down | Last tick/health probe | Trading unaffected | App/deploy check | Stale/outage state |
| Missed tick | Gap > configured threshold | Alert; next tick recovers; no catch-up entry | Loop/workflow | High alert |
| Three tick failures | Event counter | HALT entries; continue recovery attempts | Loop | Critical |
| Human emergency order | Broker discrepancy/manual record | HALT, reconcile, disclose autonomy break | Recovery/manual drill | Public disclosure |

No listed failure is both silent and without a test/error path. Any newly discovered silent failure becomes P1 and blocks activation.

---

## 26. Final Definition of Done

Theta Gate V1 is complete only when all of the following are true:

- [ ] This document is linked as the sole V1 implementation authority; source documents remain unchanged.
- [ ] One deployed code commit and one validated config hash are recorded.
- [ ] Every P1 task is complete and all tests pass in the actual Actions environment.
- [ ] The submission account is mechanically proven paper-only, fresh, and initially `$100,000`.
- [ ] The model has no broker write tool or credential and cannot influence strikes, expiry, quantity, price, gates, or exits.
- [ ] Every entry write passed through the paper/account-asserting adapter with a remotely committed intent, bounded semantic client ID, and matching dry run; every risk-reducing degraded write used the same adapter and a deterministic broker-recoverable ID. Each degraded action has either a durable spool import or an explicit broker-evidence `spool_lost_reconstructed` record; any reconstructed gap is disclosed and no unresolved gap remains.
- [ ] Crash, duplicate-run, ambiguous-submit, cancel/fill, partial/imbalanced fill, assignment, stale data, model failure, broker failure, Git failure, and failed-exit scenarios have dated passing evidence.
- [ ] At least one autonomous one-contract lifecycle completes on paper if the archived live rules require an actual trade; otherwise a clearly labeled replay may demonstrate failure paths but is never presented as broker history.
- [ ] The journal parses fully, preserves lifecycle order, contains no protected data, and reconciles to broker history.
- [ ] The dashboard works cold from outside, shows freshness/integrity state, and contains no write controls or secrets.
- [ ] Before submission, an independent reconciliation records current evidence satisfying every `EXACT_FLAT(account_key)` clause; schedules and the control freeze remain active until that evidence and the submission receipt are durable.
- [ ] Current tree and full Git history pass secret/security review.
- [ ] Repository, URL, video, slides, cover, write-up, account field, and deadline are independently verified against the live submission form.
- [ ] The write-up reports sample size, assumptions, slippage, failures, interventions, and no unsupported edge claim.
- [ ] A submission receipt is retained before the verified deadline.

Anything less is a prototype or a read-only demonstration. It is not an activated controlled autonomous trading agent.

---

## 27. Decision log

| Decision | Resolution | Reason |
|---|---|---|
| Source-plan relationship | One canonical document; sources preserved | Prevent contradictory operational authority |
| V1 side | Put credit only | Removes unvalidated call branch and surface |
| Model-selected DTE | Removed | Deterministic financial resolver owns expiry |
| Target delta | `0.20` within `0.16–0.25` | Simple deterministic center; still a hypothesis |
| DTE | 6–9 calendar days plus flatten buffer | Avoid near-flatten expiries without fake linear-theta claims |
| Quantity | One contract throughout V1 | Sample cannot justify scaling |
| Stop | Close-debit multiple `2.0`; example loss `$60` on `$0.60` credit | Correct arithmetic and naming |
| Quote age | 60 seconds | 600 seconds is unsafe for short-dated options |
| Sigma distance | Diagnostic only | One sigma conflicts with delta band |
| Credit/delta curve | Diagnostic only | One observed surface is insufficient |
| VIX lower bound | Removed | No validated marginal safety case beyond direct credit/VRP checks; those checks do not guarantee rejection below VIX 12 |
| VIX/regime/VRP | Enforced hypotheses | Consistency and risk reduction, not proven alpha |
| Partial-fill claim | Unverified platform behavior; defensive recovery retained | Official documents describe behavior differently |
| Margin | Reserve full width internally; re-probe broker BP | Avoid universal claim from conflicting evidence |
| Journal | Append-only lifecycle events | Pre-fill and post-fill facts occur at different times |
| Event serialization | Account-scoped locked chain head | Concurrent executor, publisher, and import appenders cannot fork the hash chain |
| Event idempotency | Lifecycle keys exclude run ID and include durable entity version | Restart changes tracing metadata, not logical-event identity |
| Account namespace | Composite account keys and account-scoped position hashes | Throwaway and submission ledgers may reuse semantic IDs safely |
| Database authority | Login roles call fixed transition RPCs; only `halt_admin` can clear HALT | A current executor credential cannot bypass the HALT state machine with direct DML |
| Recovery admission | One-RPC `halt_latch`, cancel all agent runs, independent recovery group | Emergency recovery cannot be displaced while a later agent authorizes entry |
| Lease | 30-second heartbeat, 180-second TTL, monotonic fence | Expiry alone cannot stop a paused stale runner |
| Manual HALT | Database first; live pre-preview/pre-submit check | Job-start Actions variables cannot stop an in-flight entry |
| Database-outage recovery | Broker-state-derived finite IDs; risk reduction only | Runner and local-spool loss must not create blind retries |
| Degraded concurrent idempotency | Gate D must prove broker-atomic same-ID uniqueness | Lookup-before-submit alone cannot close a cross-runner TOCTOU race |
| DB-outage latch | Immediately flatten recognized exposure under fixed `dbout` reason | A local trigger/spool cannot be the sole copy of exit urgency |
| Submit race | `SUBMIT_AUTHORIZED` is the control-plane linearization point | A later HALT cannot recall an authorized packet, so exact-ID cancel/reconcile is mandatory |
| Daily baseline | Exact cent-normalized `last_equity`; one-cent difference conflicts | Drawdown authority cannot depend on an undefined materiality tolerance |
| Exact flatness | One five-clause broker-and-ledger `EXACT_FLAT` predicate | No empty-position shortcut may clear HALT, stop recovery, unlock controls, rotate credentials, or certify submission |
| Control workflow freeze | No-bypass default-branch ruleset from Gate F through `EXACT_FLAT` plus receipt | Mutable scheduled YAML cannot strand recovery or silently change dispatch authority during exposure |
| Recovery secret binding | Versioned, non-secret fingerprints in the retained descriptor | Recovery cannot silently use a rotated or mismatched client-ID/account/broker/database/HALT credential |
| Release promotion | Immutable SHA-named runtime tags plus one `ACTIVE_RELEASE_REF` selector | A tick sees a complete old or new release; promotion is `EXACT_FLAT`-only and rollback preserves the old tag |
| Break-glass recovery | Separate retained `RECOVERY_RELEASE_DESCRIPTOR`, recovery-only workflow | Failed active code or online verifier cannot strand exposure; recovery authority can never authorize entry |
| Recovery incidents | Typed keys, secret-free source validation, serialized dedup, terminal evidence -> successful job -> one-purpose resolution, unresolved retry | The current incident closes without circular flatness logic; failed, replayed, or final-tick recovery cannot silently force or suppress action |
| Release trust | GitHub OIDC artifact attestation with pinned verifier and signer identity | Secret-free CI can prove manifest provenance without a long-lived key |
| Client IDs | 48-character grammar plus keyed 100-bit token and collision HALT | Broker-valid, restart-stable IDs do not depend on full SHA text |
| Lost degraded spool | Reconstruct from deterministic IDs and broker history; disclose gap | Audit loss cannot be falsely represented as an imported local record |
| Monitoring | Real-time tested alert or maximum five-minute active polling | A 15-minute check cannot satisfy a five-minute response target |
| Git | Post-tick publication only | Cannot be execution state or trigger retries |
| Dashboard | Read-only file projection | Keeps public UI outside broker/secret boundary |
| Upstream skill | Post-core, nonblocking | Critical path is a safe working agent and submission |

---

## 28. Source registry

Primary implementation references:

- Alpaca paper trading limitations and simulation behavior: <https://docs.alpaca.markets/docs/paper-trading>
- Alpaca options Level 3 and MLeg behavior: <https://docs.alpaca.markets/docs/options-level-3-trading>
- Alpaca options permissions and paper availability: <https://docs.alpaca.markets/docs/options-trading>
- Vendored local operating references:
  - `.agents/skills/alpaca-trading-paper-trading/SKILL.md`
  - `.agents/skills/alpaca-trading-paper-trading-cli/SKILL.md`
  - `.agents/skills/alpaca-trading-paper-trading-mcp/SKILL.md`
  - `.agents/skills/alpaca-trading-backtest/SKILL.md`
- Project research: `docs/research/best-options-traders-1996-2026.md`
- Historical plans, preserved but operationally superseded:
  - `docs/PLAN.md`
  - `docs/STRATEGY.md`
  - supplied `theta-gate-implementation-plan.md` (identified by the SHA-256 in this document)
  - supplied `STRATEGY.md` (identified by the SHA-256 in this document)

Version-sensitive facts—CLI flags, endpoint output, MLeg schema/status behavior, paper partial fills, price sign, buying-power treatment, and hackathon submission requirements—must be reverified at the activation boundary. A dated successful probe is evidence for that account/version, not a permanent platform guarantee.

---

## GSTACK REVIEW REPORT

| Review | Scope | Runs | Status | Result |
|---|---|---:|---|---|
| Financial/safety analysis | Strategy arithmetic, sizing, claims, paper-only exposure | 1 | CLEAR | Corrected stop arithmetic, bounded V1 risk, and separated hypotheses from verified behavior |
| Architecture/research review | Control ledger, broker boundary, release/recovery architecture, implementation coverage | Multiple convergence passes | CLEAR | No unresolved P0/P1 architecture gap |
| Engineering plan review | Implementability, dependencies, failure modes, tests, rollback, operations | 1 full review | CLEAR | 22 remediation work packages folded into the canonical plan |
| Adversarial review | Race conditions, authority drift, recovery liveness, trust, terminal-state logic | Multiple convergence passes | CLEAR | Final circular incident-resolution defect corrected and independently cleared |
| CEO review | Separate `/plan-ceo-review` run | 0 | NOT RUN | Scope was an implementation authority; strategic, financial, and adversarial decision lenses were applied directly |
| Cross-model Codex review | External Codex review | 0 | SKIPPED | This plan was produced in Codex; no unsupported cross-model review claim |
| Design review | Implemented UI | 0 | NOT APPLICABLE | Dashboard design remains an implementation-stage deliverable |
| Developer-experience review | Implemented developer workflow | 0 | NOT APPLICABLE | No code or workflow implementation exists yet |

**VERDICT:** ENGINEERING + ARCHITECTURE + FINANCIAL + ADVERSARIAL REVIEWS CLEARED — READY TO IMPLEMENT

NO UNRESOLVED DECISIONS
