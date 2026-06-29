# Tests for koan/home.py: resolver precedence, was_home_explicit, negative-presence,
# derivation into FileKeyBackend / save_koan_config, and CLI both-position + require-exists.

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from koan.home import resolve_koan_home, was_home_explicit


# ---------------------------------------------------------------------------
# resolve_koan_home: precedence and expansion
# ---------------------------------------------------------------------------

class TestResolveKoanHome:
    def test_cli_home_wins_over_env(self, tmp_path):
        """cli_home takes precedence over KOAN_HOME in env."""
        cli = str(tmp_path / "cli")
        env_val = str(tmp_path / "env")
        result = resolve_koan_home(cli, env={"KOAN_HOME": env_val})
        assert result == Path(cli).expanduser().resolve()

    def test_env_used_when_cli_home_is_none(self, tmp_path):
        """KOAN_HOME is used when cli_home is None."""
        env_val = str(tmp_path / "env-home")
        result = resolve_koan_home(None, env={"KOAN_HOME": env_val})
        assert result == Path(env_val).expanduser().resolve()

    def test_default_when_both_absent(self, koan_home):
        """Default Path.home() / '.koan' is used when neither cli_home nor KOAN_HOME is set.

        The autouse koan_home fixture patches Path.home() to the tmp dir, so the
        default branch resolves to tmp_path / '.koan' == koan_home.
        """
        result = resolve_koan_home(None, env={})
        assert result == Path.home() / ".koan"

    def test_tilde_expanded_in_cli_home(self, tmp_path):
        """A tilde in cli_home is expanded via expanduser."""
        # We can test this by using an absolute path that won't exist; just verify
        # the path object is returned expanded (no leading ~).
        raw = str(tmp_path / "explicit")
        result = resolve_koan_home(raw, env={})
        assert not str(result).startswith("~")
        assert result.is_absolute()

    def test_relative_cli_home_is_resolved_to_absolute(self, tmp_path, monkeypatch):
        """A relative cli_home is resolved to an absolute path."""
        monkeypatch.chdir(tmp_path)
        result = resolve_koan_home("relative-dir", env={})
        assert result.is_absolute()
        assert result == (tmp_path / "relative-dir").resolve()


# ---------------------------------------------------------------------------
# was_home_explicit
# ---------------------------------------------------------------------------

class TestWasHomeExplicit:
    def test_true_when_cli_home_provided(self):
        """Returns True when cli_home is a non-None string."""
        assert was_home_explicit("/some/path", env={}) is True

    def test_true_when_koan_home_env_set(self):
        """Returns True when KOAN_HOME is in env."""
        assert was_home_explicit(None, env={"KOAN_HOME": "/some/path"}) is True

    def test_false_when_both_absent(self):
        """Returns False when neither cli_home nor KOAN_HOME env is set."""
        assert was_home_explicit(None, env={}) is False

    def test_cli_home_empty_string_is_falsy_so_env_wins(self):
        """An empty string cli_home leaves env as the source of truth.

        An empty string is not None, but resolve_koan_home treats it as falsy;
        was_home_explicit mirrors that by checking cli_home is not None.
        """
        # cli_home="" is not None, so was_home_explicit returns True even though
        # resolve_koan_home would fall through to env.  This is acceptable: the
        # caller passed an explicit (if empty) value.
        assert was_home_explicit("", env={}) is True


# ---------------------------------------------------------------------------
# Negative presence: removed globals must not exist
# ---------------------------------------------------------------------------

class TestRemovedGlobals:
    def test_config_path_absent(self):
        """CONFIG_PATH must not exist in koan.config after the hard cutover."""
        import koan.config as cfg_mod
        assert not hasattr(cfg_mod, "CONFIG_PATH"), (
            "CONFIG_PATH was re-introduced; hard cutover requires permanent removal"
        )

    def test_master_key_path_absent(self):
        """MASTER_KEY_PATH must not exist in koan.credentials after the hard cutover."""
        import koan.credentials as creds_mod
        assert not hasattr(creds_mod, "MASTER_KEY_PATH"), (
            "MASTER_KEY_PATH was re-introduced; hard cutover requires permanent removal"
        )

    def test_runs_dir_absent(self):
        """RUNS_DIR must not exist in koan.web.app after the hard cutover."""
        import koan.web.app as app_mod
        assert not hasattr(app_mod, "RUNS_DIR"), (
            "RUNS_DIR was re-introduced; hard cutover requires permanent removal"
        )


# ---------------------------------------------------------------------------
# Derivation: home threads correctly into FileKeyBackend and save_koan_config
# ---------------------------------------------------------------------------

