import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.config_system import DEFAULTS_PATH, PROFILES_DIR, load_factory_config

REQUIRED_SECTIONS = [
    "paths",
    "duration_policy",
    "watch",
    "auto_fix",
    "queue",
    "health",
]

PATH_KEYS = [
    "data_dir",
    "queue_dir",
    "history_dir",
    "logs_dir",
    "jobs_dir",
    "watch_state_dir",
]

DURATION_KEYS = [
    "min_duration",
    "short_clip_min_duration",
    "ultra_short_threshold",
    "max_duration_loss_ratio",
    "allow_original_short",
]

WATCH_KEYS = ["poll_interval", "stable_seconds", "max_files_per_cycle", "recursive"]
AUTO_FIX_KEYS = ["enabled", "max_fixes_per_clip", "min_improvement", "target_verdict"]
QUEUE_KEYS = ["max_retries", "cleanup_days"]
HEALTH_KEYS = ["min_free_disk_gb", "queue_warning_size", "queue_critical_size"]


def _assert_section_keys(config: dict, section: str, keys: list[str]) -> None:
    block = config.get(section)
    assert isinstance(block, dict), f"missing section: {section}"
    for key in keys:
        assert key in block, f"{section} missing key: {key}"


def main() -> int:
    assert DEFAULTS_PATH.exists(), "config/defaults.json must exist"
    defaults = json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))
    assert isinstance(defaults, dict)

    for section in REQUIRED_SECTIONS:
        assert section in defaults, f"defaults.json missing section: {section}"
    _assert_section_keys(defaults, "paths", PATH_KEYS)
    _assert_section_keys(defaults, "duration_policy", DURATION_KEYS)
    _assert_section_keys(defaults, "watch", WATCH_KEYS)
    _assert_section_keys(defaults, "auto_fix", AUTO_FIX_KEYS)
    _assert_section_keys(defaults, "queue", QUEUE_KEYS)
    _assert_section_keys(defaults, "health", HEALTH_KEYS)

    for profile in ("dev", "continuous", "production"):
        path = PROFILES_DIR / f"{profile}.json"
        assert path.exists(), f"missing profile: {path}"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("profile") == profile

    dev = load_factory_config("dev")
    assert dev["profile"] == "dev"
    assert dev["dry_run"] is True
    assert dev["watch"]["max_files_per_cycle"] == 3

    continuous = load_factory_config("continuous")
    assert continuous["auto_fix"]["enabled"] is True
    assert continuous["duration_policy"]["allow_original_short"] is True

    production = load_factory_config("production")
    assert production["resource_limits"]["min_disk_free_ratio"] == 0.1

    merged = load_factory_config("dev", {"watch": {"max_files_per_cycle": 1}})
    assert merged["watch"]["max_files_per_cycle"] == 1

    print("test_config_profiles: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
