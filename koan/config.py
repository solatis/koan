# KoanConfig dataclass and config file loader/saver.
# Storage: ~/.koan/config.json -- mirrors src/planner/model-config.ts.

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .types import AgentInstallation, Profile, ProfileTier

log = logging.getLogger("koan.config")

CONFIG_PATH = Path.home() / ".koan" / "config.json"


@dataclass
class KoanConfig:
    agent_installations: list[AgentInstallation] = field(default_factory=list)
    profiles: list[Profile] = field(default_factory=list)
    active_profile: str = "balanced"
    scout_concurrency: int = 8


# -- Write lock (lazily initialized) ------------------------------------------

_config_write_lock: asyncio.Lock | None = None


def _get_write_lock() -> asyncio.Lock:
    global _config_write_lock
    if _config_write_lock is None:
        _config_write_lock = asyncio.Lock()
    return _config_write_lock


# -- Parsers -------------------------------------------------------------------

def _parse_agent_installations(raw: list) -> list[AgentInstallation]:
    results: list[AgentInstallation] = []
    if not isinstance(raw, list):
        return results
    for entry in raw:
        if not isinstance(entry, dict):
            log.warning("agentInstallations entry is not an object; skipping.")
            continue
        alias = entry.get("alias", "")
        runner_type = entry.get("runnerType", "")
        binary = entry.get("binary", "")
        if not alias or not runner_type or not binary:
            log.warning("agentInstallations entry missing alias/runnerType/binary; skipping.")
            continue
        extra_args = entry.get("extraArgs", [])
        if not isinstance(extra_args, list):
            extra_args = []
        results.append(AgentInstallation(
            alias=alias,
            runner_type=runner_type,
            binary=binary,
            extra_args=[str(a) for a in extra_args],
        ))
    return results


def _parse_profiles(raw: list) -> list[Profile]:
    results: list[Profile] = []
    if not isinstance(raw, list):
        return results
    for entry in raw:
        if not isinstance(entry, dict):
            log.warning("profiles entry is not an object; skipping.")
            continue
        name = entry.get("name", "")
        if not name:
            log.warning("profiles entry missing name; skipping.")
            continue
        tiers_raw = entry.get("tiers", {})
        if not isinstance(tiers_raw, dict):
            log.warning("profiles[%s].tiers is not an object; skipping.", name)
            continue
        tiers: dict[str, ProfileTier] = {}
        for tier_name, tier_val in tiers_raw.items():
            if not isinstance(tier_val, dict):
                log.warning("profiles[%s].tiers[%s] is not an object; skipping tier.", name, tier_name)
                continue
            rt = tier_val.get("runnerType", "")
            model = tier_val.get("model", "")
            thinking = tier_val.get("thinking", "disabled")
            if not rt or not model:
                log.warning("profiles[%s].tiers[%s] missing runnerType/model; skipping tier.", name, tier_name)
                continue
            tiers[tier_name] = ProfileTier(runner_type=rt, model=model, thinking=thinking)
        results.append(Profile(name=name, tiers=tiers))
    return results


def _parse_scout_concurrency(raw: dict) -> int:
    if not isinstance(raw, dict):
        return 8
    sc = raw.get("scoutConcurrency")
    if isinstance(sc, bool):
        return 8
    if isinstance(sc, int) and sc > 0:
        return sc
    return 8


# -- Loaders / savers ---------------------------------------------------------

async def load_koan_config() -> KoanConfig:
    defaults = KoanConfig()

    try:
        text = CONFIG_PATH.read_text("utf-8")
    except FileNotFoundError:
        return defaults

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        log.warning("config.json is not valid JSON; treating config as absent.")
        return defaults

    if not isinstance(parsed, dict):
        log.warning("config.json top-level value is not an object; treating config as absent.")
        return defaults

    active_profile = parsed.get("activeProfile", "balanced")
    if not isinstance(active_profile, str) or not active_profile:
        active_profile = "balanced"

    # Exclude "balanced" from persisted profiles -- it is recomputed at startup
    profiles = [p for p in _parse_profiles(parsed.get("profiles", [])) if p.name != "balanced"]

    return KoanConfig(
        agent_installations=_parse_agent_installations(parsed.get("agentInstallations", [])),
        profiles=profiles,
        active_profile=active_profile,
        scout_concurrency=_parse_scout_concurrency(parsed),
    )


async def save_koan_config(config: KoanConfig) -> None:
    async with _get_write_lock():
        config_dir = CONFIG_PATH.parent
        config_dir.mkdir(parents=True, exist_ok=True)

        existing: dict = {}
        try:
            existing = json.loads(CONFIG_PATH.read_text("utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        # Remove legacy keys
        existing.pop("modelTiers", None)
        existing.pop("activeInstallations", None)

        # Serialize agent_installations
        existing["agentInstallations"] = [
            {
                "alias": inst.alias,
                "runnerType": inst.runner_type,
                "binary": inst.binary,
                "extraArgs": inst.extra_args,
            }
            for inst in config.agent_installations
        ]

        # Serialize active_profile (omit if default)
        if config.active_profile != "balanced":
            existing["activeProfile"] = config.active_profile
        else:
            existing.pop("activeProfile", None)

        # Serialize profiles (user-defined only; balanced never persisted)
        existing["profiles"] = [
            {
                "name": p.name,
                "tiers": {
                    tier_name: {
                        "runnerType": pt.runner_type,
                        "model": pt.model,
                        "thinking": pt.thinking,
                    }
                    for tier_name, pt in p.tiers.items()
                },
            }
            for p in config.profiles
            if p.name != "balanced"
        ]

        existing["scoutConcurrency"] = config.scout_concurrency

        tmp_path = CONFIG_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(existing, indent=2) + "\n", "utf-8")
        tmp_path.rename(CONFIG_PATH)
