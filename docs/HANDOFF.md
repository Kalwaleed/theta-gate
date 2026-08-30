# Handoff — Theta Gate

**Written Sun 30 Aug 2026, ~08:00 ET.** Rewritten from scratch — the previous version had been patched in layers and its top line contradicted its body. Deadline: **submission Fri 4 Sep, 11:00 ET.** First live trading: **Mon 31 Aug, 09:30 ET.**

**Verify before trusting this file** — `git log --oneline -5`, `pytest -q`, `gh pr list`. If it disagrees with the repo, the repo is right. No commit hash is quoted here as "current"; they go stale immediately, the agent's own `journal:` commits included.

Deep reference: **`docs/ANALYSIS-2026-08-30.md`** — the 157-agent audit, every finding with severity, the day-by-day plan, and two designs (X1 sizing, X2 MCP reconciliation). This file is only the resume point.

---

## State

`main` is green: **155 tests**, and CI now runs `pytest` on every push and PR. Repo is **PRIVATE**. The submission paper account is ACTIVE, $100,000, **zero orders ever placed** — its history is the judges' evidence of autonomy, so never trade it by hand.

| Component | State |
|---|---|
| `alpaca.py`, `spread.py`, `risk.py`, `market.py`, `brain.py`, `loop.py` | Built, tested, materially fixed 30 Aug |
| `store.py`, `app.py` | Built; dashboard is read-only and reads no credentials |
| `.github/workflows/agent.yml` + `ci.yml` | Cron every 5 min, weekdays 09:30–16:00 ET; CI on push/PR |
| `governance.json` | VRP tenor-matched (below) |
| `LICENSE`, `NOTICE` | MIT + Apache-2.0 for the vendored Alpaca skills |
| Deck (#11), cover (#12) | Open PRs, **not merged** — held for Thursday's real numbers |
| Demo URL, video, write-up | **Not done.** The hosted demo URL is a hard submission gate |

---

## What 30 Aug changed, and why it mattered

**Two independent bugs each meant zero trades all week.** Both are fixed. Both were mine.

1. **`alpaca._run` read stdout only.** CLI 0.0.13 writes API error bodies to **stderr**, so every submit path died at the first `client_order_id` lookup. It now parses stderr, raises `AlpacaCLIError`, and reads a 404 as a lookup miss rather than a crash.
2. **The option chain was capped at 100 contracts.** The 0.16–0.25 delta band sits nearer the money than that cap reached, so no candidate could ever qualify — a truncation artifact I had previously misread as "quiet market, correctly no trade." Now `--limit 1000` + `next_page_token` pagination + a strike window of `spot × 0.90…1.02` at entry (legs ±0.50 at exit).

Also landed: dead orders are no longer adopted (`TERMINAL_UNFILLED_STATUSES`; the id walks `s0 → s0r2 … r6`); force-close rung tags carry the date, closing a Friday collision that reused Thursday's id; the journal publishes on **every** tick path including exceptions and `not_paper_abort`; a live sibling order is cancelled before a ladder submits beside it; and `loop.py` refuses a live tick outside GitHub Actions without `--local-live`.

**VRP decision (option C), committed.** `realised_vol_lookback_days` 20 → 10 and `min_vrp_points` 2.0 → 1.0, so the realised-vol window matches the 6–9 DTE tenor being sold. On Friday's marks SPY passes both expiries (+2.1 / +2.3 pts) and QQQ only the 9-DTE (+1.3); Monday's open moves all four numbers. It was chosen with Friday's data in view — **say that in the write-up.** Without it the gate vetoed everything and the first plausible entry was Wednesday.

---

## Monday

**Pre-market.** Dispatch `gate_check=true` around 09:45 ET and read the gate tally.

**Then watch two things.** The **09:30 tick is the first scheduled run in this repo's history** — every green run so far has been `workflow_dispatch`, and the cron itself is still unproven. Then the **10:30 entry window**.

**Watch the first fill closely.** `_extract_actual_price` assumes `filled_avg_price` mirrors `limit_price`'s negative-is-credit convention. The analysis reports this verified, but it has still never been observed on a real fill.

**After close** — the analysis's Monday block: phantom-open reconciliation, `assert_paper` once per poll loop, qty 1→2 with the X1 partial-fill design, `available_underlyings` in the brain context, the stale-order sweep outside windows, the dashboard batch, then X2 (read-only MCP reconciliation).

---

## Open PRs

Only **#11** and **#12** are still open. Both are held for Thursday.

| PR | Call | Why |
|---|---|---|
| **#11** deck | **Hold → Thursday** | Merge once real numbers exist. **Two fixes first:** `SemiBold` → `SmBld` in `theta-gate.tex` (IBM Plex registers that weight as `SmBld`; with the font installed — as it is on PK's Mac — `make` hard-fails and emits no PDF), and the gate count. |
| **#12** cover | **Hold → Thursday** | Same gate-count fix. Otherwise clean: exactly 1920×1080, safe build script, no secrets in the HTML or the PNG bytes. |

**Merged 30 Aug:** #7 (store rebuild race — atomic `os.replace`, mutation-tested) and #9 (dashboard HTML escaping, thesis rows, and a `seq`-join parity fix).

**Closed 30 Aug**, each with the reasoning in the PR thread:

- **#8** cron probe — right idea, expired branch. Its probe windows (Sun 07:20–08:05 UTC) had passed and `* * 0` next recurs 6 Sep, after the deadline. Monday's 09:30 tick proves the same thing for free.
- **#10** ECC bundle — byte-identical repeat of the closed #2. No trading code; five unpinned `npx -y <pkg>@latest` MCP servers plus a remote endpoint, against a repo whose LLM boundary is deliberately sealed. If it returns a third time, revoke the app's repo access.
- **#13** security review — its `.memsearch/` deletion was redundant (`main` did it in `1e980f4`). **The audit was preserved** at `docs/SECURITY-REVIEW-2026-08-30.md`: no credential in any blob of any reachable commit, workflow `permissions: contents: write` only, no fork-triggerable injection surface. Lift that table into the write-up.

**The gate count is wrong in three places.** Deck and cover both claim **18 deterministic gates**; the real number is **21** (18 state-only + 3 sized, and `check_all` runs both lists). Root cause is `risk.py`'s own hedge, *"the eighteen-ish gates"* — fix the docstring too, or it propagates into the next artifact.

---

## Decisions PK has taken

- **VRP option C** — committed.
- **Commit-history disclosure** — `96fd434` (1,049 lines across `alpaca.py`/`risk.py`/`spread.py`/`governance.json`/tests) landed **3h40m before kickoff**, and 60–73% of those files still trace to it. Judges check history. **State it plainly in Thursday's write-up** — it reads far better volunteered than discovered.
- **Sequencing** — merge fixes now; hold deck and cover until Thursday's numbers.
- **Design is the team's** — fonts, palette, layout and deck structure are for the five of you. Correctness (a build that emits no PDF, a wrong gate count) is still worth flagging; taste is not.
- **Public flip** — after `/security-review`, not before. Actions minutes are a non-issue: 152 used of 2,000 in August, and the quota resets 1 Sep, so only Monday bills against August.

---

## Gotchas — do not re-derive

- **`alpaca doctor --profile X` silently ignores the flag.** Every call routes through the `ALPACA_PROFILE` env var (`_profile_env`). Regular commands honour `--profile`; only `doctor` lies.
- **`ALPACA_ACCOUNT_ID` is the UUID, not the account number.** `PA32UO0QXLRO` is the dashboard-facing number; `assert_paper` compares against `id`.
- **GitHub secrets and variables are separate namespaces.** `secrets.X` resolves to empty when X is stored as a variable — silently, on every run.
- **`gh secret list` cannot distinguish an empty secret from a populated one**, and `gh secret set` prints nothing either way. The only proof is a workflow run: populated renders `***` in the log's env dump, empty renders blank. That is how an empty `ANTHROPIC_API_KEY` was caught, after two silent failures.
- **Interactive `gh secret set` does not work from Claude Code's `!` prompt** — stdin isn't a TTY, so it stores empty. Pipe the value and echo its character count first.
- **`.env` lines carry leading whitespace**, so `grep '^KEY='` matches nothing. That produced the empty secret.
- **`--dry-run` gates `submit_mleg` *and* `cancel_order`.** A cancel is a broker write, and an order under dry-run may be a real one adopted from an earlier live tick.
- **A duplicate `client_order_id` returns HTTP 422, never a second order.** That is the entire idempotency mechanism: recompute the *same* id and look it up before submitting.
- **`brain.py`'s validation is not HTML-aware** — word-count caps and a substring blocklist only; `<img src=x onerror=…>` passes both. `app.py`'s `esc()` is the only thing preventing script execution in a judge's browser. Do not remove it as redundant.
- **The billing API moved.** `/settings/billing/actions` returns 410; use `/settings/billing/usage`.

---

## Known-open, deliberately

- **Exchange holidays are not checked** — weekday gate only. None fall in the window, and a holiday tick fails safe on stale quotes.
- **No automated single-leg repair.** A naked leg triggers HALT and a CRITICAL journal entry; a human closes it. `alpaca.py` has no single-leg primitive, and building one untested this week is its own risk.
- **Orphan equity (assignment) is detected, not flattened** — same reason.
- **A failed `git push` still loses that tick's local writes.** Loud now (`ok: false`, non-zero exit, red run) rather than silent, but not recovered.

---

## Operating notes

```bash
# a local tick -- reads and journal writes are real, broker writes held back
set -a; source .env; set +a
.venv/bin/python3 loop.py --once --dry-run --profile submission

# read-only gate diagnostic (costs one real brain.propose call)
PYTHONPATH=. .venv/bin/python3 scripts/live_gate_check.py

# rehearse the workflow on the real runner
gh workflow run "Theta Gate Agent" --repo Kalwaleed/theta-gate -f dry_run=true
```

Use `.venv/bin/python3`, never system `python3`. A live local tick now requires `--local-live`; without it `loop.py` refuses to run outside GitHub Actions.

**Kill switch:** set `active: true` in `data/HALT.json`. It blocks new entries while exits and reconciliation keep running by design. `loop.py` sets it automatically on a naked leg or an untracked broker position, and it is git-published each tick so it survives the ephemeral runner.

Repo: `https://github.com/Kalwaleed/theta-gate` (private, 6 collaborators).

---

## The strategy, in one paragraph

Put-credit spreads on SPY and QQQ, 6–9 DTE, short delta 0.16–0.25, $5 wide, **exactly 1 contract**. Entries at 10:30 and 13:30 ET in 15-minute windows; weekends short-circuit before any chain fetch or billed model call. A bearish proposal is NO_TRADE — V1 is put-only, never a call-side substitution. Last new entry Wed 2 Sep 10:45 ET; everything flattens Thu 3 Sep from 14:30 ET via a four-rung ladder; Fri 4 Sep is monitor-only before the 11:00 ET submission. The model proposes an underlying and a direction and nothing else — every strike, size, price and gate is deterministic Python, and `risk.py` has the last word.
