# Handoff — Theta Gate

**One-shot pickup document — read it, act on it, then it is done.** Do not
update this file as the day goes on. Put running state in `docs/STATUS.md`,
and put the team-facing snapshot in `docs/TEAM-BRIEF.md`.

**Written Tue 1 Sep 2026, 15:20 ET (22:20 Riyadh).** Written because the
session that held the Wednesday watcher is closing.
**Submission closes Fri 4 Sep, 11:00 ET.**

**Verify before you trust this file** — `git log --oneline -5`,
`.venv/bin/python3 -m pytest -q`, `gh pr list`, `git status`,
`cat data/HALT.json`. If the repo disagrees, the repo is right.

---

## Do this first

**Re-arm the Wednesday watcher. The previous one died with its session.**
`Monitor` and `CronCreate` both live in memory only. The script itself is now
in the repo and survives:

```bash
bash scripts/wed_watch.sh          # sleeps until Wed 2 Sep 09:28 ET, then reports
```

Run it in the background from the new session (Monitor, or `run_in_background`).
It refuses to fire late: if the date is already past Wed 2 Sep it prints
`MISSED` and exits.

It reports three things:

1. **09:28 ET** — one line to confirm it woke.
2. **~09:36 ET** — the credit-quality reading on the live 3–5 DTE band for
   SPY and QQQ, with each gate verdict. This is ~55 minutes of warning before
   the window.
3. **09:36 → 10:52 ET** — proposals, vetoes, fills, any `exit_evaluated` with
   a signal other than `hold`, HALT, assignment, orphans, submit failures.

**Why from the open and not from 10:30:** an exit can fire on any tick, and a
stop-out on either leg frees a slot that changes what 10:30 can do.

---

## The book, right now

| Position | Structure | Qty | Credit | Cost to close | Unrealised | Stop |
|---|---|---|---|---|---|---|
| `tg-e-20260831-1030-spy` | SPY 754/749P, exp 9 Sep | 1 | 0.61 | 0.95 | **−$34** | 1.22 |
| `tg-e-20260901-1030-qqq` | QQQ 699/694P, exp 4 Sep | 2 | 0.59 | 0.90 | **−$62** | 1.18 |

**Total unrealised −$96** on a $100,000 account (−0.10%). Both read `hold` at
the 14:58 ET tick. `HALT.json` inactive, no orphans, every tick green.

**Watch QQQ.** It touched 1.11 at 14:46 ET against a 1.18 stop — inside 7
cents of a stop-out. It has since eased to 0.90. **QQQ expires Fri 4 Sep, so
it has 3 DTE and the least time to recover.** SPY expires 9 Sep and never got
closer than 1.08 against 1.22.

The −1% daily drawdown halt is about $900 away. That halt blocks new entries
only. It never closes a position.

Book is at capacity — 2 concurrent, 1 per underlying — so **no entry was
possible Tuesday afternoon and none is possible until a slot frees.**

---

## Repo state

`main` at `7ad6ac9` · **0 open PRs** · **309 tests passing** · working tree
clean · repo still PRIVATE, flips public Thu 3 Sep 17:00 ET (automated,
`.github/workflows/go-public.yml`, write path verified).

---

## The one live risk at Wednesday's window

**`gate_credit_quality` may veto the proposal, and that is the gate working,
not a fault.** At $5 wide the headroom is about 8 points against its 40%
deviation limit (it was ~26 at $2 wide). If it vetoes, the hackathon ends with
two trades instead of three. Do not touch `governance.json` to force a third
trade — the settings are closed decisions, listed in `docs/TEAM-BRIEF.md`.

---

## Then, in order

| When | What |
|---|---|
| Wed 2 Sep 10:45 ET | Entries close permanently. Nothing more to enter. |
| Thu 3 Sep 14:30 ET | Force-close ladder runs. Book must end flat. Watch all four rungs: 14:30 mid → 15:00 cross → 15:30 `market_mleg` capped at width−0.01 → 15:45 reconcile and alert. |
| Thu 3 Sep, after flat | **One sitting, one source:** fill `deck/theta-gate.tex:422-425` (4 `\PLACEHOLDER` stats), the Results placeholders in `submission/WRITEUP.md`, and the bracketed numbers in `social/drafts/06-results-and-flat.md`. |
| Thu 3 Sep 17:00 ET | Repo flips public (automated). |
| Fri 4 Sep 11:00 ET | Submission closes. |

---

## Still outstanding, not done

