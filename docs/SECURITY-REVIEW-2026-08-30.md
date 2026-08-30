# Pre-publication security review

**Reviewer:** Matt Suiche. **Date:** 30 Aug 2026. **Scope:** full repository, full history, ahead of making the repo public.

Preserved from PR #13, which was closed because its only code change — deleting `.memsearch/` — had already landed on `main` in `1e980f4`. The audit itself is the part worth keeping. Lift this table into Thursday's write-up.

**Result: one finding worth acting on, since fixed. No credential has ever been committed.**

## What was checked

| Check | Result |
|---|---|
| `.env` or any env/secret/key file ever committed, in any commit | **Never** |
| Every blob in every reachable commit, scanned for `sk-ant-*`, `PK[A-Z0-9]{18,}`, `AKIA*`, PEM private keys | **Only the `XXXX` placeholders in `env.example`** |
| Secrets logged, printed, or journaled | **None** — no `print`/`_append_journal` touches a KEY/SECRET/TOKEN |
| Journal fields ever written | `ts, event, ok, level, reason, error, profile, halt_active, orphan_symbols, exits, entry_attempted` — nothing sensitive |
| Workflow `permissions:` | `contents: write` only, scoped for the journal push; no `pull-requests`, no `issues` |
| Workflow injection surface | `${{ }}` used only for secrets/vars into `env:`, plus a `boolean` `dry_run` input settable only by collaborators. Not attacker-controllable — no `pull_request_target`, no `issue_comment`, no fork trigger |
| `.claude/settings.json` (goes public) | No secrets. Allowlist is read verbs only; `position close-all` and `order cancel-all` explicitly denied |
| LLM boundary | `tools=[]`, `mcp_servers={}`, `strict_mcp_config=True`, `setting_sources=[]` — nothing can hand the model a credential |

## The finding — closed

`.memsearch/` was local tooling scratch, committed by accident: 161 lines of session summaries with 14 absolute transcript paths, plus a machine-local index path and directory tree. Together they exposed a teammate's local username and home-directory layout in 16 places.

Severity **low** — paths and a handle, not credentials. `main` untracked and gitignored the directory in `1e980f4`, so the working tree is clean.

## History is deliberately not rewritten

The blobs stay in history. A `filter-repo` pass would rewrite **every commit hash in the project**, including the `theta-gate-agent[bot]` journal commits — and the judges read commit history as evidence the work happened inside the window. Trading that evidence away to hide a home directory is a bad exchange.

If the team disagrees, it must happen **before** the repo is public, not after.

## Two open items for the team

1. **Commit-author emails become public** with the repo. Two personal addresses appear in `git log`; `Kalwaleed` already uses a GitHub noreply address. If either author wants theirs private, decide before publishing — same history-rewrite trade-off as above.
2. **Dashboard sequencing.** PR #9 fixed an HTML-injection hole in `app.py` where journal strings — including the model's free-text thesis — rendered as live markup. **Merged 30 Aug**, before any public deployment. Do not remove `app.py`'s `esc()` as redundant: `brain.py`'s validation is word-count and substring only, and is not HTML-aware.
