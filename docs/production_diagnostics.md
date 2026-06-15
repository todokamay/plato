# Production Diagnostics

Production diagnostics explain what happened during real Plato runs without changing scoring, routing, auto-fix, or Safe Replace behavior.

## Export Diagnostics

```powershell
py tools\export_production_diagnostics.py
py tools\export_production_diagnostics.py --json
py tools\export_production_diagnostics.py --output-dir data\diagnostics
```

Exports are written to:

```text
data\diagnostics\diagnostics_YYYYMMDD_HHMMSS\
```

Files:

- `diagnostics.json`
- `diagnostics_summary.txt`

## Included

- latest Auto QC run summary
- latest Batch QC run summary
- Safe Replace diagnostics
- queue summary
- job summary
- health summary
- watch state summary
- dead-code quarantine summary
- repo safety summary
- recent logs/events
- generated report paths
- operator recommendations

## Excluded

- MP4/MOV/AVI/MKV/WebM files
- SQLite databases
- secrets, tokens, passwords, and API keys

Media and database paths are redacted in the diagnostics JSON.

## Explain A Clip Decision

```powershell
py tools\explain_clip_decision.py data\auto_qc_runs\run_YYYYMMDD_HHMMSS\run_summary.json --clip FILENAME
py tools\explain_clip_decision.py data\auto_qc_runs\run_YYYYMMDD_HHMMSS\run_summary.json --clip FILENAME --json
```

The explainer uses existing result fields only:

- verdict and bucket
- original and fixed scores
- fix attempted/accepted status
- Safe Replace status
- acceptance/rejection/duration reasons
- recommendations already present in the row

It does not invent a new score or change the verdict.

## Safe Replace Relationship

Diagnostics include Safe Replace status and rollback availability from `replace_log.json`.

If backups are missing, diagnostics marks rollback unavailable and recommends resolving missing backups before rollback.
