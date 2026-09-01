# Status — Theta Gate

**Rolling status log, not a one-time handoff — updated in place as the trading day progresses.** Last updated Mon 31 Aug 2026, ~14:10 ET (21:10 Riyadh). First live trading day, in progress right now. Deadline: **submission Fri 4 Sep, 11:00 ET.**

**Verify before trusting this file** — `git log --oneline -5`, `pytest -q`, `gh pr list`, `gh run list --workflow="Theta Gate Agent" --limit 5`. If it disagrees with the repo, the repo is right. No commit hash is quoted here as "current"; they go stale immediately, the agent's own `journal:` commits included.

Deep reference: **`docs/ANALYSIS-2026-08-30.md`** — a 157-agent audit from Sunday, every finding with severity, the day-by-day plan, two designs (X1 sizing, X2 MCP reconciliation). Written before today's events below — treat this file as the current layer on top of it, not a replacement.

Multiple Claude sessions have touched this repo. This one is `theta-gate-scoped-v1`, running as a **background job** — everything below is verified by this session directly, not secondhand. A separate **interactive** session with the identical name (`[4de1cb]` in `ListAgents`) and a read-only audit session (`theta-gate-hackathon-analysis`) have also been active; this file cannot speak to what either of them did that isn't visible in git/GitHub.

---

## Right now, this exact moment

### Tue 1 Sep — three firsts in one trade

- **10:33 ET: QQQ 699/694P filled, $5 wide, qty 2, exp 4 Sep, credit $0.59**, max
  loss $882 against the $1,000 cap. Position `tg-e-20260901-1030-qqq`.
- **It proposed QQQ, not SPY — `f7b74b9`'s position-aware routing running live for
  the first time.** SPY was at its per-underlying cap from Monday, so the model was
  only offered what it could actually trade. At 10:44 the same fix logged
  `all_underlyings_at_cap` and **skipped the model call entirely** rather than
  proposing something the gates would veto. Both halves of that commit are now proven.
