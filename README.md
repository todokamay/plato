# Plato Video Lab

Deterministic local toolkit for short-form video QC, ranking, reporting, conservative auto-fix, and local Factory OS orchestration.

Plato Video Lab is built for a local workflow where ready MP4 clips are analyzed after export, sorted by publishing readiness, and optionally passed through safe ffmpeg fixes. It does not use ML, OCR, Whisper, OpenAI/Ollama/VLM calls, cloud services, or auto-publishing.

## UI

Run the FastAPI app:

```powershell
py tools\init_db.py
py app.py
```

Open:

- `http://127.0.0.1:8000/` dashboard
- `http://127.0.0.1:8000/control-center` Factory OS Control Center
- `http://127.0.0.1:8000/upload` upload/analyze workflow
- `http://127.0.0.1:8000/clips` clip list
- `http://127.0.0.1:8000/batch-qc` latest batch QC dashboard
- `http://127.0.0.1:8000/auto-qc` latest automated QC/auto-fix dashboard

## Factory OS Quick Start

Check current state without running work:

```powershell
py tools\run_orchestrator.py --status-only
```

Run one safe dry-run scan. This does not call ffmpeg, does not process videos, and does not modify originals:

```powershell
py tools\run_orchestrator.py --once --dry-run
```

Run continuous operator mode after VideoAutoPipeline outputs are detected:

```powershell
py tools\run_orchestrator.py ^
--detect-videoautopipeline-outputs ^
--watch ^
--auto-fix ^
--copy-results ^
--allow-original-short ^
--short-clip-min-duration 5
```

Smoke-check the local Factory OS:

```powershell
py tools\smoke_factory_run.py --skip-tests
```

## CLI Tools

Single clip analysis:

```powershell
py tools\analyze_clip.py path\to\video.mp4
```

Batch QC for a folder:

```powershell
py tools\batch_qc_folder.py "C:\Users\User\Desktop\Work\VideoAutoPipeline\outputs" --copy-results
```

Automated QC with conservative ffmpeg fixes:

```powershell
py tools\auto_qc_fix_folder.py "C:\Users\User\Desktop\Work\VideoAutoPipeline\outputs" --auto-fix --copy-results
```

Run tests:

```powershell
py tools\run_tests.py
py tools\run_full_validation.py
```

## Current v1.0.1 Capabilities

- FastAPI + Jinja local web UI.
- Factory OS Control Center at `/control-center`.
- Orchestrator status, dry-run, watch/queue scan, recovery hooks, and health checks.
- Persistent watch, queue, history, event, report, and log state under `data/`.
- SQLite-backed local clip/report storage.
- ffprobe metadata, frame sampling, OpenCV visual analysis, deterministic audio analysis, opening analysis, retention/rhythm metrics, and active-content heuristics.
- Deterministic score consistency layer with raw score, adjusted score, cap verdict, adjusted-score verdict, canonical final verdict, verdict source, and alignment labels.
- Deterministic edit-point timeline with priorities, timestamps, expected formula lift, detected-by sources, and recommended edits.
- Batch QC folder scanning with skip-by-identity, `--force`, `--recursive`, `--limit`, `--dry-run`, CSV/JSON/HTML summaries, and optional result copying.
- Portfolio buckets: `Publish Candidate`, `Safe Test`, `Quick Fix`, `High Upside Rework`, `Hold / Source Material`, and `Reject`.
- DaVinci marker CSV and fix-plan CSV/JSON export for manual editing workflows.
- Auto-QC pipeline that plans safe deterministic fixes, applies optional ffmpeg auto-fixes, re-analyzes fixed MP4 copies, compares before/after, and routes final outputs.
- Auto-QC output buckets: `publish_ready`, `safe_to_test`, `fixed_publish_ready`, `fixed_safe_to_test`, `rejected`, `failed_fix`, `hold_source`, and `debug_review`.

## Safety Guarantees

- No destructive editing.
- Optional conservative ffmpeg auto-fix exists, originals are never modified.
- Original files are not moved, deleted, or overwritten.
- Fixed outputs are written as new MP4 files under run output folders.
- Result folders receive copies only when `--copy-results` is used.
- No DaVinci Resolve automation or scripting in v1.0.1.
- No auto-publishing.
- No virality prediction; scores and lifts are deterministic formula estimates, not historical performance forecasts.

## Reports And Outputs

Single-clip reports are written to `data/reports`.

Batch QC runs are written to:

```text
data/qc_results/batch_YYYYMMDD_HHMMSS/
```

Auto-QC runs are written to:

```text
data/auto_qc_runs/run_YYYYMMDD_HHMMSS/
```

Factory OS runtime state is written to:

```text
data/queue/
data/history/
data/events/
data/logs/
data/watch_state/
data/report_center/
data/routed/
data/archive/
```

Runtime data, generated reports, SQLite files, logs, video files, and Python caches are ignored by Git.

## Limits

- Active-content detection is heuristic and deterministic.
- Credits-like/static text-card detection is heuristic.
- DaVinci exports are marker/fix-plan files only; they do not control Resolve.
- Auto-fix is intentionally conservative and limited to safe ffmpeg operations such as re-export, audio normalization/boost, short opening trims, ending trims, and short high-confidence segment removals.
