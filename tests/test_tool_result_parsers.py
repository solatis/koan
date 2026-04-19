"""Tests for the tool-result parsers in ClaudeRunner.

Covers the three exploration tool parsers (read, grep, ls), the content-shape
helper that normalizes string vs. list content, and one integration test that
exercises the full parse_stream_event path with a synthetic user message.
"""
from __future__ import annotations

import json

from koan.runners.claude import (
    ClaudeRunner,
    _parse_grep_result,
    _parse_ls_result,
    _parse_read_result,
    _tool_result_text,
)


# ---------------------------------------------------------------------------
# _tool_result_text
# ---------------------------------------------------------------------------

class TestToolResultText:
    def test_string_content_returned_as_is(self):
        assert _tool_result_text("hello") == "hello"

    def test_list_of_text_blocks_joined(self):
        content = [
            {"type": "text", "text": "one\n"},
            {"type": "text", "text": "two"},
        ]
        assert _tool_result_text(content) == "one\ntwo"

    def test_list_with_non_text_blocks_skipped(self):
        content = [
            {"type": "image", "data": "..."},
            {"type": "text", "text": "only this"},
        ]
        assert _tool_result_text(content) == "only this"

    def test_unknown_shape_returns_empty(self):
        assert _tool_result_text(None) == ""
        assert _tool_result_text(42) == ""


# ---------------------------------------------------------------------------
# Read parser
# ---------------------------------------------------------------------------

class TestReadParser:
    def test_basic_numbered_lines(self):
        text = "     1\tfirst line\n     2\tsecond line\n     3\tthird\n"
        metrics = _parse_read_result(text)
        assert metrics == {
            "lines_read": 3,
            "bytes_read": len(b"first linesecond linethird"),
        }

    def test_strips_trailing_system_reminder(self):
        text = (
            "1\tabc\n"
            "2\tdef\n"
            "<system-reminder>\nDo not touch.\n</system-reminder>"
        )
        metrics = _parse_read_result(text)
        assert metrics == {"lines_read": 2, "bytes_read": len(b"abcdef")}

    def test_empty_result_returns_none(self):
        assert _parse_read_result("") is None

    def test_non_numbered_output_returns_none(self):
        assert _parse_read_result("just some text\nwithout tabs\n") is None

    def test_utf8_byte_counting(self):
        # Three "hello" with a multibyte char.
        text = "1\théllo\n"
        metrics = _parse_read_result(text)
        assert metrics is not None
        assert metrics["lines_read"] == 1
        assert metrics["bytes_read"] == len("héllo".encode("utf-8"))


# ---------------------------------------------------------------------------
# Grep parser
# ---------------------------------------------------------------------------

class TestGrepParser:
    def test_files_with_matches_mode(self):
        text = "src/a.py\nsrc/b.py\nsrc/c.py\n"
        assert _parse_grep_result(text) == {"matches": 3, "files_matched": 3}

    def test_content_mode_path_line_match(self):
        text = (
            "src/a.py:10:def foo():\n"
            "src/a.py:42:def bar():\n"
            "src/b.py:5:def baz():\n"
        )
        assert _parse_grep_result(text) == {"matches": 3, "files_matched": 2}

    def test_count_mode(self):
        text = "src/a.py:4\nsrc/b.py:2\nsrc/c.py:1\n"
        assert _parse_grep_result(text) == {"matches": 7, "files_matched": 3}

    def test_summary_line_with_files(self):
        text = "Found 42 matches in 6 files\nsome context line\n"
        assert _parse_grep_result(text) == {"matches": 42, "files_matched": 6}

    def test_summary_line_without_files(self):
        text = "Found 12 matches\n"
        metrics = _parse_grep_result(text)
        assert metrics is not None
        assert metrics["matches"] == 12

    def test_empty_result_returns_none(self):
        assert _parse_grep_result("") is None
        assert _parse_grep_result("   \n\n") is None


# ---------------------------------------------------------------------------
# Ls parser
# ---------------------------------------------------------------------------

class TestLsParser:
    def test_tree_listing_counts_entries_and_dirs(self):
        text = (
            "- /path/to/root/\n"
            "  - file1.py\n"
            "  - file2.py\n"
            "  - subdir/\n"
            "    - nested.py\n"
            "  - another_dir/\n"
        )
        metrics = _parse_ls_result(text)
        # 5 entries (file1, file2, subdir, nested, another_dir); 2 dirs (subdir, another_dir).
        assert metrics == {"entries": 5, "directories": 2}

    def test_header_not_counted(self):
        text = "- /home/user/\n  - a\n"
        assert _parse_ls_result(text) == {"entries": 1, "directories": 0}

    def test_empty_result_returns_none(self):
        assert _parse_ls_result("") is None
        assert _parse_ls_result("nothing relevant\n") is None


# ---------------------------------------------------------------------------
# parse_stream_event integration
# ---------------------------------------------------------------------------

class TestParseStreamEventUser:
    def _runner(self) -> ClaudeRunner:
        return ClaudeRunner(subagent_dir="/tmp/does-not-matter")

    def test_user_message_with_read_tool_result_emits_event(self):
        r = self._runner()
        # Prime the tracker as if a Read tool_use block had been seen earlier.
        r._exploration_tool_by_id["toolu_123"] = "read"
        payload = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_123",
                        "content": "1\talpha\n2\tbeta\n",
                    }
                ]
            },
        }
        events = r.parse_stream_event(json.dumps(payload))
        assert len(events) == 1
        ev = events[0]
        assert ev.type == "tool_result"
        assert ev.tool_name == "read"
        assert ev.tool_use_id == "toolu_123"
        assert ev.metrics == {"lines_read": 2, "bytes_read": len(b"alphabeta")}
        # Tracker drained.
        assert "toolu_123" not in r._exploration_tool_by_id

    def test_user_message_with_untracked_tool_result_is_ignored(self):
        r = self._runner()
        payload = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_unknown",
                        "content": "anything",
                    }
                ]
            },
        }
        assert r.parse_stream_event(json.dumps(payload)) == []

    def test_user_message_with_list_content_handled(self):
        r = self._runner()
        r._exploration_tool_by_id["toolu_456"] = "grep"
        payload = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_456",
                        "content": [
                            {"type": "text", "text": "src/a.py:10:hit\n"},
                            {"type": "text", "text": "src/b.py:20:hit\n"},
                        ],
                    }
                ]
            },
        }
        events = r.parse_stream_event(json.dumps(payload))
        assert len(events) == 1
        assert events[0].metrics == {"matches": 2, "files_matched": 2}

    def test_user_message_with_unparseable_content_emits_none_metrics(self):
        r = self._runner()
        r._exploration_tool_by_id["toolu_789"] = "read"
        payload = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_789",
                        "content": "not numbered lines\n",
                    }
                ]
            },
        }
        events = r.parse_stream_event(json.dumps(payload))
        assert len(events) == 1
        assert events[0].metrics is None
