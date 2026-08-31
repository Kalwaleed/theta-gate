"""State-builder for the Theta Gate entry pipeline. Fetches market data --
via alpaca.py (the broker) and Cboe's public VIX-family CSVs directly -- and
turns it into the plain-dict state risk.py's gates read, and the plain
Contract list spread.py's selection functions consume. No decisions live
here; this module only assembles inputs, so risk.py stays the only
component holding a real decision.
"""

import csv
import json
import math
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from io import StringIO
from zoneinfo import ZoneInfo

import alpaca
import spread

ET = ZoneInfo("America/New_York")


class MarketDataError(RuntimeError):
    """Raised when a market data source is unavailable, stale, or malformed.
    Callers (loop.py) must treat this as NO_TRADE for entries, never let it
    propagate into a crash, and never let it block exit/reconciliation logic
    (which doesn't depend on this module's fresh data)."""


# ---------------------------------------------------------------------------
# VIX family (Cboe)
# ---------------------------------------------------------------------------

def _fetch_csv_last_row(url: str) -> tuple[str, float]:
    """Fetches one Cboe VIX-family CSV and returns (date, close) from its
    last row. Header is exactly DATE,OPEN,HIGH,LOW,CLOSE, DATE is MM/DD/YYYY,
    sorted ascending so the last row is the most recent session -- verified
    live 29 Aug 2026, plain urllib with no extra headers needed."""
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            body = resp.read().decode("utf-8")
    except (urllib.error.URLError, OSError) as exc:
        raise MarketDataError(f"could not fetch {url}: {exc}") from exc

    if not body.strip():
        raise MarketDataError(f"empty response from {url}")

    rows = list(csv.DictReader(StringIO(body)))
    if not rows:
        raise MarketDataError(f"no data rows in CSV from {url}")

    last = rows[-1]
    if "DATE" not in last or "CLOSE" not in last:
        raise MarketDataError(f"malformed CSV from {url}: missing DATE/CLOSE columns")

    date_str, close_str = last["DATE"], last["CLOSE"]
    if not date_str:
        raise MarketDataError(f"missing DATE in last row from {url}")
    try:
        close = float(close_str)
    except (TypeError, ValueError):
        raise MarketDataError(f"non-numeric CLOSE {close_str!r} from {url}")
    if not math.isfinite(close) or close <= 0:
        raise MarketDataError(f"invalid CLOSE {close} from {url}")
    return date_str, close


def fetch_vix_family(now: datetime, url_template: str, max_age_days: int = 4) -> dict:
    """Fetches VIX, VIX9D, VIX3M from Cboe's public CSVs via urllib.request
    -- stdlib only, this project's deliberate zero-HTTP-dependency choice
    (see requirements.txt). All three must report the same last-row date, or
    one feed is stale relative to the others and the regime read as a whole
    can't be trusted.

    max_age_days is a simpler approximation of "must equal the immediately
    preceding trading session": it counts calendar days, not exchange
    sessions, so it can't tell a legitimate long-weekend gap from a genuinely
    stale feed. A known, deliberate simplification, not full
    exchange-calendar precision.
    """
    rows = {
        key: _fetch_csv_last_row(url_template.format(symbol=symbol))
        for key, symbol in (("vix", "VIX"), ("vix9d", "VIX9D"), ("vix3m", "VIX3M"))
    }

    dates = {key: date for key, (date, _) in rows.items()}
    if len(set(dates.values())) != 1:
        raise MarketDataError(f"VIX-family feeds disagree on last date: {dates}")

    as_of_date = datetime.strptime(next(iter(dates.values())), "%m/%d/%Y").date()
    age_days = (now.astimezone(ET).date() - as_of_date).days
    if age_days > max_age_days:
        raise MarketDataError(
            f"VIX-family last date {as_of_date.isoformat()} is {age_days}d behind now -- stale"
        )

    return {
        "vix": rows["vix"][1],
        "vix9d": rows["vix9d"][1],
        "vix3m": rows["vix3m"][1],
        "as_of": as_of_date.isoformat(),
    }


# ---------------------------------------------------------------------------
# Realised vol / intraday move (Alpaca daily bars)
# ---------------------------------------------------------------------------

