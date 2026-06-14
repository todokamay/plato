from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.videoautopipeline_detector import DEFAULT_VIDEOAUTOPIPELINE_ROOT
from modules.watch_folder import DEFAULT_STATE_FILE, WatchOptions, resolve_watch_folder, run_watch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch a folder for stable MP4 files and run Plato auto-QC.")
    parser.add_argument("input_folder", nargs="?", help="Folder containing VideoAutoPipeline MP4 outputs.")
    parser.add_argument("--detect-videoautopipeline-outputs", action="store_true", help="Auto-detect the recommended VideoAutoPipeline output folder.")
    parser.add_argument("--videoautopipeline-root", default=str(DEFAULT_VIDEOAUTOPIPELINE_ROOT), help="VideoAutoPipeline project root used for output detection.")
    parser.add_argument("--auto-fix", action="store_true", help="Apply safe deterministic ffmpeg fixes through the existing auto-QC pipeline.")
    parser.add_argument("--copy-results", action="store_true", help="Copy final originals/fixed clips into output bucket folders.")
    parser.add_argument("--once", action="store_true", help="Run one polling cycle and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Detect stable files but do not call auto-QC.")
    parser.add_argument("--poll-interval", type=float, default=10.0, help="Seconds between polling cycles.")
    parser.add_argument("--stable-seconds", type=float, default=5.0, help="Seconds a file's size and mtime must remain stable.")
    parser.add_argument("--max-files-per-cycle", type=int, default=10, help="Maximum stable files to process in one cycle.")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE), help="Persistent watch state JSON path.")
    parser.add_argument("--output-dir", help="Base output directory for auto-QC run artifacts.")
    parser.add_argument("--allow-original-short", action="store_true", help="Allow valid original short clips below the normal minimum duration.")
    parser.add_argument("--short-clip-min-duration", type=float, default=5.0, help="Minimum fixed duration when --allow-original-short applies.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        watch_folder, detection = resolve_watch_folder(
            args.input_folder,
            detect_videoautopipeline_outputs_enabled=args.detect_videoautopipeline_outputs,
            videoautopipeline_root=args.videoautopipeline_root,
        )
        options = WatchOptions(
            watch_folder=watch_folder,
            state_file=args.state_file,
            output_dir=args.output_dir,
            auto_fix=args.auto_fix,
            copy_results=args.copy_results,
            dry_run=args.dry_run,
            once=args.once,
            poll_interval=args.poll_interval,
            stable_seconds=args.stable_seconds,
            max_files_per_cycle=args.max_files_per_cycle,
            allow_original_short=args.allow_original_short,
            short_clip_min_duration=args.short_clip_min_duration,
        )
        cycles = run_watch(options)
    except KeyboardInterrupt:
        print("Watch stopped by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = {"ok": True, "watch_folder": str(watch_folder.resolve()), "detection": detection, "cycles": cycles}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if detection:
        print(f"detected_recommended_input_folder: {detection.get('recommended_input_folder')}")
    for cycle in cycles:
        print(
            "cycle: {cycle_id} detected={detected_count} stable={stable_count} "
            "processed={processed_count} skipped={skipped_count} failed={failed_count} run_id={auto_qc_run_id}".format(**cycle)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