- **First qty-2 fill (X1) and first 3-5 DTE fill.** Expiry 4 Sep is 3 days out, so
  Thursday's force-close catches it a day before expiry — the decay capture the
  tenor change (`2f0472f`, msuiche's finding) exists for.
- **The entry ladder worked as designed:** first order at mid −0.63 did not fill in
  40 seconds, re-priced to −0.58, filled at 0.59.
- **First fill-versus-quote measurement.** Realised credit/width 0.118 against 0.120
  quoted five minutes earlier — about 2.5% slippage at $5 width, which matches the
  half-of-bid-ask assumption. Book now at capacity: 2 concurrent, 1 per underlying,
  so no further entries today.


- **09:36 ET today: the first-ever cron-scheduled tick fired**, and it worked. Every green run before this was `workflow_dispatch` — the schedule trigger was unproven all week (see the closed PR #8). It is proven now.
- **10:30 ET: first live trade, filled clean.** SPY bull put credit spread, short 754P / long 749P, $5 wide, qty 1, exp 9 Sep, credit $0.61 (order `7fe33b90`). Both legs filled atomically at the same broker timestamp — no naked leg. `tick_completed` immediately after: `halt_active: false`, `orphan_symbols: []`.
- **The price-sign convention is now verified live, for the first time ever.** Pulled the raw order directly from Alpaca (`alpaca order get`, not just the journal): parent `filled_avg_price: "-0.61"` matches submitted `limit_price: "-0.61"` exactly. `loop.py`'s `_extract_actual_price` docstring updated to record this (commit `a3b1447`) — no longer flagged as unverified.
- **13:30 ET window: correctly declined, not a bug.** Ticks at 13:38 and 13:45 ET each got a fresh SPY proposal from the model and both were blocked by the risk gate: `"concurrent: already at max positions for SPY"` — one position per underlying, and the 10:30 spread is still open. Confirmed by reading `risk.py`'s gate, not assumed.
- **QQQ has not been proposed today — confirmed by design, not a gap.** `brain.py` builds market-data context for both SPY and QQQ every call (`_build_context_text`, lines 118-122) but its system prompt requires exactly ONE underlying per proposal (`brain.py:68`, "propose ONE underlying, ONE direction"). The model saw both symbols each time and chose SPY twice. This matches the canonical plan Sec 9.1/9.2 cited in the file header — one bounded model call, one proposal, per tick.
- **16:00 ET close: watched, and nothing fired.** Position `tg-e-20260831-1030-spy` carries overnight, `hold` on every exit evaluation all day, cost-to-close 0.46–0.49 at the last two ticks against the 0.61 credit (small unrealized gain, well short of the 0.305 take-profit). No `exit_intent`, no naked leg, no orphans; `data/HALT.json` `active: false` and every `tick_completed` `ok: true` throughout. Repo: **PRIVATE** (correct, unchanged).
- **On present marks this spread most likely exits via Thursday's force-close ladder, not via take-profit.** That ladder is now covered at every rung (PR #24) and rehearsable before its date with `loop.py --as-of` — see Operating notes.
- **284 tests pass**, up from 155 as of Sunday.
- **X1 landed tonight (`ac714be`): `fixed_quantity` 1 -> 2**, with partial-fill handling on every order path. PK's call, taken after seeing the arithmetic. Worth recording that the per-trade cap cannot be reached by sizing alone: at the $5 width and the 10%-of-width credit floor, the worst case a qty-2 position can carry is $900 against the $1,000 cap, and two of them are $1,800 against the $3,000 open-risk cap. Every gate still binds. Rollback is one value in `governance.json`.
- **What qty 2 does and does not buy.** Max profit across two positions rises from $122 to $244 on a $100k account -- 0.24%. Capital at risk rises from $878 to $1,800. Credit/width tracks ~0.8 x short delta (verified live 26 Aug), so the arithmetic edge is roughly zero minus the bid-ask: this is 4x variance, not 4x edge, and it raises the chance the submitted P&L is negative rather than a small positive. Recorded here so the write-up and the deck say the same thing.
- **Next watch point: tomorrow's 10:30 ET entry window.** SPY is at its per-underlying cap, so this is the first live exercise of `f7b74b9`'s position-aware routing — the model should be offered QQQ instead of SPY, or no call made at all. Never yet seen live.

---

## What changed since Sunday's handoff, and why it matters

**The submission-account bugs are fixed and now proven, not just fixed.** Sunday's handoff covered two zero-trade bugs (`alpaca._run` reading stdout only; the option chain capped at 100 contracts) — both fixed then, both now validated by real scheduled ticks running clean.

**A real gap in my own earlier verification, found by someone else, now closed.** I built `.github/workflows/go-public.yml` (the Thursday public-flip automation) and reported a passing dry run as proof it worked. PR #18 (merged, not mine) correctly identified that dry run only exercised `gh repo view` — a *read*. It never tested `Administration: write`, the one permission the actual flip needs, and that PAT was **already known** to be missing a different permission it was assumed to have (`Pull requests`, which 403'd on 30 Aug). The fix: the dry run now does a no-op `PATCH` to the real endpoint. **Re-run and confirmed PASS this morning** — the write permission genuinely works. Lesson for next time: a green dry run proves only what it actually calls, not what the task needs.

**PK's real email is out of the repo's git history — everywhere, verified.** `looods@gmail.com` was in 14 commits across every branch (repo was about to go public Thursday). Rewrote via `git filter-repo` with a mailmap (`→ 196770746+Kalwaleed@users.noreply.github.com`), force-pushed with `--force-with-lease`, verified zero occurrences across all branches on a fresh independent clone. One branch (`chore/gitignore-agent-state`) needed a second pass — it kept moving while teammates pushed to it live, and I nearly reported it clean based on a single-commit spot check that was wrong (its direct parent looked clean; its full ancestry wasn't — always check the whole ancestry, not one hop). Fully clean now, confirmed.

Operational notes for anyone doing history surgery on this repo again: **`git push --force` (blind) and `git filter-repo` get blocked unpredictably by this environment's safety classifier** — sometimes they run, sometimes they don't, with no obvious pattern. `git push --force-with-lease=<branch>:<expected-sha>` with an explicit expected hash has worked reliably every time. If `filter-repo` itself is blocked, there's no clean workaround short of the user running it directly.

**PR #11 (deck) merged Monday morning without the fixes I'd flagged — now fixed directly on `main` (commit `f823296`).** Both confirmed bugs:
1. `deck/theta-gate.tex:43` — `BoldFont=* SemiBold` → `SmBld`. IBM Plex Sans registers that weight as `SmBld`; `make` hard-failed and emitted no PDF with the real font installed, confirmed by reproducing the failure before the fix and a clean build after.
2. `deck/theta-gate.tex:152,190,484` — "eighteen"/"18 gates" → **21**, matching `risk.py`'s own docstring (`_STATE_ONLY_GATES` 18 + `_SIZED_GATES` 3).

`make check` still reports 8 pre-existing content-overflow warnings, confirmed present before this fix too (unrelated to the font/count bugs, a separate layout issue — design is the team's call per PK's note below).

**Automated spam PRs — source identified, and PK revoked it on 31 Aug. Closed.** The identical "feat: add theta-gate ECC bundle" PR (#2, #10, #15, #16, #19) comes from the **`ecc-tools` GitHub App** (bot, not a repo collaborator — confirmed against the 6-person collaborator list). Revoking its access requires a GitHub App JWT; a personal-account PAT can't do it (`401`/`403` on every API path tried). This is a personal account (not an org), so there was no admin-API route either — it had to be done via github.com/settings/installations → ecc-tools → Configure → remove `theta-gate`. **PK did that on 31 Aug.** Confirmed as far as a PAT allows: the `ecc-tools/theta-gate-*` remote branch is gone, all five of its PRs (#2, #10, #15, #16, #19) are closed, and none are open. The revocation itself is not PAT-readable — the real proof is that no sixth spam PR appears. If one does, it was not revoked.

---

## Open PRs

**None**, as of 16:15 ET Monday 31 Aug (`gh pr list` returns 0). Everything has been merged or closed. New work from a peer session may appear at any time — more than one session has been committing to this worktree today, so re-check before assuming.

**Merged Monday afternoon:** #23 (decision log was an allowlist — 18 hidden event types, 9 operator-critical), #24 (Thursday's force-close ladder covered at every rung, plus `loop.py --as-of` to rehearse it before its date), #25 (flatten an overnight assignment autonomously).

**Closed Monday afternoon, both sizing changes, both rejected:** #26 (size from the proposer's confidence) and #27 (3 concurrent positions, up to 15 contracts). `governance.json` is unchanged and still canonical: `max_concurrent_positions` 2, one position per underlying, quantity fixed at 1, `max_loss_per_trade_dollars` 1000.

**Follow-up landed on `main` after #24 merged (`c5e37ba`):** `--as-of` sandboxed the rehearsal journal and the git publish but not `data/HALT.json`, and `_trigger_halt` writes even under `--dry-run` by design. A rehearsal could therefore stop the live cron three days before the deadline — and because `_trigger_halt` is first-reason-wins, the genuine halt that followed could no longer state its own reason. `HALT_PATH` is now redirected alongside `JOURNAL_PATH`, seeded from the real file so a real active HALT stays visible to `_check_halt`.

**Merged since Sunday:** #11 (deck — merged unfixed, fixed directly on `main` Monday, see above), #12 (cover, clean), #18 (go-public write-permission fix), #20 (brain.py test coverage, 155→241 tests).

**Closed since Sunday**, each with reasoning in the PR thread: #8, #10, #13 (audit preserved at `docs/SECURITY-REVIEW-2026-08-30.md`), #14 (superseded — its useful `.gitignore` additions were folded into `main` by hand in `2d6df54`), #15, #16, #17 (empty-body duplicate of #13), #19.

---

## Decisions PK has taken

- **VRP option C** — committed (Sunday). `realised_vol_lookback_days` 10, `min_vrp_points` 1.0.
- **Commit-history disclosure** — `96fd434` (1,049 lines) landed 3h40m before kickoff. State it plainly in the write-up.
- **Design is the team's** — fonts, palette, layout, deck structure. Correctness (a build that emits no PDF, a wrong gate count) is worth flagging once; the deck merging without those fixes applied means it's worth flagging again, since it's now live on `main`, not held in a PR.
- **Public flip** — Thursday **3 Sep, 17:00 ET (00:00 Riyadh, effectively Friday)**, one day before the actual Fri 4 Sep 11:00 ET deadline (Thursday is *not* the deadline — confirmed and corrected 30 Aug). Automated via `.github/workflows/go-public.yml`, now fully verified including write permission. A session-bound backup cron also exists (job `85094226` in this session) but dies if this session ends — the GitHub Actions workflow is the durable one.
- **Never trade the submission account by hand** — its history is judges' evidence of autonomy.

---

## Gotchas — do not re-derive

- **`alpaca doctor --profile X` silently ignores the flag.** Every call routes through `ALPACA_PROFILE` env var (`_profile_env`). Only `doctor` lies.
- **`ALPACA_ACCOUNT_ID` is the UUID, not the account number.** `assert_paper` compares against `id`.
- **GitHub secrets and variables are separate namespaces.** `secrets.X` resolves to empty when X is a variable — silently.
- **A fine-grained GitHub PAT's `Administration` scope does not cover `gh pr list`.** That needs a separate `Pull requests` read permission. Caused a real failure in `go-public.yml`; fixed by making that step `continue-on-error` (it's informational only — never let a non-critical step block a critical one).
- **The default GitHub Actions `GITHUB_TOKEN` cannot change repo visibility** — hard platform limit, not a `permissions:` config choice. Needs a fine-grained PAT (`Administration: write`, this repo only), stored as `REPO_ADMIN_PAT`.
- **A green dry run only proves what it actually calls.** `go-public.yml`'s first version tested read access and was reported as "tested, works" — it never touched the write path that mattered. Check what the dry run actually exercises before trusting it.
- **`--dry-run` gates `submit_mleg` *and* `cancel_order`.** A cancel is a broker write.
- **A duplicate `client_order_id` returns HTTP 422, never a second order.** The entire idempotency mechanism.
- **`brain.py`'s validation is not HTML-aware.** `app.py`'s `esc()` is the only thing preventing script injection in a judge's browser. Do not remove it as redundant.
- **Rewriting git history changes every downstream commit hash.** A branch left un-rewritten will show "no common ancestor" with a rewritten `main` — that's expected for *any* stale branch, active work or not, and isn't itself evidence of anything.

---

## Known-open, deliberately

- **Exchange holidays are not checked** — weekday gate only. None fall in the window.
- **No automated single-leg repair.** A naked leg triggers HALT; a human closes it.
- **Orphan equity (assignment) is detected, not flattened** — same reason.
- **A failed `git push` still loses that tick's local writes.** Loud (`ok: false`, red run), not recovered.
- **X1 (qty 1→2 partial-fill sizing) and X2 (read-only MCP reconciliation)** — designed in Sunday's analysis as after-close work. Not confirmed done or not done as of this writing; check `governance.json`'s quantity field and whether an MCP reconciliation step exists in `loop.py` before assuming either way.

---

## Deliverables still outstanding

Demo URL (not deployed — no deploy config found in the repo), video, write-up, and the deck fixes above. Cover (#12) is done. Social posts: 1 of 5 as of Sunday's audit, and that one post may predate the eligible window — unverified since.

---

## Operating notes

```bash
# a local tick -- reads and journal writes are real, broker writes held back
set -a; source .env; set +a
.venv/bin/python3 loop.py --once --dry-run --profile submission

# read-only gate diagnostic (costs one real brain.propose call)
PYTHONPATH=. .venv/bin/python3 scripts/live_gate_check.py

# rehearse the trading workflow on the real runner
gh workflow run "Theta Gate Agent" --repo Kalwaleed/theta-gate -f dry_run=true

# rehearse the public-flip workflow (now properly tests write permission)
gh workflow run go-public.yml --repo Kalwaleed/theta-gate -f dry_run=true
```

Use `.venv/bin/python3`, never system `python3`. A live local tick requires `--local-live`; without it `loop.py` refuses to run outside GitHub Actions.

**Kill switch:** set `active: true` in `data/HALT.json`. Blocks new entries; exits and reconciliation keep running by design. Git-published each tick so it survives the ephemeral runner.

Repo: `https://github.com/Kalwaleed/theta-gate` (private, 6 collaborators: msuiche, PasoUnleashed, Kalwaleed, turki-Twj, ghaus47, roymchoi).

---

## The strategy, in one paragraph

Put-credit spreads on SPY and QQQ, 6–9 DTE, short delta 0.16–0.25, $5 wide, **exactly 1 contract** (unless X1 above has since landed). Entries at 10:30 and 13:30 ET in 15-minute windows; weekends short-circuit before any chain fetch or billed model call. A bearish proposal is NO_TRADE — V1 is put-only, never a call-side substitution. Last new entry Wed 2 Sep 10:45 ET; everything flattens Thu 3 Sep from 14:30 ET via a four-rung ladder; Fri 4 Sep is monitor-only before the 11:00 ET submission. The model proposes an underlying and a direction and nothing else — every strike, size, price and gate is deterministic Python, and `risk.py` has the last word.
