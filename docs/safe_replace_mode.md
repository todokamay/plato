# Safe Replace Mode

Safe Replace Mode is optional. Default Auto QC remains copy-only: fixed clips are written as new files and originals are not overwritten.

Use replace mode only when an accepted fixed MP4 should become the working original for the selected folder.

## CLI

```powershell
py tools\auto_qc_fix_folder.py SELECTED_FOLDER --auto-fix --copy-results --allow-original-short --replace-with-fixed --confirm-replace --backup-dir data\replace_backups
```

Rollback:

```powershell
py tools\auto_qc_fix_folder.py --rollback-replace-log data\auto_qc_runs\run_YYYYMMDD_HHMMSS\logs\replace_log.json
```

Diagnostics:

```powershell
py tools\replace_diagnostics.py
py tools\replace_diagnostics.py --json
py tools\replace_diagnostics.py --log data\auto_qc_runs\run_YYYYMMDD_HHMMSS\logs\replace_log.json
```

## UI Workflow

Open:

```text
http://127.0.0.1:8000/operator
```

In Safe Replace Mode:

1. Select the input folder.
2. Check `Enable Safe Replace Mode`.
3. Check `I understand originals may be replaced after backup`.
4. Enter a backup directory.
5. Run `Run Auto QC Once with Safe Replace`.

Rollback uses the latest `replace_log.json` path shown in the operator UI, or a manually entered log path.

## Safety Guarantees

- Replace mode is off by default.
- Both CLI flags are required: `--replace-with-fixed` and `--confirm-replace`.
- Both UI checkboxes are required.
- Only accepted fixed `.mp4` clips can replace originals.
- The fixed file must pass `ffprobe`.
- A backup is copied before replacement.
- If backup creation fails, no replacement happens.
- If `ffprobe` fails, no replacement happens.
- Rejected/unaccepted fixed clips are skipped.
- Each replace run writes `logs/replace_log.json`.

## Risks

Do not use replace mode on irreplaceable source folders without backups.

Keep backup directories outside the selected input folder so future scans do not reprocess backup clips.
