# Handoff — Theta Gate

**Written Sat 29 Aug 2026, 11:40 ET** — after the GitHub Actions rehearsal ran green on the real runner with all three secrets verified populated. `main` is pushed and in sync with `origin`; 96/96 tests pass (the team merged PRs #1/#3/#4/#5 — `store.py`, `app.py` and doc corrections — on top). **No blockers remain for Monday's first live session.** Deadline: **submission Fri 4 Sep, 11:00 ET.**

Read this first, then `docs/PLAN.md` (design + timeline) and `docs/THETA_GATE_CANONICAL_PLAN.md` (strategy authority). This file covers only what a fresh session needs to resume, and is written to go stale — update or delete it once trading starts. **Verify state rather than trusting this file** (`git log --oneline -5`, `pytest -q`); if it disagrees with the repo, the repo is right. Commit hashes are deliberately not quoted as "current" here — they go stale the moment anything else lands, `journal:` commits from the agent itself included.

---

## Where things stand

Every file in the trading path is built, tested, and committed. **96/96 tests pass** (`pytest -q`, Python 3.14.6 in `.venv`).

| Component | State |
|---|---|
| `alpaca.py`, `spread.py`, `risk.py` | Built, tested |
| `market.py`, `brain.py`, `loop.py` | Built, tested |
| `.github/workflows/agent.yml` | Built; cron every 5 min, weekdays, 09:30–16:00 ET |
| `governance.json`, event calendar | Built |
| `scripts/live_gate_check.py` | Built; read-only diagnostic, mirrors the entry pipeline |
| `store.py` (SQLite read model) | Built (PR #1); derived from the journal, gitignored, no trading-path coupling |
| `app.py` (Streamlit dashboard) | Built (PR #5); read-only, no credentials. **Not yet deployed** — the hosted URL is a hard submission gate |
| `README.md` write-up for judges | **Not built** — Thursday, needs real trading history |

GitHub config is complete and **verified by a real run**: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` and `ANTHROPIC_API_KEY` all render as `***` (masked = populated) in run `33260744206`'s env dump; `ALPACA_ACCOUNT_ID` is a **variable**, not a secret — the workflow reads it via `vars.`, which matters (see gotchas).

The workflow itself is proven end to end: a `workflow_dispatch` rehearsal ran green on the real runner Sat 29 Aug 11:15 ET (run `33259706303`, 46s) — checkout, Python 3.14, pinned Alpaca CLI 0.0.13, `assert_paper` against the real account, live broker reads, and `_git_publish` committing and pushing the journal to `main` as `theta-gate-agent[bot]`. Returned `ok: true`, `entry.attempted: false` (weekend, correctly short-circuited). That run is what proves the CI half of durability: until it, `_git_publish` had only ever been exercised on a local machine, never from an ephemeral runner where a lost push actually costs state.

Two harmless observations from that run, noted so nobody re-investigates them: the runner resolves Python **3.14.7** against the local venv's 3.14.6 (patch drift, `python-version: "3.14"` is intentionally not pinned tighter), and GitHub annotates the run with a **Node 20 deprecation warning** for `actions/checkout@v4` / `actions/setup-python@v5` — both are forced onto Node 24 and work fine. Neither is a failure; both will keep appearing.

Account: fresh paper account, id `7a013821-9249-4505-8025-fb298f0931a5`, $100,000, zero positions, zero orders, zero manual trades. **Never place a manual order on it** — its history is the judges' evidence the agent is autonomous.

---

## Do this next

**1. Close PR #2 — it is the only open PR and it should not be merged.** "feat: add theta-gate ECC bundle", authored by the `app/ecc-tools` GitHub App, not a team member. It touches no `.py`, no `.github/`, no `governance.json` (verified three ways), and `brain.py`'s `setting_sources=[]` means the trading loop could not load it even if merged — so this is a cost/benefit call, not a security incident. Decline it because it adds zero trading functionality six days from submission while configuring five MCP servers via unpinned `npx -y <pkg>@latest` plus a live remote endpoint (`mcp.exa.ai`) in `.codex/config.toml`. Its generated skill also instructs agents to use PascalCase filenames and TypeScript idioms in what is a snake_case Python repo, from "1 analyzed commits" — guidance wrong about the repo's own language, carrying `allow_implicit_invocation: true`. Full reasoning is posted as a comment on the PR.

**2. Re-run the rehearsal any time you change a secret or the workflow.**

```bash
gh workflow run "Theta Gate Agent" --repo Kalwaleed/theta-gate -f dry_run=true
gh run watch --repo Kalwaleed/theta-gate
gh run view <run-id> --repo Kalwaleed/theta-gate --log | grep -E "API_KEY:"
```

Safe on a weekend: `_current_entry_window` returns `None` Sat/Sun, so the entry pipeline short-circuits — no billed LLM call, no order path. Expect `ok: true`, `entry.attempted: false`, a new `theta-gate-agent[bot]` journal commit, and every `*_API_KEY` rendering as `***`.

**3. Monday during market hours — finish the gate verification.** The weekend live check confirmed gates fire in the right order, but only up to `gate_delta_band`: no candidate reached the 0.16–0.25 delta band (real deltas were 0.04–0.08 in low-vol conditions), so `credit_quality`, `minimum_credit`, `quote_sanity`, `vrp_present` and the three sized gates have **never fired on a real qualifying candidate**. Re-run the checker once the market is open:

```bash
set -a; source .env; set +a
PYTHONPATH=. .venv/bin/python3 scripts/live_gate_check.py
```

It mirrors `loop.py`'s entry pipeline exactly (same functions, same order) but is strictly read-only — no journal writes, no git, no order submission. It *does* make one real `brain.propose()` call, so it costs an Anthropic API call per run.

**4. Deploy the dashboard to Streamlit Community Cloud.** `app.py` is merged but not hosted, and the demo URL is a hard submission gate — no URL, entry not judged. Two things to know before it goes public: `.streamlit/config.toml` now sets `showErrorDetails = "none"` (the repo is private, the URL will not be — don't remove it), and `store.connect()`/`rebuild()` has no locking, so confirm several simultaneous cold loads don't race on the SQLite rebuild before handing the link to judges.

**5. Watch the first live entry closely.** Two things are still unverified against a real fill, because no fill has ever happened: the **sign convention** on `filled_avg_price` (`_extract_actual_price` in `loop.py` assumes it mirrors `limit_price`'s negative-is-credit convention), and `_map_account_state`'s Alpaca field names. Both are disclosed in code comments.

---

## Gotchas that already bit us — do not re-derive

- **`alpaca doctor --profile X` silently ignores the flag.** Verified live. `alpaca.py` routes every call through the `ALPACA_PROFILE` env var instead (`_profile_env`). Regular commands like `account get` *do* honor `--profile`; only `doctor` lies. Do not "simplify" this back to the flag.
- **`ALPACA_ACCOUNT_ID` is the UUID, not the account number.** `PA32UO0QXLRO` is the account_number shown in Alpaca's dashboard; `assert_paper` compares against `id`. Using the account_number fails closed on every tick, permanently.
- **GitHub secrets and variables are separate namespaces.** `secrets.ALPACA_ACCOUNT_ID` resolves to an empty string when the value is stored as a variable — silent, and it trips `assert_paper` on every scheduled run. Cost us a real blocker; fixed in `257ccdc`.
- **`--dry-run` gates `submit_mleg` *and* `cancel_order`.** A cancel is a broker write, and an order under dry-run may be a *real* order adopted from an earlier live tick. Do not add a broker write that ignores the `dry_run` flag.
- **Duplicate `client_order_id` is rejected with HTTP 422, never duplicated.** Verified live. This is the entire idempotency mechanism: recompute the *same* id on retry and look it up first. A random fallback id would silently defeat it.
- **`.env` lines carry leading whitespace, and the file has a stray heredoc marker.** Sourcing it prints `.env:7: command not found: EOF` (harmless). The whitespace is not harmless: `grep '^KEY='` silently matches nothing, which is how an empty `ANTHROPIC_API_KEY` reached GitHub and cost two failed attempts. Setting a secret from `.env` needs no `^` anchor, plus quote/CR stripping — and **echo the character count to prove extraction worked before storing it**:
  ```bash
  V=$(grep -m1 '^[^#]*ANTHROPIC_API_KEY=' .env | cut -d= -f2- | tr -d ' "'"'"'\r'); echo "extracted ${#V} chars"
  printf '%s' "$V" | gh secret set ANTHROPIC_API_KEY --repo Kalwaleed/theta-gate
  ```
- **Interactive `gh secret set` does not work from Claude Code's `!` prompt.** stdin isn't a TTY there, so `gh` reads nothing and silently stores an empty value. Use the piped form above, a real terminal, or the GitHub web UI.
- **`gh secret list` cannot tell an empty secret from a populated one.** Both show name + timestamp; `gh secret set` prints nothing either way. The only reliable check is a workflow run: a populated secret renders as `***` in the log's env dump, an empty one renders blank. This is the single highest-value verification in the whole setup — it is how the empty key was caught at all.
- **The docs described things that were never built, and one wrong fact appeared three times.** `docs/PLAN.md` claimed MCP-based perception and a second-pass critic re-verifying delta and credit; neither shipped (`brain.py` runs `tools=[]`, `mcp_servers={}`, `max_turns=1`, and there is no critic anywhere). It also said the agent executes via `api POST /v2/orders` — it does not; `submit_mleg` shells out to `order submit --order-class mleg` (`alpaca.py:207-215`), and `api POST` is a raw passthrough this codebase never calls. Both are corrected. The lesson for Thursday's write-up: **grep the claim against the code before it ships to judges**, and when a wrong fact turns up, grep for every other copy of it — that one appeared in the architecture diagram, the CLI summary, and the integration section.

---

## Known-open, deliberately

- **Exchange holidays are not checked.** `_current_entry_window` gates on weekday only. None fall in the 31 Aug–4 Sep window, and a holiday tick fails safe anyway (stale quotes → `gate_quote_sanity` rejects). Upgrade path if this outlives the hackathon: gate on `alpaca.clock()`'s `is_open`.
- **No automated single-leg repair.** If a cancel loses the race against a fill and leaves one leg naked, `loop.py` sets HALT and journals CRITICAL — a human closes it. `alpaca.py` has no single-leg order primitive, and building one untested days before the deadline is its own risk. Detection is thorough; remediation is manual.
- **Orphan equity (overnight assignment) is detected, not flattened.** Same reason — no stock-order primitive in `alpaca.py`. Blocks entries, journals CRITICAL.
- **A failed `git push` loses that tick's local writes.** Now loud (tick returns `ok: false`, non-zero exit, red Actions run) rather than silent, but not recovered.
- **`store.connect()`/`rebuild()` has no locking** (`store.py:317`, `:331`). Two concurrent callers hitting a missing or stale `.db` can race on create/unlink and raise an uncaught `sqlite3.OperationalError`. Nothing hits it concurrently today — but the deployed dashboard will, since Streamlit Community Cloud can serve several judges at once and a cold session may trigger a rebuild. Confined to the read model; the journal is never written from there, so the trading path cannot be affected. Test before the demo URL is public.

---

## Operating notes

Run a tick locally (reads and journal writes are real; broker writes held back):

```bash
set -a; source .env; set +a
.venv/bin/python3 loop.py --once --dry-run --profile submission
```

Use `.venv/bin/python3`, not system `python3` — `claude_agent_sdk` is only in the venv.

**Kill switch:** set `active: true` in `data/HALT.json`. Blocks all new entries; exits and reconciliation keep running by design. `loop.py` also sets it automatically on a naked leg or an untracked broker position. It is git-published each tick, so it survives the ephemeral runner.

Repo: `https://github.com/Kalwaleed/theta-gate` (private). Six collaborators already have access; no one else needs adding.

---

## Trading plan, in one line each

Put-credit spreads on SPY/QQQ, 6–9 DTE, short delta 0.16–0.25, $5 wide, **exactly 1 contract**, entries at 10:30 and 13:30 ET in 15-minute windows. Bearish proposals are NO_TRADE — V1 is put-only, never a call-side substitution. Last new entry Wed 2 Sep 10:45 ET; everything flattens Thu 3 Sep from 14:30 ET via a four-rung ladder; Fri 4 Sep is monitor-only ahead of the 11:00 ET submission. The LLM proposes an underlying and a direction and nothing else — strikes, sizing, and every gate are deterministic Python.
