# lablab.ai submission — every field, ready to paste

Verified against the repo and the live journal on **3 Sep 2026**. I cannot submit
this form; paste it yourself. Deadline **Fri 4 Sep 11:00 ET / 18:00 Riyadh**.

---

## 📋 Basic information

### Project title
```
Theta Gate
```

### Short description
```
An autonomous options agent that cannot place a trade it should not. The LLM
proposes a direction and nothing else; 21 deterministic Python gates hold the
final say, and every refusal is logged with its reason.
```

### Long description
```
Theta Gate sells defined-risk vertical put spreads on SPY and QQQ from a fresh
$100,000 Alpaca paper account. Every order in its history was placed by the
agent. No human placed or closed a trade all week.

THE PROBLEM

Alpaca's paper-trading skills require human confirmation before every order, and
five operations demand it even unattended. That breaks the autonomous brief: a
cron job at 10:30 on a Tuesday has no one to ask. A confirmation is really two
things — seeing what is about to happen, and deciding whether it is allowed.
Theta Gate keeps the second part and replaces the human with 21 assertions.

THE ARCHITECTURE

One bounded model call per entry window. Claude Opus 5 runs with tools=[],
mcp_servers={}, strict_mcp_config=True and max_turns=1. It sees only scalar
market numbers already computed for the gates, and returns five fields:
underlying, direction, confidence, thesis, invalidation. It cannot pick a
strike, a size, a price, or a threshold, and it holds no broker credential. A
prompt injection returns no proposal, never a crash — the breach is unreachable,
not merely forbidden, and a test asserts it.

Everything downstream is deterministic Python. Strike selection, sizing, the
credit floor, the variance-risk-premium check, position caps, drawdown halts —
all of it is arithmetic in risk.py with governance.json as the single source of
every number, a file no LLM can write to.

THE ONE EDGE IT CLAIMS

Before writing strategy code I priced real spreads on the live chain. Swept from
0.15 to 0.45 delta across five widths, expected value is negative every time, by
almost exactly the bid-ask cost. Delta is the risk-neutral probability, so a
fairly priced chain cannot yield edge by arithmetic alone. So the agent claims
exactly one edge, names it — the variance risk premium — and refuses to trade
when it is absent. It vetoed four candidates on that gate alone.

RESULTS, AND WHAT THEY DO NOT SHOW

Six sessions. 582 journal events and 178 ticks by Thursday's close, 9 model
proposals, 2 fills.
Realised P&L +$95, 2 for 2, max drawdown -0.15% measured peak mark-to-market —
not the realised-only 0.0% that would have flattered it. Both positions closed
themselves on the take-profit rule at 09:37 ET on the final day, five hours
before the mandatory flatten.

Two trades prove nothing about edge, and the deck says so on its own slide. What
six sessions do show is whether the machinery holds: whether every refusal was
logged with a reason, whether the kill switch stayed reachable, whether a
multi-leg order ever left a naked leg. Those are answerable at this sample size.

Being precise about one thing, because the journal is public and anyone can
check it: the four-rung force-close ladder built for the final afternoon never
executed live. It is tested and was rehearsed against all four rungs with a
simulated clock, but take-profit got there first. A code path that has not run
is not described here as if it had.

VERIFICATION

344 tests in CI on every push. A hash-chained, append-only JSONL journal replayed
into SQLite. A second scheduled job reconciles the broker's own view against that
journal over Alpaca's MCP server, with two read tools allowed and every write
tool denied by name — the thing that verifies the books is not the thing that
writes them.
```

### Technology & category tags
```
Claude, Anthropic, Alpaca Trading API, Alpaca MCP Server, Alpaca CLI, Python,
Streamlit, GitHub Actions, SQLite, Options Trading, Algorithmic Trading,
Autonomous Agents, Risk Management, Fintech
```

---

## 📸 Cover image and presentation

| Field | Value |
|---|---|
| Cover image | `cover/cover.png` (in repo) |
| Video presentation | Produced outside this repo |
| Slide presentation | `deck/theta-gate.pdf` — 13 pages |

---

## 💻 App hosting and repository

| Field | Value |
|---|---|
| Public GitHub repository | `https://github.com/Kalwaleed/theta-gate` |
| Demo application platform | Streamlit Community Cloud |
| Application URL | `https://theta-gate-km6zecgl3nxqiqnh7fpdqg.streamlit.app/` |
| **Alpaca paper trading account ID** | `7a013821-9249-4505-8025-fb298f0931a5` |

---

## 🔗 Social engagement — submit these 5

Post 01 is **excluded on purpose**: it published 27 Aug 03:37 ET, 31 hours before
the 28 Aug 11:00 ET kick-off, so it cannot score and would waste a slot.

| # | Posted (ET) | URL |
|---|---|---|
| 1 | 2 Sep 03:18 | `https://x.com/KhaledAlwaleed/status/2095048707511394537` |
| 2 | 3 Sep 03:05 | `https://x.com/KhaledAlwaleed/status/2095407737564004463` |
| 3 | 3 Sep 08:45 | `https://x.com/KhaledAlwaleed/status/2095493420655763551` |
| 4 | 3 Sep 14:07 | `https://x.com/KhaledAlwaleed/status/2095574400942915688` |
| 5 | — | **post `social/drafts/06-results-and-flat.md`, then paste its URL here** |

---

## Before you hit submit

- [ ] Video recorded and uploaded
- [ ] Post 06 published, URL pasted above
- [ ] Repo is public — confirmed, since 31 Aug
- [ ] Dashboard loads in a logged-out browser window
- [ ] Account ID matches the one the agent actually traded