- **Video not recorded.** Shot list and spoken script are at
  `submission/VIDEO-SCRIPT.md`. Shots 1–7 are recordable now; shot 8 needs
  Thursday's flat book. The script carries a do-not-film list (`.env`, a
  filled-in `env.example`, `alpaca doctor` output, GitHub secrets pages).
  The archived rules contain **no duration rule** — 3:00 is our own target.
- **Deck is stale on at least two counts** and needs a correction pass before
  Thursday. `7ad6ac9` fixed three claims; more remain.
- **Demo URL** — no deploy config exists. Floor is a screen recording;
  Streamlit deploy after Thursday's public flip if there is time.
- **Social — 0 of 5 eligible.** Post 01 went out 27 Aug, one day before the
  28 Aug 11:00 ET kick-off, so it is outside the window and must not be
  submitted. Five drafts sit in `social/drafts/02-06`. **PK posts. The agent
  never posts.**
- **`ENTRY_CONCESSION_FLOOR_DOLLARS`** (`loop.py:71`) is an absolute $0.50, so
  `width_dollars` is not really one governance value. **Fix after the
  deadline, not before.**

---

## Binding decisions — do not reopen

- **Width stays $5.** Closed on 208 quote observations and five agent reviews.
  See `docs/TEAM-BRIEF.md` for the two findings that decide it.
- **Tenor is 3–5 DTE**, `time_exit_dte` 1. Credit is tenor-invariant at fixed
  delta, so the shorter tenor is free decay capture.
- **Rejected: aggressive sizing** (33 contracts, −6% halt) and
  **confidence-based sizing** (the model returns a near-constant 0.60–0.62).
- **VRP option C** — `realised_vol_lookback_days` 10, `min_vrp_points` 1.0.
- **Never trade the submission account by hand.** Its history is the judges'
  evidence of autonomy.
- **Public flip Thu 3 Sep 17:00 ET**, one day before the deadline.

---

## Gotchas — do not re-derive

- **`Monitor` and `CronCreate` are session-only.** Nothing is written to disk;
  both die when the session ends. This is why the watcher script now lives in
  `scripts/`.
- **A peer Claude session may share this worktree.** Never `git stash` — you
  will take their uncommitted work. Commit only your own paths by name.
- **`plan.credit` is `short.mid − long.mid`** — a MID credit, never a fill.
  Tuesday's real slippage was **6.35%**, not 2.5%.
- **`alpaca doctor --profile X` silently ignores the flag.** Everything else
  routes through the `ALPACA_PROFILE` env var.
- **`ALPACA_ACCOUNT_ID` is the UUID, not the account number.**
- **A duplicate `client_order_id` returns HTTP 422, never a second order.**
  That is the whole idempotency mechanism.
- **`.mcp.json` must keep `fastmcp==3.2.0` pinned.** A fresh `uvx` resolve of
  `alpaca-mcp-server==2.3.0` dies without it.
- **GitHub secrets and variables are separate namespaces** — `secrets.X`
  resolves to empty in silence when X is a variable.
- **The `Read` tool's injection scanner flags `brain.py`.** False positive —
  it matches that file's own `_INJECTION_MARKERS` defence list.
- **A Streamlit Cloud public app still 303s to auth for cookie-less curl.**
  That is not a login wall.

---

## Deep reference

| File | What |
|---|---|
| `docs/TEAM-BRIEF.md` | Team-facing snapshot — config, closed decisions, timeline. Regenerated, never appended. |
| `docs/STATUS.md` | Rolling history and the reasoning behind every decision. |
| `docs/STRATEGY-REVIEW-2026-09-01.md` | Why the agent filters but does not select. |
| `docs/ANALYSIS-2026-08-30.md` | Sunday's full audit, every finding with severity. |
| `governance.json` | Every threshold. No LLM can write to it. |

## Operating notes

```bash
set -a; source .env; set +a
.venv/bin/python3 loop.py --once --dry-run --profile submission   # local tick, no broker writes
PYTHONPATH=. .venv/bin/python3 scripts/live_gate_check.py         # read-only gate diagnostic
PYTHONPATH=. .venv/bin/python3 scripts/measure_credit_curve.py    # read-only credit curve
ALPACA_PROFILE=submission alpaca order get --order-id <id>        # raw broker order
```

Use `.venv/bin/python3`, never system `python3`. Kill switch:
`data/HALT.json` → `active: true`.

Repo: `github.com/Kalwaleed/theta-gate` (private, 6 collaborators).
