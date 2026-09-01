# Theta Gate

An autonomous options-trading agent for the [Alpaca AI Trading Agents Hackathon](https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon) (28 Aug – 4 Sep 2026).

**The one idea:** the LLM has read-only tools. Every write goes through deterministic Python. A proposer suggests a direction; it never picks a strike, sizes a position, or holds an order credential. A pure-Python risk guard has final say and cannot be argued with — the breach is not reachable, not merely forbidden.

This file is the getting-started guide and team workflow note. The full design doc — architecture, every risk gate, the corrections from live testing, the timeline — lives at **[`docs/PLAN.md`](docs/PLAN.md)**. Read that before touching `risk.py` or `spread.py`. Strategy/architecture authority is **[`docs/THETA_GATE_CANONICAL_PLAN.md`](docs/THETA_GATE_CANONICAL_PLAN.md)** — see `docs/PLAN.md` for which parts of it we build (Scoped V1) and which we deliberately don't (a Postgres/OIDC control-plane, sized for a production system rather than a 5-day paper demo). The final one-page write-up for judging gets built here on Thursday, once there's real trading history to report.

**Live dashboard:** https://theta-gate-km6zecgl3nxqiqnh7fpdqg.streamlit.app/

## Status

Built and passing: `alpaca.py`, `spread.py`, `risk.py`, `market.py`, `brain.py`, `loop.py`, `store.py`, `app.py`, `governance.json`, `data/events_2026-08-31_2026-09-04.json`, `.github/workflows/agent.yml` — 155/155 tests across `test_agent.py`, `test_loop.py`, `test_store.py` and `test_app.py`. Three diagrams at [`docs/diagrams/`](docs/diagrams/). Run the dashboard locally with `streamlit run app.py`. See the Repo layout table in `docs/PLAN.md` for the live checklist.

## Quick start

```bash
git clone https://github.com/Kalwaleed/theta-gate.git
cd theta-gate
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                          # 155 passed
```

You'll also want the Alpaca CLI (`brew install alpacahq/tap/cli`) and your own paper API keys in a local `.env` (copy `env.example` — see the trap documented inside it before you touch `ALPACA_PAPER_TRADE` / `ALPACA_LIVE_TRADE`). `ALPACA_ACCOUNT_ID` is now a hard requirement, not just documentation for judges — `alpaca.assert_paper()` refuses to trade the `submission` profile at all unless it's set and matches the live account, closing a gap where a config mistake could silently point `submission` at the wrong paper account.

**Never run write commands against the submission account.** Its trade history is what judges read as "autonomous" — a manual order on it, even a test, undermines that claim. If you need to poke at the live API, use your own throwaway paper account.

**MCP is the auditor, not the trader.** The trading loop touches the broker through the Alpaca CLI only. Alpaca's MCP server (`alpaca-mcp-server`, pinned `==2.3.0` in `.mcp.json`) runs once per session close in `scripts/mcp_reconcile.py` (cron: `.github/workflows/reconcile.yml`, 16:05 ET): a deliberately separate, read-only integration — exactly two read tools allowed, every write tool denied by name — that diffs the broker's positions and orders against the journal. Two independent code paths agreeing is evidence; one code path agreeing with itself is not. A mismatch is a red run and a `warning` journal event for a human — the reconciler never places, cancels, or closes anything, and never HALTs.

## Team workflow

Five of us are pushing to the same repo, so a couple of habits keep it boring:

- **Pull before you push.** `git pull --rebase origin main` first, always — the Actions cron will also be committing `journal.jsonl` once `loop.py` exists, several times a day.
- **Small, real commits.** lablab's judges check commit history for evidence the AI core was built inside the hackathon window, not assembled once and pushed. Commit as you go.
- **Run `pytest -q` before you push anything touching `risk.py` or `spread.py`.** These two files are the whole safety story — a broken gate is a real-money-shaped bug even on paper.
- **Don't touch `.env` in a commit.** It's gitignored; if `git status` ever shows it staged, stop and ask.

## Submission

Submitted from Khaled's (`Kalwaleed`) lablab.ai account, matching this repo's owner and the paper trading account required by the hackathon rules.

## Licensing

MIT (see `LICENSE`). `.agents/skills/` redistributes Alpaca's own agent skills under Apache-2.0 — see `.agents/skills/LICENSE` and `NOTICE`.