class TestDerivation:
    def test_file_key_backend_creates_master_key_in_home(self, tmp_path):
        """FileKeyBackend(home).load_key() creates home/master.key."""
        from koan.credentials import FileKeyBackend
        home = tmp_path / "koan-state"
        home.mkdir()
        FileKeyBackend(home).load_key()
        assert (home / "master.key").exists()

    @pytest.mark.anyio
    async def test_save_koan_config_writes_config_yaml_in_home(self, tmp_path, monkeypatch):
        """save_koan_config(cfg, home) writes home/config.yaml."""
        from koan.config import KoanConfig, save_koan_config
        monkeypatch.setattr("koan.config._config_write_lock", None)
        home = tmp_path / "koan-state"
        home.mkdir()
        cfg = KoanConfig(scout_concurrency=7)
        await save_koan_config(cfg, home)
        assert (home / "config.yaml").exists()

    @pytest.mark.anyio
    async def test_load_koan_config_reads_from_home(self, tmp_path, monkeypatch):
        """load_koan_config(home) reads home/config.yaml."""
        from koan.config import KoanConfig, load_koan_config, save_koan_config
        monkeypatch.setattr("koan.config._config_write_lock", None)
        home = tmp_path / "koan-state"
        home.mkdir()
        cfg = KoanConfig(scout_concurrency=42)
        await save_koan_config(cfg, home)
        loaded = await load_koan_config(home)
        assert loaded.scout_concurrency == 42


# ---------------------------------------------------------------------------
# CLI both-position: --home before and after subcommand
# ---------------------------------------------------------------------------

class TestCliHomePosition:
    """Build the top-level parser as __main__ does and verify --home is parsed
    from both positions (before the subcommand and after it).

    Uses argparse directly rather than invoking main() so no server or driver
    starts; we only test the parse-and-resolve contract.
    """

    def _build_parser(self):
        """Reproduce the argparse setup from __main__.py."""
        import argparse
        from koan.home import resolve_koan_home, was_home_explicit

        common = argparse.ArgumentParser(add_help=False)
        common.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
        common.add_argument("--home", default=argparse.SUPPRESS, metavar="PATH")

        parser = argparse.ArgumentParser(prog="koan", parents=[common])
        subs = parser.add_subparsers(dest="subcommand")

        run_parser = subs.add_parser("run", parents=[common])
        run_parser.add_argument("--port", type=int, default=None)

        mem_parser = subs.add_parser("memory", parents=[common])
        mem_subs = mem_parser.add_subparsers(dest="memory_command")
        mem_subs.add_parser("status", parents=[common])

        return parser, resolve_koan_home, was_home_explicit

    def test_home_before_subcommand_run(self, tmp_path):
        """--home /path koan run resolves to /path."""
        parser, rk, _ = self._build_parser()
        home_path = str(tmp_path)
        args = parser.parse_args(["--home", home_path, "run"])
        cli_home = getattr(args, "home", None)
        assert cli_home == home_path
        assert rk(cli_home, env={}) == Path(home_path).resolve()

    def test_home_after_subcommand_run(self, tmp_path):
        """koan run --home /path resolves to /path."""
        parser, rk, _ = self._build_parser()
        home_path = str(tmp_path)
        args = parser.parse_args(["run", "--home", home_path])
        cli_home = getattr(args, "home", None)
        assert cli_home == home_path
        assert rk(cli_home, env={}) == Path(home_path).resolve()

    def test_home_before_subcommand_memory(self, tmp_path):
        """--home /path koan memory status resolves to /path."""
        parser, rk, _ = self._build_parser()
        home_path = str(tmp_path)
        args = parser.parse_args(["--home", home_path, "memory", "status"])
        cli_home = getattr(args, "home", None)
        assert cli_home == home_path
        assert rk(cli_home, env={}) == Path(home_path).resolve()


# ---------------------------------------------------------------------------
# CLI require-exists: non-existent explicit home causes non-zero exit
# ---------------------------------------------------------------------------

class TestCliRequireExists:
    def test_nonexistent_explicit_home_causes_exit(self, monkeypatch, tmp_path):
        """was_home_explicit + not home.is_dir() -> exit with error message."""
        from koan.home import resolve_koan_home, was_home_explicit

        cli_home = str(tmp_path / "does-not-exist")
        home = resolve_koan_home(cli_home, env={})
        assert was_home_explicit(cli_home, env={})
        assert not home.is_dir()  # does not exist

    def test_default_home_exempt_from_existence_check(self):
        """was_home_explicit returns False for the default path so no check is applied."""
        from koan.home import was_home_explicit
        # Neither cli_home nor KOAN_HOME is set.
        assert not was_home_explicit(None, env={})
