# koan_yield removal guard (M5b).
#
# koan_yield was removed when the agent loop went in-process: a terminal-text
# turn (no tool calls) is the hand-back signal, so the explicit yield tool is
# gone. These tests assert it does not creep back into the tool registry or
# the permission tables.

from __future__ import annotations


def test_koan_yield_absent_from_mcp_tool_registry():
    # koan.runners.base deleted in M4; KOAN_MCP_TOOLS lives in koan.agents.events.
    from koan.agents.events import KOAN_MCP_TOOLS
    assert "koan_yield" not in KOAN_MCP_TOOLS


def test_koan_yield_absent_from_role_permissions():
    # ROLE_PERMISSIONS now lives in koan.tools.tool_policy (inlined from permissions.py in M1).
    from koan.tools.tool_policy import ROLE_PERMISSIONS
    for role, tools in ROLE_PERMISSIONS.items():
        assert "koan_yield" not in tools, f"koan_yield leaked into {role!r} permissions"
