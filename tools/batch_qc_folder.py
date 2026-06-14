import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.batch_qc import run_batch_qc


def _print_text(payload: dict) -> None:
    counts = payload.get("counts", {})
    paths = payload.get("paths", {})
    print(f"Batch: {payload.get('batch_id')}")
    print(f"Input: {payload.get('input_folder')}")
    print(
        "Scanned: {scanned_count} | New: {new_count} | Skipped: {skipped_count} | "
        "Analyzed: {analyzed_count} | Failed: {failed_count}".format(**counts)
    )
    print(
        "Publish: {publish_candidate_count} | Safe Test: {safe_test_count} | "
        "Quick Fix: {quick_fix_count} | High Upside: {high_upside_rework_count} | "
        "Hold: {hold_count} | Reject: {reject_count}".format(**counts)
    )
    if paths:
        print("Outputs:")
        for key, value in paths.items():
            if key == "marker_paths":
                print(f"  {key}: {len(value)} marker file(s)")
            else:
                print(f"  {key}: {value}")
    else:
        print("Dry run: no output files written.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batch QC ready video clips exported by VideoAutoPipeline.")
    parser.add_argument("folder", help="Folder containing ready MP4/MOV/MKV/WebM clips.")
    parser.add_argument("--force", action="store_true", help="Re-analyze already analyzed clips.")
    parser.add_argument("--recursive", action="store_true", help="Scan subfolders too.")
    parser.add_argument("--copy-results", action="store_true", help="Copy clips into result bucket folders.")
    parser.add_argument("--output-dir", help="Output directory. Defaults to data/qc_results/batch_YYYYMMDD_HHMMSS.")
    parser.add_argument("--limit", type=int, help="Analyze only first N clips.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without analysis/copy/export.")
    args = parser.parse_args(argv)

    try:
        payload = run_batch_qc(
            args.folder,
            force=args.force,
            recursive=args.recursive,
            copy_results=args.copy_results,
            output_dir=args.output_dir,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        fallback = r"py tools\batch_qc_folder.py PATH --dry-run"
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc), "suggested_command": fallback}, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
            print(f"Suggested next command: {fallback}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload)
        if (payload.get("counts") or {}).get("scanned_count") == 0:
            print("No MP4/MOV/MKV/WebM files found. Try --recursive or point to the export folder.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
