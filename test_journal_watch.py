"""scripts/journal_watch.py -- the shell watchers' journal parser.

The first assertion is the whole point: importing this module is enough to
catch a syntax error. The parser it replaced lived inside a shell string,
so nothing checked it until it ran, and on 2 Sep it ran nine times and
raised SyntaxError nine times -- the final entry window went unwatched.
CI is the gate now.
"""

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("journal_watch", Path("scripts/journal_watch.py"))
jw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jw)   # a SyntaxError here fails the whole file


def _write(tmp_path, records):
    path = tmp_path / "journal.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return str(path)


ENTRY = {"ts": "2026-09-03T10:33:15-04:00", "event": "entry_filled",
         "position_id": "tg-e-20260903-1030-spy", "underlying": "SPY", "qty": 2, "ok": True}
FORCE = {"ts": "2026-09-03T15:45:12-04:00", "event": "force_close_unresolved", "level": "critical",
         "position_id": "tg-e-20260903-1030-spy", "reason": "final rung, still open"}


def test_since_prints_force_close_unresolved_and_marks_it_critical(tmp_path, capsys):
    journal = _write(tmp_path, [ENTRY, FORCE])
    assert jw.main(["--since", "0", "--journal", journal]) == 0
    out = capsys.readouterr().out
    assert "FORCE_CLOSE_UNRESOLVED" in out
    assert "*** CRITICAL ***" in out
    # the high water mark comes back so the next poll starts where this one stopped
    assert "SEQ=2" in out
    assert jw.main(["--since", "2", "--journal", journal]) == 0
    assert "FORCE_CLOSE_UNRESOLVED" not in capsys.readouterr().out


def test_flat_is_nonzero_while_a_position_is_open(tmp_path, capsys):
    journal = _write(tmp_path, [ENTRY])
    assert jw.main(["--flat", "--journal", journal]) == 1
    assert "tg-e-20260903-1030-spy" in capsys.readouterr().out


def test_flat_is_zero_once_every_entry_has_a_matching_exit(tmp_path, capsys):
    exit_filled = {"ts": "2026-09-03T15:30:02-04:00", "event": "exit_filled",
                   "position_id": ENTRY["position_id"], "underlying": "SPY", "ok": True}
    journal = _write(tmp_path, [ENTRY, exit_filled])
    assert jw.main(["--flat", "--journal", journal]) == 0
    assert "FLAT" in capsys.readouterr().out


def test_a_torn_final_line_is_skipped_not_fatal(tmp_path, capsys):
    journal = _write(tmp_path, [ENTRY, FORCE])
    with open(journal, "a", encoding="utf-8") as f:
        f.write('{"ts": "2026-09-03T15:50:00-04:00", "event": "tick_com')   # mid-write crash
    assert jw.main(["--since", "0", "--journal", journal]) == 0
    assert "FORCE_CLOSE_UNRESOLVED" in capsys.readouterr().out
    assert jw.main(["--flat", "--journal", journal]) == 1


def test_last_tick_reports_the_newest_tick_and_the_halt_flag(tmp_path, capsys):
    ticks = [{"ts": f"2026-09-03T{t}-04:00", "event": "tick_completed", "halt_active": False}
             for t in ("14:31:02", "15:01:44")]
    assert jw.main(["--last-tick", "--journal", _write(tmp_path, ticks)]) == 0
    out = capsys.readouterr().out
    assert "15:01:44" in out and "halt=False" in out


def test_last_tick_is_nonzero_when_no_tick_has_landed(tmp_path):
    assert jw.main(["--last-tick", "--journal", _write(tmp_path, [ENTRY])]) == 1
