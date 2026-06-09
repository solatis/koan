# Negative-presence guards: assert the deleted HTTP MCP transport and permission
# fence modules cannot be imported. If either module reappears (e.g. via a
# mistaken git revert), these tests catch it before the rest of the suite can
# silently regress to the old code paths.

import importlib
import pytest


def test_mcp_endpoint_module_deleted():
    """koan.web.mcp_endpoint was deleted in M1; importing it must raise ModuleNotFoundError."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("koan.web.mcp_endpoint")


def test_permissions_module_deleted():
    """koan.lib.permissions was deleted in M1; importing it must raise ModuleNotFoundError."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("koan.lib.permissions")


def test_probe_module_deleted():
    """koan.probe was deleted in M4; importing it must raise ModuleNotFoundError."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("koan.probe")


def test_claude_agent_module_deleted():
    """koan.agents.claude was deleted in M4; importing it must raise ModuleNotFoundError."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("koan.agents.claude")


def test_command_line_agent_module_deleted():
    """koan.agents.command_line was deleted in M4; importing it must raise ModuleNotFoundError."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("koan.agents.command_line")


def test_runners_package_deleted():
    """koan.runners was deleted in M4; importing it must raise ModuleNotFoundError."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("koan.runners")
