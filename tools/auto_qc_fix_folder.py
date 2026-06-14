from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.auto_qc import run_auto_qc_fix


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Plato automated QC and conservative ffmpeg auto-fixes for a folder.")
    parser.add_argument("input_folder", help="Folder containing MP4/MOV/MKV/WebM clips.")
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
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--keep-temp", action="store_true", help="Keep intermediate segment files for debugging.")
    parser.add_argument("--no-copy-original-rejects", action="store_true", help="Do not copy rejected original files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = run_auto_qc_fix(
            args.input_folder,
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
            keep_temp=args.keep_temp,
            no_copy_original_rejects=args.no_copy_original_rejects,
        )
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
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
    if paths:
        print("outputs:")
        for key in ["run_summary_json", "run_summary_csv", "run_report_html", "run_fix_plan_csv", "run_fix_plan_json", "auto_fix_log"]:
            print(f"  {key}: {paths.get(key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
