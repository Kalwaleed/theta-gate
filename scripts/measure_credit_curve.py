"""Read-only: what credit does a $5-wide vertical actually pay at 3-5 DTE?

Answers the question the tenor change (governance dte 6-9 -> 3-5, commit
2f0472f) left open: at fixed delta, premium falls with tenor, so a short-DTE
credit may not clear gate_credit_quality (+/-40% of 0.8 x delta, a curve
measured at 6-9 DTE and carrying NO tenor term) or gate_minimum_credit
(10% of width). If it does not, the tenor change buys nothing.

Also sweeps width, because governance.json records credit/width FALLING as
width grows (5-wide 0.120 -> 25-wide 0.056) and nothing below $5 has ever
been measured.

Places nothing. Reads chain + quotes only, writes no journal. Safe any time,
but option quotes before 09:30 ET are stale and wide -- run it after the open
for a number worth acting on.

    PYTHONPATH=. .venv/bin/python3 scripts/measure_credit_curve.py
"""
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import market
import risk
import spread

ET = ZoneInfo("America/New_York")
GOV = json.load(open("governance.json"))
WIDTHS = [1.0, 2.0, 3.0, 5.0]
BANDS = {"3-5 DTE (now live)": (3, 5), "6-9 DTE (previous)": (6, 9)}


def verdict(plan, gov):
    """The two credit gates, by name, so the output says which one bites."""
    out = []
    for gate in (risk.gate_credit_quality, risk.gate_minimum_credit):
        reason = gate({}, plan, gov, datetime.now(ET))
        out.append(gate.__name__.replace("gate_", "") + (": PASS" if reason is None else f": VETO ({reason})"))
    return out


def main():
    now = datetime.now(ET)
    dmin, dmax = GOV["strategy"]["short_delta_min"], GOV["strategy"]["short_delta_max"]
    print(f"{now.isoformat(timespec='seconds')}  delta band {dmin}-{dmax}  "
          f"expected ratio = {GOV['strategy']['credit_quality_expected_ratio']} x delta, "
          f"max deviation {GOV['strategy']['credit_quality_max_deviation']:.0%}, "
          f"floor {GOV['strategy']['min_credit_pct_of_width']:.0%} of width\n")

    for underlying in GOV["strategy"]["underlyings"]:
        for label, (lo, hi) in BANDS.items():
            try:
                state = market.build_underlying_state(
                    underlying, now=now, dte_min=lo, dte_max=hi,
                    profile="submission",
                    rv_lookback_days=GOV["vrp"]["realised_vol_lookback_days"],
                )
            except Exception as e:                      # noqa: BLE001 - report, never raise
                print(f"{underlying} {label}: no data -- {type(e).__name__}: {e}\n")
                continue

            contracts = state.get("contracts") or []
            print(f"== {underlying}  {label}  spot {state.get('spot')}  {len(contracts)} put contracts")
            if not contracts:
                print("   chain empty\n")
                continue

            for width in WIDTHS:
                plans = spread.rank_candidates(contracts, "bull_put", width, dmin, dmax, now)
                if not plans:
                    print(f"   ${width:>4.0f} wide: no strike pair at this width")
                    continue
                p = plans[0]
                ratio = p.credit / p.width
                expected = GOV["strategy"]["credit_quality_expected_ratio"] * abs(p.short.delta)
                dev = abs(ratio - expected) / expected if expected else float("nan")
                dte = (datetime.strptime(p.short.expiry, "%Y-%m-%d").date() - now.date()).days
                print(f"   ${width:>4.0f} wide: credit ${p.credit:.2f}  ratio {ratio:.3f}  "
                      f"delta {abs(p.short.delta):.3f}  expected {expected:.3f}  dev {dev:>4.0%}  "
                      f"{dte}d  margin ${width * 100:.0f}  credit/margin {p.credit * 100 / (width * 100):.3f}")
                for line in verdict(p, GOV):
                    print(f"        {line}")
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
