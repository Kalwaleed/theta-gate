# Handoff — Theta Gate

**One-shot pickup document. Read it, act on it, then it is done.** Do not
update this file as the day moves. Put rolling state in `docs/STATUS.md`.
Put team-facing state in `docs/TEAM-BRIEF.md`.

**Written Tue 1 Sep 2026, 14:25 ET (21:25 Riyadh).** Deadline: **submission
Fri 4 Sep, 11:00 ET.**

**Verify before you trust this file** — `git log --oneline -5`,
`.venv/bin/python3 -m pytest -q`, `gh pr list`, `git status`. If the repo
disagrees with this file, the repo is right.

---

## Do this first — arm the Wednesday watcher

The previous session armed a Monitor for the Wednesday open. **That Monitor
died with the session.** Nothing is armed now. Re-arm it:

```bash
nohup scripts/wed_watch.sh > /tmp/wed_watch.log 2>&1 &
```

Or run it in a background Bash tool call. The script is safe to start at any
time: it sleeps until Wed 2 Sep 09:28 ET, and it exits with `MISSED` instead
of firing late if the date has already passed.

**Why 09:30 and not 10:30** — three reasons, all still true:

1. The credit-gate veto is predictable at 09:36, and there is no second
   window if it vetoes.
2. An exit can fire on any tick. A stop-out frees a position slot and changes
   what the 10:30 window can do.
3. The first tick of the day is the overnight integrity check — assignment,
   untracked broker position, orphan leg.

**What the script prints** — the market-open line at 09:28, the live
credit-quality reading at 09:36 for both underlyings with each gate verdict,
then every proposal, veto, fill, non-`hold` exit signal, HALT and fault event
until 10:52 ET.

---

## State right now

| Item | Value |
|---|---|
| Branch | `main` at `f8a641f` |
| Tests | **317 pass** |
| HALT | inactive |
| Open PRs | **#32** (peer session, dashboard URL + sharing) |
| Positions | **2 of 2 — at capacity** |

**Book, both underwater, both `hold`:**

| Position | Legs | Qty | Credit | Cost to close | DTE |
|---|---|---|---|---|---|
| `tg-e-20260831-1030-spy` | 754P / 749P | 1 | 0.61 | 0.84 | 8 |
| `tg-e-20260901-1030-qqq` | 699P / 694P | 2 | 0.59 | 0.73 | 3 |

Neither is near its stop (1.22 SPY, 1.18 QQQ). Both sit at capacity, so
**Wednesday's 10:30 window can only enter if one of these exits first.**

---

## Decisions already closed — do not re-open

| Decision | Value | Ground |
|---|---|---|
| Spread width | **$5** | Dollar bid-ask is flat across widths while credit scales with width; the entry ladder inverts below ~$4.6 because of `ENTRY_CONCESSION_FLOOR_DOLLARS` |
| Tenor | **3–5 DTE**, `time_exit_dte: 1` | Merged from PR #27's tenor half |
| Sizing | **qty 2 fixed** | PR #27's confidence-sizing half rejected; PR #26 closed |
| VRP gate | lookback 10 days, `min_vrp_points` 1.0 | 30 Aug option C |
| Public flip | **Thu 3 Sep 17:00 ET** | Automated, `go-public.yml`, write path verified |
| Manual trading | **never** | The account history is the judges' evidence of autonomy |

**Credit is tenor-invariant at fixed delta.** $0.61 at both 6–9 DTE and 3–5
DTE, measured live. Do not re-derive this from √T — that reasoning applies to
a fixed strike, not to a delta-matched vertical.

**`plan.credit` is a mid, not a fill.** Measured friction is **6.35%**, not
2.5%. Any gross ratio quoted without `friction_ratio` applied is optimistic.

---

## Still outstanding

- **Thu 3 Sep, after the 14:30 force-close** — fill four `\PLACEHOLDER`
  stats in `deck/theta-gate.tex:422-425`, the Results placeholders in
  `submission/WRITEUP.md`, and the bracketed numbers in
  `social/drafts/06-results-and-flat.md`. Do all of them in one sitting.
- **Video not recorded.** Shots 1–7 are recordable now. Shot 8 needs the flat
  book. Script and do-not-film list: `submission/VIDEO-SCRIPT.md`.
- **Deck is stale on at least two counts** — needs a correction pass before
  Thursday.
- **Social: 0 of 5 drafts posted.** Drafts are in `social/drafts/`. **PK
  posts, the agent never posts.**
- **`ENTRY_CONCESSION_FLOOR_DOLLARS` width coupling** — fix after the
  deadline, not before.

---

## Gotchas — do not re-derive

- **A peer Claude session shares this worktree.** Never `git stash`. Commit
  only your own staged paths. `git pull --rebase` fails when their
  uncommitted work is present.
- **`alpaca doctor --profile X` silently ignores the flag.** Everything else
  routes through the `ALPACA_PROFILE` env var.
- **`ALPACA_ACCOUNT_ID` is the UUID**, not the account number.
- **A duplicate `client_order_id` returns HTTP 422, never a second order.**
  This is the whole idempotency mechanism.
- **GitHub secrets and variables are separate namespaces.** `secrets.X`
  resolves to empty, silently, when X is a variable.
- **`.mcp.json` needs `fastmcp==3.2.0` pinned.** A fresh `uvx` resolve
  breaks `alpaca-mcp-server` 2.3.0.
- **The Read tool flags `brain.py` as injection.** False positive — it
  matches that file's own defence list at lines ~54-66.
- Use `.venv/bin/python3`, never system `python3`.

---

## Deep reference

| File | What |
|---|---|
| `docs/TEAM-BRIEF.md` | The distributable snapshot — regenerate it, never append |
| `docs/STATUS.md` | Rolling log of live-trading events |
| `docs/ANALYSIS-2026-08-30.md` | The 157-agent Sunday audit, every finding with severity |
| `submission/WRITEUP.md` | PK's own prose, 941 words. Do not rewrite it |
| `submission/VIDEO-SCRIPT.md` | 8 shots, 3:00 target, do-not-film list |

## Operating notes

```bash
set -a; source .env; set +a
.venv/bin/python3 loop.py --once --dry-run --profile submission  # local tick, no broker writes
PYTHONPATH=. .venv/bin/python3 scripts/live_gate_check.py        # read-only gate diagnostic
PYTHONPATH=. .venv/bin/python3 scripts/measure_credit_curve.py   # read-only credit curve
ALPACA_PROFILE=submission alpaca order get --order-id <id>       # raw broker order
```

Kill switch: `data/HALT.json` → `active: true`.
Repo: `github.com/Kalwaleed/theta-gate` (private until Thu 3 Sep 17:00 ET).

---

## Demo URL

**https://theta-gate-km6zecgl3nxqiqnh7fpdqg.streamlit.app/**

Public, anonymous, and rendering. Verified 1 Sep in a headless browser with no
Streamlit account: the dashboard loads, no sign-in.

**Do not verify this with plain `curl -L`.** Streamlit Cloud answers the first
anonymous request to *any* app -- public ones included -- with
`303 -> share.streamlit.io/-/auth/app`, which sets a session cookie and bounces
back. A client that keeps no cookies follows that into `/-/login?payload=...`
and reads as a login wall. `curl -sL -c jar -b jar <url>` returns 200; a browser
renders the page. This produced one false submission-blocking report already.

Sharing is set to *"This app is public and searchable"*. Worth one browser check
after Thursday's repo flip, in case the visibility setting resets with it.
