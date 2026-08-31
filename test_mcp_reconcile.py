"""X2 -- the read-only MCP reconciliation auditor. The tests pin the two
properties that make it safe to run unattended: it can never write to the
broker, and it fails as a red run + journal event, never as a crash or a
HALT."""

import asyncio
import importlib.util
import json
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

import loop

spec = importlib.util.spec_from_file_location("mcp_reconcile", Path("scripts/mcp_reconcile.py"))
mr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mr)

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# The write boundary
# ---------------------------------------------------------------------------

def test_options_never_allow_a_write_tool(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    o = mr.build_options()
    assert set(o.allowed_tools) == {"mcp__alpaca__get_all_positions", "mcp__alpaca__get_orders"}
    assert not any("place" in t or "cancel" in t or "close" in t or "exercise" in t
                   for t in o.allowed_tools)
    assert set(mr.WRITE_TOOLS) <= set(o.disallowed_tools)
    assert o.tools == []
    assert o.permission_mode == "dontAsk"
    assert o.mcp_servers["alpaca"]["env"]["ALPACA_PAPER_TRADE"] == "true"
    assert o.mcp_servers["alpaca"]["env"]["ALPACA_TOOLSETS"] == "trading"
    args = o.mcp_servers["alpaca"]["args"]
    assert any(a == "alpaca-mcp-server==2.3.0" for a in args), "server version must stay pinned"
    assert any(a == "fastmcp==3.2.0" for a in args), "fastmcp must stay pinned (2.3.0 breaks on newer)"


def test_refuses_the_live_flag(monkeypatch):
    monkeypatch.setenv("ALPACA_LIVE_TRADE", "true")
    with pytest.raises(SystemExit):
        mr.refuse_live()
    monkeypatch.setenv("ALPACA_LIVE_TRADE", "false")
    mr.refuse_live()  # must not raise


def test_never_imports_the_trading_broker_module():
    source = Path("scripts/mcp_reconcile.py").read_text()
    assert "import alpaca" not in source, "the auditor must not share the trader's code path"
    assert "_trigger_halt" not in source, "the auditor never HALTs"


# ---------------------------------------------------------------------------
# Envelope unwrap -- data from ToolResultBlocks only
# ---------------------------------------------------------------------------

def test_unwrap_extracts_the_server_envelope():
    assert mr.unwrap(json.dumps({"data": {"result": [{"symbol": "SPY"}]}})) == [{"symbol": "SPY"}]
    assert mr.unwrap([{"type": "text", "text": json.dumps({"data": {"result": []}})}]) == []


@pytest.mark.parametrize("bad", ["not json", json.dumps([1, 2]), json.dumps({"nope": 1}),
                                  json.dumps({"data": "flat"}), None, 42])
def test_unwrap_returns_none_on_anything_else(bad):
    assert mr.unwrap(bad) is None


# ---------------------------------------------------------------------------
# The diff -- reuses loop._open_positions, catches every audited shape
# ---------------------------------------------------------------------------

def _journal_pos(short="SPY1", long_="SPY2"):
    return [{"position_id": "p1", "underlying": "SPY", "short_symbol": short, "long_symbol": long_}]


def test_diff_clean_book_matches():
    d = mr.diff(_journal_pos(), [{"symbol": "SPY1", "asset_class": "us_option"},
                                  {"symbol": "SPY2", "asset_class": "us_option"}], [], [])
    assert d["matched"] == ["SPY1", "SPY2"] and mr.is_clean(d)


def test_diff_flags_the_f3_phantom_as_journal_only():
    d = mr.diff(_journal_pos(), [], [], [])
    assert d["journal_only"] == ["SPY1", "SPY2"] and not mr.is_clean(d)


def test_diff_flags_broker_only_and_equity():
    d = mr.diff([], [{"symbol": "SPY1", "asset_class": "us_option"},
                     {"symbol": "SPY", "asset_class": "us_equity"}], [], [])
    assert d["broker_only"] == ["SPY1"] and d["broker_equity"] == ["SPY"] and not mr.is_clean(d)


def test_diff_flags_fills_the_journal_never_saw():
    today = datetime.now(ET).strftime("%Y%m%d")
    orders = [{"client_order_id": f"tg-e-{today}-1030-spy-s0", "filled_qty": "1"},
              {"client_order_id": f"tg-e-{today}-1030-spy-s1", "filled_qty": "0"},   # unfilled -> ignored
              {"client_order_id": "someone-elses-order", "filled_qty": "3"}]         # not ours -> ignored
    d = mr.diff([], [], orders, [])
    assert d["fills_unknown_to_journal"] == [f"tg-e-{today}-1030-spy-s0"]
    assert d["orders_seen"] == 3 and not mr.is_clean(d)


def test_diff_flags_journal_fills_the_broker_never_saw():
    today = datetime.now(ET).strftime("%Y%m%d")
    events = [{"event": "entry_filled", "client_order_id": f"tg-e-{today}-1030-spy-s0"}]
    d = mr.diff([], [], [], events)
    assert d["journal_fills_unknown_to_broker"] == [f"tg-e-{today}-1030-spy-s0"]


# ---------------------------------------------------------------------------
# fetch_broker_state failure classification (fake SDK, no network)
# ---------------------------------------------------------------------------

class _B:  # base for the fake SDK's record types -- module-level so
    # isinstance() agrees between message builders and the patched module
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Sys(_B): pass
class Asst(_B): pass
class User(_B): pass
class Res(_B): pass
class Use(_B): pass
class ToolRes(_B): pass


def _fake_sdk(messages):
    """Builds a fake claude_agent_sdk module whose query() replays `messages`."""
    m = types.ModuleType("claude_agent_sdk")

    async def query(prompt, options):
        for msg in messages:
            yield msg

    for name, obj in [("SystemMessage", Sys), ("AssistantMessage", Asst),
                      ("UserMessage", User), ("ResultMessage", Res),
                      ("ToolUseBlock", Use), ("ToolResultBlock", ToolRes),
                      ("TextBlock", _B), ("query", query)]:
        setattr(m, name, obj)
    return m


def _run_fetch(messages):
    mod = _fake_sdk(messages)
    with patch.dict(sys.modules, {"claude_agent_sdk": mod}):
        return asyncio.run(mr.fetch_broker_state(options=None))


def _happy_messages(positions_result="[]", orders_result="[]", connected=True):
    msgs = []
    msgs.append(Sys(data={"mcp_servers": [{"name": "alpaca",
                                            "status": "connected" if connected else "failed"}]}))
    msgs.append(Asst(content=[Use(id="t1", name="mcp__alpaca__get_all_positions"),
                              Use(id="t2", name="mcp__alpaca__get_orders")]))
    msgs.append(User(content=[
        ToolRes(tool_use_id="t1", is_error=False,
                content=json.dumps({"data": {"result": json.loads(positions_result)}})),
        ToolRes(tool_use_id="t2", is_error=False,
                content=json.dumps({"data": {"result": json.loads(orders_result)}})),
    ]))
    msgs.append(Res(is_error=False))
    return msgs


def test_fetch_happy_path_returns_both_datasets():
    positions, orders, failure = _run_fetch(_happy_messages('[{"symbol": "SPY1"}]', '[]'))
    assert failure is None and positions == [{"symbol": "SPY1"}] and orders == []


def test_fetch_fails_when_the_server_never_connects():
    positions, orders, failure = _run_fetch(_happy_messages(connected=False))
    assert positions is None and "not connected" in failure


def test_fetch_flags_a_401_style_tool_error():
    msgs = _happy_messages()
    # replace the tool results with one error block (server connected, key bad)
    msgs[2] = User(content=[ToolRes(tool_use_id="t1", is_error=True, content="401 unauthorized")])
    positions, orders, failure = _run_fetch(msgs)
    assert positions is None and "tool error" in failure


def test_fetch_never_trusts_model_text_for_data():
    # tool results missing entirely; the model could have "said" anything
    msgs = _happy_messages()
    del msgs[2]
    positions, orders, failure = _run_fetch(msgs)
    assert positions is None and "missing" in failure


# ---------------------------------------------------------------------------
# main() -- journal event, publish, exit codes, lock
# ---------------------------------------------------------------------------

def _main_with(monkeypatch, tmp_path, fetch_result, publish_calls=None, no_publish=False):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "j.jsonl"))
    monkeypatch.setattr(loop, "LOCK_PATH", str(tmp_path / "lock"))
    monkeypatch.setenv("ALPACA_LIVE_TRADE", "false")
    calls = publish_calls if publish_calls is not None else []
    monkeypatch.setattr(loop, "_git_publish", lambda now: calls.append(now) or {"pushed": True})
    async def fake_fetch(options):
        if isinstance(fetch_result, Exception):
            raise fetch_result
        return fetch_result
    monkeypatch.setattr(mr, "fetch_broker_state", fake_fetch)
    monkeypatch.setattr(mr, "build_options", lambda: None)
    argv = ["--no-publish"] if no_publish else []
    return mr.main(argv), loop._read_journal()


