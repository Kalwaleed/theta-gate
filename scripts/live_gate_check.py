"""Standalone live-gate sanity check -- read-only, no journal writes, no git,
no broker submissions. Mirrors loop.py's _attempt_entry_pipeline exactly
(same functions, same state-building, same gate-loop order) so results
reflect real production wiring, not a simplified stand-in. Run manually,
market open or closed, to check the deterministic gate stack (market.py ->
spread.py -> risk.py) and brain.py's live SDK call against real data.
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
    print(f"=== live-gate sanity check -- {now.isoformat()} ===\n")

    with open("governance.json", encoding="utf-8") as f:
        gov = json.load(f)

    print("--- assert_paper + account ---")
    account = alpaca.account(profile="submission")
    account_state = loop._map_account_state(account)
    print(json.dumps(account_state, indent=2))

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
            continue
        underlying_states[u] = u_state
        print(f"{u}: spot={u_state['spot']:.2f}  rv20={u_state['realised_vol_20d']:.4f}  "
              f"intraday_move={u_state['intraday_move_pct']:.4%}  contracts={len(u_state['contracts'])}")

    print("\n--- brain.propose (real SDK call, real market data, no fabricated context) ---")
    brain_context = {u: {k: v for k, v in s.items() if k != "contracts"} for u, s in underlying_states.items()}
    brain_context.update({"vix": regime["vix"], "vix9d": regime["vix9d"], "vix3m": regime["vix3m"]})
    propose_result = brain.propose(brain_context, now)
    print(f"schema_version={propose_result.schema_version}  model={propose_result.model}  "
          f"latency={propose_result.latency_seconds:.2f}s")
    print(f"raw_response: {propose_result.raw_response!r}"[:500])
    if propose_result.proposal:
        print(f"proposal: {dataclasses.asdict(propose_result.proposal)}")
    else:
        print("proposal: None (model_failure_or_malformed)")

    print("\n--- gate stack, every candidate, both directions reachable in V1 ---")
    direction = risk.resolve_direction("bullish")  # -> "bull_put", the only direction V1 ever proposes real strikes for
    for u, u_state in underlying_states.items():
        candidates = spread.rank_candidates(
            u_state["contracts"], direction, gov["strategy"]["width_dollars"],
            gov["strategy"]["short_delta_min"], gov["strategy"]["short_delta_max"], now,
        )
        base_gate_state = {
            **account_state, "paper_verified": True, "halt_active": False,
            "open_positions": [], "entries_today": 0, "consecutive_exceptions": 0,
            "realised_vol_20d": u_state["realised_vol_20d"], "intraday_move_pct": u_state["intraday_move_pct"],
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

    print("\n=== done -- read-only, nothing journaled, nothing committed, no orders touched ===")


if __name__ == "__main__":
    main()
