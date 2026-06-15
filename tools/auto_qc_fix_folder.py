from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.auto_qc import rollback_replace_log, run_auto_qc_fix
from modules.videoautopipeline_detector import DEFAULT_VIDEOAUTOPIPELINE_ROOT, detect_videoautopipeline_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Plato automated QC and conservative ffmpeg auto-fixes for a folder.")
    parser.add_argument("input_folder", nargs="?", help="Folder containing MP4/MOV/MKV/WebM clips.")
    parser.add_argument("--detect-videoautopipeline-outputs", action="store_true", help="Detect and use the recommended VideoAutoPipeline output folder when input_folder is omitted.")
    parser.add_argument("--videoautopipeline-root", default=str(DEFAULT_VIDEOAUTOPIPELINE_ROOT), help="VideoAutoPipeline project root used for output detection.")
    parser.add_argument("--auto-fix", action="store_true", help="Apply safe deterministic ffmpeg fixes.")
    parser.add_argument("--dry-run", action="store_true", help="Scan only; do not analyze, fix, copy, or write outputs.")
    parser.add_argument("--force", action="store_true", help="Re-analyze existing clips.")
    parser.add_argument("--recursive", action="store_true", help="Scan subfolders.")
    parser.add_argument("--copy-results", action="store_true", help="Copy final originals/fixed clips into output bucket folders.")
    parser.add_argument("--output-dir", help="Output run directory.")
    parser.add_argument("--limit", type=int, help="Process only first N files.")
    parser.add_argument("--max-fixes-per-clip", type=int, default=3, help="Maximum safe fixes to apply per clip.")
    parser.add_argument("--min-improvement", type=float, default=2.0, help="Minimum adjusted-score improvement required.")
    parser.add_argument("--target-verdict", default="SAFE TO TEST", help="Target final verdict for accepting fixed output.")
    parser.add_argument("--min-duration", type=float, default=8.0, help="Normal minimum fixed duration in seconds.")
    parser.add_argument("--short-clip-min-duration", type=float, default=5.0, help="Minimum fixed duration when --allow-original-short applies.")
    parser.add_argument("--ultra-short-threshold", type=float, default=8.0, help="Original clips below this threshold may use the short-clip duration policy.")
    parser.add_argument("--max-duration-loss-ratio", type=float, default=0.15, help="Maximum allowed fixed-duration loss ratio.")
    parser.add_argument("--allow-original-short", action="store_true", help="Allow valid original short clips to remain below --min-duration after fixing.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--keep-temp", action="store_true", help="Keep intermediate segment files for debugging.")
    parser.add_argument("--no-copy-original-rejects", action="store_true", help="Do not copy rejected original files.")
    parser.add_argument("--replace-with-fixed", action="store_true", help="Replace accepted original MP4s with their accepted fixed MP4s.")
    parser.add_argument("--confirm-replace", action="store_true", help="Required with --replace-with-fixed before originals can be overwritten.")
    parser.add_argument("--backup-dir", help="Backup directory used before replacing originals.")
    parser.add_argument("--rollback-replace-log", help="Restore originals from a previous replace_log.json and exit.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_folder = args.input_folder
    detection = None

    if args.rollback_replace_log:
        try:
            payload = rollback_replace_log(args.rollback_replace_log)
        except Exception as exc:
            if args.json:
                print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
            else:
                print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"restored_count: {payload.get('restored_count')}")
            print(f"failed_count: {payload.get('failed_count')}")
        return 0 if payload.get("ok") else 1

    if not input_folder and args.detect_videoautopipeline_outputs:
        detection = detect_videoautopipeline_outputs(args.videoautopipeline_root)
        input_folder = detection.get("recommended_input_folder") or None
        if not input_folder:
            fallback = (
                r'py tools\auto_qc_fix_folder.py data\temp\manual_videoautopipeline_outputs '
                r'--auto-fix --copy-results --limit 5 --allow-original-short --short-clip-min-duration 5'
            )
            if args.json:
                print(json.dumps({"ok": False, "error": "No VideoAutoPipeline MP4 output folders found.", "detection": detection, "fallback_command": fallback}, ensure_ascii=False, indent=2))
            else:
                print("No VideoAutoPipeline MP4 output folders found.")
                print("Fallback command:")
                print(fallback)
            return 1
    elif not input_folder:
        print("ERROR: input_folder is required unless --detect-videoautopipeline-outputs is used.", file=sys.stderr)
        print(r"Suggested next command: py tools\auto_qc_fix_folder.py PATH --dry-run", file=sys.stderr)
        return 1

    try:
        payload = run_auto_qc_fix(
            input_folder,
            auto_fix=args.auto_fix,
            dry_run=args.dry_run,
            force=args.force,
            recursive=args.recursive,
            copy_results=args.copy_results,
            output_dir=args.output_dir,
            limit=args.limit,
            max_fixes_per_clip=args.max_fixes_per_clip,
            min_improvement=args.min_improvement,
            target_verdict=args.target_verdict,
            min_duration=args.min_duration,
            short_clip_min_duration=args.short_clip_min_duration,
            ultra_short_threshold=args.ultra_short_threshold,
            max_duration_loss_ratio=args.max_duration_loss_ratio,
            allow_original_short=args.allow_original_short,
            keep_temp=args.keep_temp,
            no_copy_original_rejects=args.no_copy_original_rejects,
            replace_with_fixed=args.replace_with_fixed,
            confirm_replace=args.confirm_replace,
            backup_dir=args.backup_dir,
        )
        if detection is not None:
            payload["detected_videoautopipeline_outputs"] = detection
    except Exception as exc:
        fallback = r"py tools\auto_qc_fix_folder.py PATH --dry-run"
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc), "suggested_command": fallback}, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
            print(f"Suggested next command: {fallback}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    counts = payload.get("counts") or {}
    paths = payload.get("paths") or {}
    print(f"run_id: {payload.get('run_id')}")
    print(f"scanned_count: {counts.get('scanned_count')}")
    print(f"analyzed_count: {counts.get('analyzed_count')}")
    print(f"auto_fix_allowed_count: {counts.get('auto_fix_allowed_count')}")
    print(f"auto_fix_attempted_count: {counts.get('auto_fix_attempted_count')}")
    print(f"accepted_fix_count: {counts.get('accepted_fix_count')}")
    print(f"rejected_fix_count: {counts.get('rejected_fix_count')}")
    print(f"failed_count: {counts.get('failed_count')}")
    if counts.get("scanned_count") == 0:
        print("No MP4/MOV/MKV/WebM files found. Try --recursive or point to the export folder.")
    if detection is not None:
        print(f"detected_recommended_input_folder: {detection.get('recommended_input_folder')}")
    if paths:
        print("outputs:")
        for key in ["run_summary_json", "run_summary_csv", "run_report_html", "run_fix_plan_csv", "run_fix_plan_json", "auto_fix_log", "replace_log_json"]:
            if key in paths:
                print(f"  {key}: {paths.get(key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
