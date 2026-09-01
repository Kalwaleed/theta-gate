# Handoff — Theta Gate

**One-shot pickup document — read it, act on it, then it's done.** Do not
update this file again as the day progresses; log ongoing state in
`docs/STATUS.md` instead (`docs/HANDOFF.md` and `docs/STATUS.md` are
deliberately separate files — see the STATUS.md preamble for why).

**Written Mon 31 Aug 2026, ~14:55 ET (21:55 Riyadh).** First live trading
day, in progress. Deadline: **submission Fri 4 Sep, 11:00 ET.**

**Verify before trusting this file** — `git log --oneline -8`,
`.venv/bin/python3 -m pytest -q`, `gh pr list`,
`gh run list --workflow="Theta Gate Agent" --limit 5`, `git status`. If it
disagrees with the repo, the repo is right.

---

## Do this first

**Close the loop on PRs #21 and #22 — they're superseded, not done.**
While this file was being written, a peer session (`verify-fix-audit-findings`,
committing under PK's own git identity) landed `f7b74b9` directly to
`main`: "fix: rename realised_vol_20d and give the brain position
awareness" — 245/245 tests pass. That commit fixes the same substance as
PR #21 (position-aware `brain_context`) and PR #22 (the stale
`realised_vol_20d` name) in one go. **Both PRs are still showing OPEN in
`gh pr list`** — check whether `f7b74b9` fully supersedes them and close
them with a pointer to that commit, rather than reviewing them as if the
work is still pending. Verify this yourself (`git show --stat f7b74b9` vs.
each PR's diff) before closing anything.

**PR #23 (decision log hides 18 of 30 event types, 9 operator-critical) is
still genuinely open and unaddressed** — that one needs real review.

---

## Right now, this exact moment

- **Position open since 10:30 ET:** `tg-e-20260831-1030-spy` — SPY bull put
  credit spread, short 754P / long 749P, $5 wide, qty 1, exp 9 Sep, credit
  $0.61 (order `7fe33b90`, verified against the broker directly, not just
  the journal). Still `hold` as of the 14:52 ET tick, cost-to-close ~0.57
  (small unrealized gain). No naked leg, `HALT.active: false` throughout.
- **13:30 ET window: no new entry, correctly gated** — both the 13:38 and
  13:45 ET ticks proposed SPY again and were blocked by
  `"concurrent: already at max positions for SPY"` (one position per
  underlying). That part is genuinely correct, deterministic risk-gate
  behavior.
- **QQQ was never offered as an alternative this afternoon — that was a
  real gap, not "by design" as I told PK earlier this session, and it's
  now fixed (unverified live).** Mechanically the model proposes exactly
  one underlying per call, which *is* by design. What wasn't by design:
  `brain_context` had no position state, so the model couldn't know SPY
  was full and route to QQQ instead. Fixed in `f7b74b9`
  (`_available_underlyings` pre-filters through the same risk gates
  before the model call; skips the call entirely if nothing's available).
  **Not yet exercised live** — no more entry windows today (10:30 and
  13:30 already passed), so the first real test is tomorrow's 10:30 or
  13:30 ET tick if the SPY position is still open then. Watch for it.
- **The price-sign convention (`filled_avg_price` mirrors `limit_price`'s
  negative-is-credit rule) is now verified live** against the real
  10:33 ET fill. `loop.py`'s `_extract_actual_price` docstring updated
  (commit `a3b1447`) — no longer an open question.
- **Next watch point: 16:00 ET (23:00 Riyadh) close**, ~1h05m from
  writing. No exit signal has fired on the open SPY spread yet.

---

## Three PRs from msuiche, opened within minutes of each other — status as of writing

- **#21 — "Only offer the proposer underlyings it can actually trade"**
  (`feat/available-underlyings`) — **superseded by `f7b74b9`** on `main`
  (see "Do this first" above). Confirm and close, don't re-review as
  pending.
- **#22 — "The realised-vol field lied about its own window"**
  (`fix/realised-vol-field-name`) — **also superseded by `f7b74b9`.**
  Real finding while it was open, worth knowing: **today's live,
  committed, judge-facing journal entries from the 10:33 and 13:38/13:45
  ET proposals literally say "SPY 20-day realised vol" when the
  governance setting has computed a 10-day number since 30 Aug's VRP
  option-C decision.** That mislabeled text is already in
  `data/journal.jsonl` on `main` and can't be retroactively fixed —
  worth a line in the write-up if judges read the raw journal.
- **#23 — "The decision log was an allowlist, and it had rotted"**
  (`fix/decision-log-denylist`) — **still genuinely open, unaddressed.**
  `loop.py` emits 30 journal event types; `store.decision_log` only
  surfaces 12 to the dashboard, silently hiding 18 — 9 of which are
  operator-critical: `assignment_detected`, `untracked_broker_position`,
  `submit_failed`, `journal_publish_failed`, `exit_fill_leg_mismatch`,
  `force_close_unresolved` (Thursday's mandatory flatten failing), and
  others. +100/-7, touches `store.py`, `test_store.py`. This one needs
  real review — a HALT-worthy event silently not reaching the dashboard
  is exactly the kind of thing that matters if something breaks between
  now and Friday.

---

## Deliverables already handled this session

- **Deck fixes applied directly to `main`** (commit `f823296`, PR #11 had
  merged Sunday without them): `BoldFont=* SemiBold` → `SmBld` (was a hard
  build failure, verified before/after), and 18→21 gates in three spots
  (matches `risk.py`'s own docstring). `make check` still shows 8
  pre-existing content-overflow warnings — unrelated, pre-existing,
  design's call per PK, not fixed.
- **`docs/HANDOFF.md` → `docs/STATUS.md` rename** (commit `756d56d`) — see
  that file's preamble for why; this file (a fresh HANDOFF.md) exists
  because PK asked for a genuine new one-shot handoff, not a revival of
  the old rolling-update pattern.

## Still outstanding, not done

- **ecc-tools spam-PR app access — needs PK directly, not scriptable.**
  Source confirmed as the `ecc-tools` GitHub App (not a repo collaborator).
  A personal-account PAT can't revoke GitHub App access via API (tried,
  401/403 on every path) and this is a personal account, not an org, so
  there's no admin-API route either. Manual step:
  **github.com/settings/installations → ecc-tools → Configure → remove
  `theta-gate`.**
- **16:00 ET close, and every entry/exit window through Friday** — nobody
  has watched past ~14:55 ET today.

---

## Decisions PK has taken (unchanged, still binding)

- **VRP option C** — `realised_vol_lookback_days` 10, `min_vrp_points`
  1.0 (30 Aug). This is exactly the setting whose rename PR #22 fixes.
- **Design is the team's** — fonts, palette, layout, deck structure.
  Correctness bugs (build failures, wrong counts, mislabeled data) are
  worth fixing/flagging regardless.
- **Public flip: Thursday 3 Sep, 17:00 ET** (00:00 Riyadh, effectively
  Friday), one day before the actual Fri 4 Sep 11:00 ET deadline.
  Automated via `.github/workflows/go-public.yml`, write-permission
  verified.
- **Never trade the submission account by hand** — its history is judges'
  evidence of autonomy.

---

## Gotchas — do not re-derive

- **`alpaca doctor --profile X` silently ignores the flag.** Every other
  call routes through `ALPACA_PROFILE` env var.
- **`ALPACA_ACCOUNT_ID` is the UUID, not the account number.**
- **GitHub secrets and variables are separate namespaces** —
  `secrets.X` resolves to empty silently when X is actually a variable.
- **A fine-grained PAT's `Administration` scope doesn't cover
  `gh pr list`** — needs a separate `Pull requests` read permission.
- **A green dry run only proves what it actually calls** — go-public.yml's
  first version tested read access, never the write path that mattered.
- **A duplicate `client_order_id` returns HTTP 422, never a second
  order** — the entire idempotency mechanism.
- **`brain.py`'s validation is not HTML-aware** — `app.py`'s `esc()` is the
  only thing preventing script injection in a judge's browser.
- The `Read` tool's injection scanner will flag `brain.py` — false
  positive, it's matching the file's own `_INJECTION_MARKERS` defense
  list (lines ~54-66), not an actual injection.

---

## Deep reference

`docs/ANALYSIS-2026-08-30.md` — 157-agent audit from Sunday, every finding
with severity. `docs/STATUS.md` — rolling log of today's live-trading
events (10:30 fill detail, journal excerpts). Both predate the three new
PRs above.

## Operating notes

```bash
set -a; source .env; set +a
.venv/bin/python3 loop.py --once --dry-run --profile submission   # local tick, no broker writes
PYTHONPATH=. .venv/bin/python3 scripts/live_gate_check.py         # read-only gate diagnostic
gh workflow run "Theta Gate Agent" --repo Kalwaleed/theta-gate -f dry_run=true
ALPACA_PROFILE=submission alpaca order get --order-id <id>        # raw broker order, bypasses journal
```

Use `.venv/bin/python3`, never system `python3`. Kill switch:
`data/HALT.json` → `active: true`.

Repo: `github.com/Kalwaleed/theta-gate` (private, 6 collaborators).

---

## Demo URL — one setting still needs changing

**https://theta-gate-km6zecgl3nxqiqnh7fpdqg.streamlit.app/**

Deployed and rendering, but **currently behind a login wall**. Verified 1 Sep:

```
GET /      -> 303
location:  https://share.streamlit.io/-/auth/app?redirect_uri=...
then       -> /-/login?payload=...
```

A judge opening it sees a Streamlit sign-in page, not the dashboard. The
hackathon requires a working Application URL, so as it stands the entry
effectively has no demo.

**Cause:** the app was deployed from a private repo, so Streamlit Cloud
defaulted the *app* to private. **App visibility is a separate setting from
repo visibility — Thursday's automated repo flip will not fix this.**

**Fix (PK, ~30 seconds):** share.streamlit.io → the app → **Settings → Sharing**
→ set to **"This app is public and searchable"** (or *anyone with the link*).
Then confirm in a private browser window that it loads without signing in.

Do this before Friday, and re-check it after Thursday's repo flip in case the
visibility change resets.