def compute_realised_vol(daily_bars: list[dict], now: datetime, lookback_days: int = 20) -> tuple:
    """Trailing realised vol, annualised, over the last `lookback_days`
    complete sessions -- the window is governance vrp.realised_vol_lookback_days
    (10 as of 30 Aug 2026, option C in docs/ANALYSIS-2026-08-30.md).
    Excludes any bar whose ET date is NOT strictly before now's ET date --
    the current, possibly-incomplete session must never leak into a return
    meant to already be closed. Requires >= lookback_days + 1 complete
    sessions (N returns need N + 1 closes); returns (None, None) on
    insufficient history or a non-finite/non-positive close rather than
    raising -- a bad bar is a data problem, and gate_vrp_present already
    rejects a missing realised_vol.

    Returns (rv, prior_close), where prior_close is the most recent
    complete session's close (for the caller's intraday-move calculation)
    and does not depend on lookback_days.
    """
    now_date = now.astimezone(ET).date()
    complete = []
    for bar in daily_bars:
        ts = spread.parse_quote_ts(bar.get("t"))
        if ts is None or bar.get("c") is None:
            continue
        bar_date = datetime.fromtimestamp(ts, tz=ET).date()
        if bar_date < now_date:
            complete.append((bar_date, bar["c"]))
    complete.sort(key=lambda pair: pair[0])

    if len(complete) < lookback_days + 1:
        return None, None

    try:
        closes = [float(c) for _, c in complete[-(lookback_days + 1):]]
    except (TypeError, ValueError):
        return None, None
    if any(not math.isfinite(c) or c <= 0 for c in closes):
        return None, None

    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)  # N-1
    rv = math.sqrt(variance) * math.sqrt(252)
    return rv, closes[-1]


def compute_intraday_move(spot: float, prior_close: float) -> float:
    return spot / prior_close - 1


# ---------------------------------------------------------------------------
# ATM IV (chain-derived, single expiry)
# ---------------------------------------------------------------------------

def compute_atm_iv(put_contracts: list, spot: float) -> float | None:
    """Same-expiry ATM put IV via linear interpolation between the strikes
    bracketing spot: K1 = greatest strike <= spot, K2 = least strike >=
    spot, among contracts with a valid finite positive IV. Returns None if
    spot isn't bracketed. The caller passes in only ONE expiry's worth of
    put contracts -- this function does not group by expiry itself."""
    valid = [c for c in put_contracts if c.iv is not None and math.isfinite(c.iv) and c.iv > 0]
    below = [c for c in valid if c.strike <= spot]
    above = [c for c in valid if c.strike >= spot]
    if not below or not above:
        return None

    k1 = max(below, key=lambda c: c.strike)
    k2 = min(above, key=lambda c: c.strike)
    if k2.strike < k1.strike:
        return None
    if k1.strike == k2.strike:
        return k1.iv

    return k1.iv + ((spot - k1.strike) / (k2.strike - k1.strike)) * (k2.iv - k1.iv)


# ---------------------------------------------------------------------------
# Event calendar
# ---------------------------------------------------------------------------

