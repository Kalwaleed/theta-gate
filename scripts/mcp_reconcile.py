#!/usr/bin/env python3
"""Read-only MCP reconciliation — the auditor, not the trader (X2,
ANALYSIS-2026-08-30, prototype verified live against the submission
account on 30 Aug: server connected, 5 read + 5 docs tools, zero write
tools, ~$0.04, 5.4s).

Once per session close (16:05 ET cron), a SECOND, independent integration
— Alpaca's MCP server, not the CLI the trading loop uses — reads the
broker's positions and orders and diffs them against the journal's view.
Two different code paths agreeing is evidence; one code path agreeing
with itself is not.

Hard boundaries, in order of importance:
- READ ONLY. The model gets exactly two tools (get_all_positions,
  get_orders); every write tool in the server's trading toolset is
  disallowed by name as well. `ALPACA_TOOLSETS=trading` strips the rest —
  verified live: `tools=[]` alone left all ~70 mcp__alpaca__ tools
  callable.
- Data comes from ToolResultBlocks ONLY — the server's envelope, never
  the model's prose about it. The model is a tool-caller here, not a
  source of truth.
- NEVER HALTs, never imports alpaca.py, never touches an order. A
  mismatch is a red run and a warning journal event for a human; the
  trading loop's own reconciliation owns the live response.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import loop  # journal read/append, _git_publish, tick lock -- NOT alpaca.py

ET = ZoneInfo("America/New_York")
MODEL_ID = "claude-opus-5"
MCP_SERVER_VERSION = "2.3.0"
FASTMCP_VERSION = "3.2.0"

ALLOWED_TOOLS = [
    "mcp__alpaca__get_all_positions",
    "mcp__alpaca__get_orders",
]
# Belt to ALLOWED_TOOLS' suspenders: every write tool in the trading
# toolset, denied by name. If the server renames one, allowed_tools still
# gates -- with permission_mode "dontAsk", anything not allowed is denied.
WRITE_TOOLS = [
    "mcp__alpaca__place_stock_order",
    "mcp__alpaca__place_option_market_order",
    "mcp__alpaca__place_crypto_order",
    "mcp__alpaca__cancel_order_by_id",
    "mcp__alpaca__cancel_all_orders",
    "mcp__alpaca__close_position",
    "mcp__alpaca__close_all_positions",
    "mcp__alpaca__exercise_options_position",
    "mcp__alpaca__do_not_exercise_options_position",
    "mcp__alpaca__update_order",
]

PROMPT = (
    "Call get_all_positions, then call get_orders with status='all' for today. "
    "After both tool calls return, reply with the single word: done. "
    "Do not summarize, interpret, or repeat the data."
)


def refuse_live():
    """Same fail-closed flag check as the trading loop's environment gate."""
    live_signal = os.environ.get("ALPACA_LIVE_TRADE", "")
    if live_signal.strip().lower() in ("true", "1", "yes"):
        raise SystemExit(f"ALPACA_LIVE_TRADE={live_signal!r} indicates live trading -- refusing to reconcile")


def build_options():
    from claude_agent_sdk import ClaudeAgentOptions
    return ClaudeAgentOptions(
        model=MODEL_ID,
        max_turns=6,
        tools=[],
        allowed_tools=ALLOWED_TOOLS,
        disallowed_tools=WRITE_TOOLS,
        permission_mode="dontAsk",
        mcp_servers={
            "alpaca": {
                "command": "uvx",
                # fastmcp pinned too: 2.3.0 declares fastmcp>=3.1.0 but
                # imports fastmcp.tools.tool, which a NEWER fastmcp removed
                # -- a fresh uvx resolve picks that newer one and the server
                # dies on import with status "failed" and no other symptom
                # (found live 31 Aug; 3.1.0 and 3.2.0 both verified to boot).
                "args": ["--with", f"fastmcp=={FASTMCP_VERSION}",
                          f"alpaca-mcp-server=={MCP_SERVER_VERSION}"],
                "env": {
                    # An explicit env REPLACES the subprocess environment --
                    # without PATH, `uvx` is unfindable and the server
                    # reports status "failed" with no other symptom
                    # (rediscovered live 31 Aug; cost one debugging pass).
                    "PATH": os.environ.get("PATH", ""),
                    "HOME": os.environ.get("HOME", ""),
                    "ALPACA_API_KEY": os.environ.get("ALPACA_API_KEY", ""),
                    "ALPACA_SECRET_KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
                    "ALPACA_PAPER_TRADE": "true",
                    "ALPACA_TOOLSETS": "trading",
                },
            }
        },
        strict_mcp_config=True,
        setting_sources=[],
    )