def test_clean_run_journals_one_info_event_and_publishes(monkeypatch, tmp_path):
    publishes = []
    rc, events = _main_with(monkeypatch, tmp_path, ([], [], None), publishes)
    assert rc == 0
    assert [e["event"] for e in events] == ["mcp_reconciliation"]
    assert events[0]["clean"] is True and events[0]["level"] == "info"
    assert len(publishes) == 1


def test_mismatch_is_rc1_warning_and_never_halts(monkeypatch, tmp_path):
    monkeypatch.setattr(loop, "HALT_PATH", str(tmp_path / "HALT.json"))
    rc, events = _main_with(monkeypatch, tmp_path,
                            ([{"symbol": "GHOST1", "asset_class": "us_option"}], [], None))
    assert rc == 1
    assert events[0]["event"] == "mcp_reconciliation" and events[0]["level"] == "warning"
    assert events[0]["broker_only"] == ["GHOST1"]
    assert loop._check_halt()[0] is False


def test_sdk_exception_is_a_failed_run_not_a_crash(monkeypatch, tmp_path):
    rc, events = _main_with(monkeypatch, tmp_path, RuntimeError("uvx resolve timed out"))
    assert rc == 1
    assert events[0]["event"] == "mcp_reconciliation_failed"
    assert "uvx resolve timed out" in events[0]["error"]


def test_tick_lock_defers_with_rc2(monkeypatch, tmp_path):
    monkeypatch.setattr(loop, "JOURNAL_PATH", str(tmp_path / "j.jsonl"))
    monkeypatch.setattr(loop, "LOCK_PATH", str(tmp_path / "lock"))
    monkeypatch.setenv("ALPACA_LIVE_TRADE", "false")
    monkeypatch.setattr(loop, "_acquire_lock", lambda: False)
    assert mr.main([]) == 2
    assert loop._read_journal() == []


def test_no_publish_flag_skips_git(monkeypatch, tmp_path):
    publishes = []
    rc, _ = _main_with(monkeypatch, tmp_path, ([], [], None), publishes, no_publish=True)
    assert rc == 0 and publishes == []