def load_event_blackouts(path: str) -> list:
    """Reads the hand-verified event calendar and expands each event into a
    flat +/-30-minute blackout window. Both tiers get the same flat window
    in this version -- Tier 1's canonical-plan nuance (widen back to the
    prior session close; block ahead of a pending event) is deliberately NOT
    implemented here: this week's one real Tier 1 event (NFP, Fri 4 Sep)
    falls after Thursday's flatten and so never exercises that clause --
    shipping untested logic for a clause that can never run this week is
    worse than clearly deferring it.

    ALWAYS raises MarketDataError on any failure to load, parse, or
    understand the file -- never returns None or an empty list to mean
    "couldn't load". risk.py's gate_event_blackout treats
    state["event_blackouts"] is None as a hard reject and [] as "no
    blackouts active"; those mean opposite things, so the caller (loop.py)
    must catch MarketDataError here and set state["event_blackouts"] = None
    (never []), so a failed load fails the gate closed instead of silently
    admitting every entry with nothing checked.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketDataError(f"could not load event calendar {path}: {exc}") from exc

    try:
        blackouts = [
            {
                "name": ev["name"],
                "start_ts": datetime.fromisoformat(ev["event_ts_et"]).timestamp() - 1800,
                "end_ts": datetime.fromisoformat(ev["event_ts_et"]).timestamp() + 1800,
            }
            for ev in data["events"]
        ]
    except (KeyError, ValueError) as exc:
        raise MarketDataError(f"malformed event calendar {path}: {exc}") from exc

    return blackouts


# ---------------------------------------------------------------------------
# Orchestration -- one call per tick, one call per underlying
# ---------------------------------------------------------------------------

def build_regime_state(now: datetime, event_calendar_path: str, vix_url_template: str) -> dict:
    """Fetched ONCE per tick and shared across SPY and QQQ -- both must
    evaluate against the same VIX/calendar read, not each fetch its own."""
    vix_family = fetch_vix_family(now, vix_url_template)
    blackouts = load_event_blackouts(event_calendar_path)
    return {
        "vix": vix_family["vix"],
        "vix9d": vix_family["vix9d"],
        "vix3m": vix_family["vix3m"],
        "vix_as_of": vix_family["as_of"],
        "event_blackouts": blackouts,
    }


def build_underlying_state(
    underlying: str, now: datetime, dte_min: int, dte_max: int, profile: str = "submission",
    rv_lookback_days: int = 20,
) -> dict:
    """Orchestrates one underlying's full state read: spot (latest quote
    midpoint), trailing RV over rv_lookback_days (governance
    vrp.realised_vol_lookback_days) + prior close (45 calendar days of daily
    bars), intraday move, and every put contract across the whole DTE window
    in a single chain call. Does NOT compute ATM IV -- the caller calls compute_atm_iv
    once it knows which expiry-group of `contracts` its chosen candidate
    belongs to."""
    quote = (alpaca.latest_quote(underlying, profile=profile).get("quote")) or {}
    bid, ask = quote.get("bp"), quote.get("ap")
    if not bid or not ask:
        raise MarketDataError(f"{underlying}: latest quote missing bid/ask ({bid}/{ask})")
    spot = (bid + ask) / 2
    spot_ts = spread.parse_quote_ts(quote.get("t"))

    # ponytail: 45 calendar days is ~31 complete sessions -- enough for any
    # lookback <= 30. Widen the fetch before raising the governance number past that.
    start = (now.astimezone(ET) - timedelta(days=45)).date().isoformat()
    daily_bars = alpaca.stock_bars(underlying, start=start, limit=45, profile=profile).get("bars", [])
    rv, prior_close = compute_realised_vol(daily_bars, now, lookback_days=rv_lookback_days)
    if rv is None:
        raise MarketDataError(
            f"{underlying}: fewer than {rv_lookback_days + 1} complete daily sessions for RV{rv_lookback_days}"
        )

    now_date = now.astimezone(ET).date()
    low = (now_date + timedelta(days=dte_min)).isoformat()
    high = (now_date + timedelta(days=dte_max)).isoformat()
    # Puts only: band strikes sit 1-4 % below spot and the long leg $5
    # further; compute_atm_iv needs one strike >= spot; 10 % below covers a
    # 2 % shock plus width. Windowed so the whole DTE range stays one page.
    chain = alpaca.option_chain(
        underlying, option_type="put",
        expiration_date_gte=low, expiration_date_lte=high,
        strike_gte=round(spot * 0.90, 2), strike_lte=round(spot * 1.02, 2),
        profile=profile,
    )
    contracts = spread.parse_chain(chain.get("snapshots", {}))

    return {
        "spot": spot,
        "spot_ts": spot_ts,
        "realised_vol": rv,
        # The window travels WITH the value (PR #22's point): the old key
        # was named realised_vol_20d and kept that name when governance
        # moved to 10 days, so the proposer wrote "20-day" theses over a
        # 10-day number. A name cannot track a config value; a field can.
        "realised_vol_lookback_days": rv_lookback_days,
        "prior_close": prior_close,
        "intraday_move_pct": compute_intraday_move(spot, prior_close),
        "contracts": contracts,
    }
