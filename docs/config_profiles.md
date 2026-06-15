# Config Profiles

Plato's Factory OS reads layered JSON configuration from `config/`. Profiles let you switch between development, continuous watch, and production-style defaults without changing code.

## Files

| File | Role |
|------|------|
| `config/defaults.json` | Baseline settings for all profiles |
| `config/profiles/dev.json` | Fast iteration: dry-run friendly, small limits |
| `config/profiles/continuous.json` | Watch + auto-fix oriented continuous operation |
| `config/profiles/production.json` | Conservative production defaults |
| `config/profiles/local.json` | Lightweight local override (same family as defaults) |

Loader: `modules/config_system.py` → `load_factory_config()`.

## Precedence

Settings are merged in this order (later wins):

1. `config/defaults.json`
2. `config/profiles/<profile>.json`
3. Environment variables (`PLATO_*`)
4. CLI overrides passed to `load_factory_config(profile, cli_overrides)`

**Summary:** `CLI > ENV > profile > defaults`

### Supported environment overrides

| Variable | Config path |
|----------|-------------|
| `PLATO_PROFILE` | profile name |
| `PLATO_WATCH_STABLE_SECONDS` | `watch.stable_seconds` |
| `PLATO_WATCH_POLL_INTERVAL` | `watch.poll_interval` |
| `PLATO_WATCH_MAX_FILES_PER_CYCLE` | `watch.max_files_per_cycle` |
| `PLATO_MIN_DISK_FREE_RATIO` | `resource_limits.min_disk_free_ratio` |

## Config Sections

### `paths`

Runtime directories (relative to repo root):

- `data_dir`, `queue_dir`, `history_dir`, `logs_dir`, `jobs_dir`, `watch_state_dir`

### `duration_policy`

Auto-QC duration guards:

- `min_duration`, `short_clip_min_duration`, `ultra_short_threshold`
- `max_duration_loss_ratio`, `allow_original_short`

### `watch`

Folder watcher behavior:

- `enabled`, `poll_interval`, `stable_seconds`, `max_files_per_cycle`, `recursive`

### `auto_fix`

Conservative ffmpeg auto-fix policy:

- `enabled`, `max_fixes_per_clip`, `min_improvement`, `target_verdict`

### `queue`

Queue engine limits:

- `max_retries`, `cleanup_days`

### `health`

Factory health thresholds:

- `min_free_disk_gb`, `queue_warning_size`, `queue_critical_size`

### `resource_limits`

Disk ratio guard used by orchestrator health checks:

- `min_disk_free_ratio`

## Profile Summaries

### `dev`

- `dry_run` defaults to `true` where applicable
- Shorter poll intervals and smaller per-cycle file limits
- Useful for safe local validation without processing videos

### `continuous`

- Watch and auto-fix enabled
- `allow_original_short: true` for short-form pipelines
- Conservative retry limits for queue stability

### `production`

- No destructive behavior; same safety guarantees as other profiles
- Longer stable/poll intervals and higher per-cycle limits
- Stricter disk free ratio

## Example Commands

One safe dry-run cycle with the dev profile:

```powershell
py tools\run_orchestrator.py --profile dev --once --dry-run
```

Continuous watch after detecting VideoAutoPipeline outputs:

```powershell
py tools\run_orchestrator.py --profile continuous --detect-videoautopipeline-outputs --watch
```

Load config in Python:

```python
from modules.config_system import load_factory_config

config = load_factory_config("dev", {"watch": {"max_files_per_cycle": 2}})
assert config["profile"] == "dev"
```

## Safety Notes

- Profiles do **not** bypass auto-fix safety rules or original-file protection.
- `dry_run` and orchestrator `--dry-run` prevent ffmpeg processing and result copying.
- Original MP4 files are never modified, moved, deleted, or overwritten regardless of profile.