def unwrap(tool_content):
    """The server wraps every result as {"data": {"result": ...}} (verified
    live 30 Aug). ToolResultBlock content arrives as a string or a list of
    text blocks; anything that does not unwrap to a data.result is None --
    the caller treats None as a failed run, never as an empty book."""
    if isinstance(tool_content, list):
        tool_content = "".join(
            part.get("text", "") if isinstance(part, dict) else getattr(part, "text", "")
            for part in tool_content
        )
    if not isinstance(tool_content, str):
        return None
    try:
        payload = json.loads(tool_content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    return data.get("result")


async def fetch_broker_state(options):
    """One query() drive. Returns (positions, orders, failure_reason).
    failure_reason is None only when the server connected, both tools
    returned without is_error, and both unwrapped to real data."""
    from claude_agent_sdk import query, AssistantMessage, UserMessage, SystemMessage, ResultMessage
    from claude_agent_sdk import ToolUseBlock, ToolResultBlock

    connected = False
    results_by_tool_id = {}
    tool_names_by_id = {}
    tool_errors = []
    result_is_error = False

    async for message in query(prompt=PROMPT, options=options):
        if isinstance(message, SystemMessage):
            for server in (message.data or {}).get("mcp_servers", []):
                if server.get("name") == "alpaca" and server.get("status") == "connected":
                    connected = True
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    tool_names_by_id[block.id] = block.name
        elif isinstance(message, UserMessage):
            content = message.content if isinstance(message.content, list) else []
            for block in content:
                if isinstance(block, ToolResultBlock):
                    if block.is_error:
                        # a 401 arrives here as is_error with the server still connected
                        tool_errors.append(tool_names_by_id.get(block.tool_use_id, "unknown"))
                    else:
                        results_by_tool_id[block.tool_use_id] = unwrap(block.content)
        elif isinstance(message, ResultMessage) and message.is_error:
            result_is_error = True

    if not connected:
        return None, None, "mcp server not connected"
    if tool_errors:
        return None, None, f"tool error from: {sorted(set(tool_errors))}"
    if result_is_error:
        return None, None, "sdk result is_error"

    positions = orders = None
    for tool_id, data in results_by_tool_id.items():
        name = tool_names_by_id.get(tool_id, "")
        if name.endswith("get_all_positions"):
            positions = data
        elif name.endswith("get_orders"):
            orders = data
    if positions is None or orders is None:
        return None, None, "missing or unparseable tool data"
    return positions, orders, None


def diff(journal_open, broker_positions, broker_orders, journal_events):
    """The whole point. journal_open comes from loop._open_positions — the
    same function the trading loop trusts, so this diff can never drift
    from the loop's own idea of 'open'."""
    journal_symbols = {
        s for rec in journal_open for s in (rec.get("short_symbol"), rec.get("long_symbol")) if s
    }
    broker_options, broker_equity = set(), set()
    for p in broker_positions or []:
        symbol = p.get("symbol", "")
        if p.get("asset_class") == "us_equity":
            broker_equity.add(symbol)
        else:
            broker_options.add(symbol)

    today = datetime.now(ET).strftime("%Y%m%d")
    broker_fill_cids = {
        str(o.get("client_order_id") or "")
        for o in broker_orders or []
        if str(o.get("client_order_id") or "").startswith(("tg-e-", "tg-x-"))
        and today in str(o.get("client_order_id") or "")
        and float(o.get("filled_qty") or 0) > 0
    }
    journal_fill_cids = {
        str(e.get("client_order_id") or "")
        for e in journal_events
        if e.get("event") in ("entry_filled", "exit_filled", "exit_partial_fill")
        and today in str(e.get("client_order_id") or "")
    }

    return {
        "matched": sorted(journal_symbols & broker_options),
        "journal_only": sorted(journal_symbols - broker_options),   # F3 phantom shape
        "broker_only": sorted(broker_options - journal_symbols),
        "broker_equity": sorted(broker_equity),                     # assignment shape
        "orders_seen": len(broker_orders or []),
        "fills_unknown_to_journal": sorted(broker_fill_cids - journal_fill_cids),
        "journal_fills_unknown_to_broker": sorted(journal_fill_cids - broker_fill_cids),
    }


def is_clean(d):
    return not (d["journal_only"] or d["broker_only"] or d["broker_equity"]
                or d["fills_unknown_to_journal"] or d["journal_fills_unknown_to_broker"])


def main(argv=None):
    args = argparse.ArgumentParser(description="Read-only MCP reconciliation (the auditor, not the trader)")
    args.add_argument("--no-publish", action="store_true",
                      help="LOCAL RUNS ONLY. Also redirects the journal to a throwaway "
                           "data/rehearsal-reconcile-*.jsonl -- a dev run must never write "
                           "mcp_reconciliation rows into the real audit trail (the same rule "
                           "as loop.py --as-of; two failed dev rows from 31 Aug are already "
                           "permanently in the journal because this flag once only skipped git)")
    opts = args.parse_args(argv)

    refuse_live()
    if opts.no_publish:
        stamp = datetime.now(ET).strftime("%Y%m%dT%H%M%S")
        loop.JOURNAL_PATH = f"data/rehearsal-reconcile-{stamp}.jsonl"
        print(f"LOCAL RUN  journal={loop.JOURNAL_PATH}  (real journal untouched, no git publish)",
              file=sys.stderr)

    if not loop._acquire_lock():
        print("tick lock held -- a trading tick is running; not reconciling mid-tick", file=sys.stderr)
        return 2

    try:
        try:
            positions, orders, failure = asyncio.run(fetch_broker_state(build_options()))
        except Exception as exc:  # noqa: BLE001 -- SDK/CLI/uvx failures are a failed RUN, never a crash
            positions, orders, failure = None, None, f"{type(exc).__name__}: {exc}"

        now = datetime.now(ET)
        if failure is not None:
            loop._append_journal("mcp_reconciliation_failed", level="warning", error=failure[:400],
                                  model=MODEL_ID, server_version=MCP_SERVER_VERSION)
            print(json.dumps({"ok": False, "error": failure}, indent=2))
            if not opts.no_publish:
                loop._git_publish(now)
            return 1

        journal_events = loop._read_journal()
        result = diff(loop._open_positions(journal_events), positions, orders, journal_events)
        clean = is_clean(result)
        loop._append_journal("mcp_reconciliation", level="info" if clean else "warning",
                              clean=clean, model=MODEL_ID, server_version=MCP_SERVER_VERSION, **result)
        print(json.dumps({"ok": True, "clean": clean, **result}, indent=2))
        if not opts.no_publish:
            loop._git_publish(now)
        return 0 if clean else 1
    finally:
        loop._release_lock()


if __name__ == "__main__":
    sys.exit(main())
