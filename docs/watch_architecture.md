# Watch Architecture

v1.1.6 keeps one runtime path for watched MP4s:

```text
detect -> watch_engine -> watch_folder -> auto_qc -> auto_fix -> report
```

## Ownership

`modules/watch_folder.py`
- Resolves watch folders.
- Observes direct `.mp4` files.
- Tracks file signatures, stability, watch state, and watch logs.
- Copies ready originals into per-cycle staging folders.
- Never edits originals.
- Does not own auto-QC execution.

`modules/watch_engine.py`
- Owns watch lifecycle entrypoints: `run_watch` and `run_watch_cycle`.
- Supplies the auto-QC executor for staged files.
- Preserves output folder naming as `<base_output_dir>/<cycle_id>`.
- Preserves dry-run behavior by letting `watch_folder` mark ready files skipped without calling the executor.
- Drives discovered watch sources and optional queue enqueue.

`modules/orchestrator.py`
- Coordinates state, health, history, report snapshots, and watch engine calls.
- Does not decide auto-QC execution details.

`tools/watch_videoautopipeline_outputs.py`
- CLI entry only.
- Parses arguments, resolves the watch folder, builds `WatchOptions`, and calls `modules.watch_engine.run_watch`.

## Safety Rules

- Original MP4s are read/stat/copied only.
- Auto-QC receives staged copies, not source files.
- Dry-run never calls auto-QC.
- `--copy-results`, `--auto-fix`, short-clip options, batch limits, and output directory behavior pass through unchanged.
- Operator watch mode still launches `tools/watch_videoautopipeline_outputs.py` as a cancellable singleton job.
