from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

from config import project_path


CONFIG_DIR = project_path("config")
DEFAULTS_PATH = CONFIG_DIR / "defaults.json"
PROFILES_DIR = CONFIG_DIR / "profiles"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _env_overrides(prefix: str = "PLATO_") -> dict:
    output: dict = {}
    mapping = {
        f"{prefix}PROFILE": ("profile", str),
        f"{prefix}WATCH_STABLE_SECONDS": ("watch.stable_seconds", float),
        f"{prefix}WATCH_POLL_INTERVAL": ("watch.poll_interval", float),
        f"{prefix}WATCH_MAX_FILES_PER_CYCLE": ("watch.max_files_per_cycle", int),
        f"{prefix}MIN_DISK_FREE_RATIO": ("resource_limits.min_disk_free_ratio", float),
    }
    for env_name, (path, caster) in mapping.items():
        if env_name not in os.environ:
            continue
        cursor = output
        parts = path.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = caster(os.environ[env_name])
    return output


def load_factory_config(profile: str | None = None, cli_overrides: dict | None = None) -> dict:
    defaults = _load_json(DEFAULTS_PATH)
    selected_profile = profile or os.environ.get("PLATO_PROFILE") or defaults.get("profile") or "local"
    profile_data = _load_json(PROFILES_DIR / f"{selected_profile}.json")
    env_data = _env_overrides()
    cli_data = cli_overrides or {}
    config = _merge(defaults, profile_data)
    config = _merge(config, env_data)
    config = _merge(config, cli_data)
    config["profile"] = config.get("profile") or selected_profile
    return config
