"""Standalone live-gate smoke check -- read-only, no journal writes, no git,
no broker submissions. Mirrors loop.py's _attempt_entry_pipeline's functions
and call order (same market.py -> brain.py -> spread.py -> risk.py wiring,
same state-building) but walks the gates from a clean Monday-open state: no
open positions, entries_today 0, no journal read. Run manually or as the
agent.yml `gate_check` dispatch, market open or closed, to check the
deterministic gate stack and brain.py's live SDK call against real data.
Exits 1 on any collected failure so a runner smoke job fails loudly.
"""

import dataclasses
import json
import sys
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import alpaca
import brain
import loop
import market
import risk
import spread

ET = ZoneInfo("America/New_York")


def main():
    now = datetime.now(ET)
    failures = []
    print(f"=== live-gate sanity check -- {now.isoformat()} ===\n")

    with open("governance.json", encoding="utf-8") as f:
        gov = json.load(f)

    print("--- assert_paper + account ---")
    account = alpaca.account(profile="submission")
    account_state = loop._map_account_state(account)
    print(json.dumps(account_state, indent=2))
    # An account-level veto (status, options level) would otherwise only
    # show up as a tally line per candidate and exit 0.
    account_reason = risk.gate_account_ready(dict(account_state), None, gov, now)
    if account_reason:
        print(f"account gate: {account_reason}")
        failures.append(f"account_ready: {account_reason}")

    print("\n--- regime state (VIX family + event calendar) ---")
    try:
        regime = market.build_regime_state(now, gov["entry"]["event_calendar_path"], gov["regime"]["vix_source_url_template"])
        print(json.dumps({k: v for k, v in regime.items() if k != "event_blackouts"}, indent=2))
        print(f"event_blackouts: {len(regime['event_blackouts'])} windows loaded")
    except market.MarketDataError as exc:
        print(f"MarketDataError: {exc}")
        sys.exit(1)

    print("\n--- underlying states ---")
    underlying_states = {}
    for u in gov["strategy"]["underlyings"]:
        try:
            u_state = market.build_underlying_state(u, now, gov["strategy"]["dte_min"], gov["strategy"]["dte_max"], profile="submission",
                                                    rv_lookback_days=gov["vrp"]["realised_vol_lookback_days"])
        except market.MarketDataError as exc:
            print(f"{u}: MarketDataError: {exc}")
            failures.append(f"{u}_market_data: {exc}")
            continue
        underlying_states[u] = u_state
        contracts, spot = u_state["contracts"], u_state["spot"]
        strikes = sorted(c.strike for c in contracts)
        lo, hi = (strikes[0], strikes[-1]) if strikes else (0.0, 0.0)
        print(f"{u}: spot={spot:.2f}  rv={u_state['realised_vol']:.4f}  "
              f"intraday_move={u_state['intraday_move_pct']:.4%}  contracts={len(contracts)}  "
              f"expiries={len({c.expiry for c in contracts})}  strikes={lo:.2f}..{hi:.2f}")
        # The chain's strike window must span the short-delta band and bracket
        # spot, or rank_candidates has nothing to rank. Expiry count is
        # informational only: on a weekend the 6-9 DTE window can hold a
        # single expiry.
        if len(contracts) < 20:
            failures.append(f"{u}_contracts: {len(contracts)} < 20")
        if lo > 0.95 * spot:
            failures.append(f"{u}_min_strike: {lo:.2f} > 0.95 * spot ({0.95 * spot:.2f})")
        if hi < spot:
            failures.append(f"{u}_max_strike: {hi:.2f} < spot ({spot:.2f})")

    print("\n--- brain.propose (real SDK call, real market data, no fabricated context) ---")
    brain_context = {u: {k: v for k, v in s.items() if k != "contracts"} for u, s in underlying_states.items()}
    brain_context.update({"vix": regime["vix"], "vix9d": regime["vix9d"], "vix3m": regime["vix3m"],
                          "available_underlyings": list(underlying_states)})
    propose_result = brain.propose(brain_context, now)
    print(f"schema_version={propose_result.schema_version}  model={propose_result.model}  "
          f"latency={propose_result.latency_seconds:.2f}s")
    print(f"raw_response: {propose_result.raw_response!r}"[:500])
    direction = "bull_put"  # diagnostic default: the only direction V1 ever proposes real strikes for
    if propose_result.proposal:
        print(f"proposal: {dataclasses.asdict(propose_result.proposal)}")
        direction = risk.resolve_direction(propose_result.proposal.direction)
        if direction is None:
            # HARD_SAFETY (canonical Sec 6.1): bearish is NO_TRADE by design, not a failure;
            # keep the diagnostic gate walk on bull_put so the stack is still exercised.
            print("direction: bearish -> NO_TRADE by design; gate walk below uses bull_put for diagnostics")
            direction = "bull_put"
    else:
        print("proposal: None (model_failure_or_malformed)")
        failures.append("proposal_none")

    print("\n--- gate stack, every candidate, both directions reachable in V1 ---")
    for u, u_state in underlying_states.items():
        candidates = spread.rank_candidates(
            u_state["contracts"], direction, gov["strategy"]["width_dollars"],
            gov["strategy"]["short_delta_min"], gov["strategy"]["short_delta_max"], now,
        )
        base_gate_state = {
            **account_state, "paper_verified": True, "halt_active": False,
            "open_positions": [], "entries_today": 0, "consecutive_exceptions": 0,
            "realised_vol": u_state["realised_vol"], "intraday_move_pct": u_state["intraday_move_pct"],
            "vix": regime["vix"], "vix9d": regime["vix9d"], "vix3m": regime["vix3m"],
            "event_blackouts": regime["event_blackouts"], "filled_underlyings_today": [],
        }
        tally = Counter()
        winner, winner_qty = None, 0
        for candidate in candidates:
            candidate = dataclasses.replace(candidate, underlying=u)
            expiry_puts = [c for c in u_state["contracts"] if c.expiry == candidate.expiry]
            atm_iv = market.compute_atm_iv(expiry_puts, u_state["spot"])
            gate_state = {**base_gate_state, "atm_iv": atm_iv}
            reason, qty = risk.check_all(gate_state, candidate, gov, now)
            if reason is None and winner is None:
                winner, winner_qty = candidate, qty
            tally[(reason or "PASS").split(":")[0]] += 1

        print(f"\n{u}: {len(candidates)} candidates considered")
        for reason, count in tally.most_common():
            print(f"  {reason}: {count}")
        if winner:
            print(f"  => WOULD ENTER: short {winner.short.symbol} / long {winner.long.symbol}  "
                  f"credit={winner.credit:.2f}  qty={winner_qty}  expiry={winner.expiry}")
        else:
            print("  => no candidate passed every gate")

    if failures:
        print("\n=== FAILURES ===")
        for failure in failures:
            print(f"  {failure}")
        print("=== read-only, nothing journaled, nothing committed, no orders touched ===")
        sys.exit(1)
    print("\n=== done -- read-only, nothing journaled, nothing committed, no orders touched ===")


if __name__ == "__main__":
    main()
