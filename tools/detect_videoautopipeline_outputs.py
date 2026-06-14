from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.videoautopipeline_detector import DEFAULT_VIDEOAUTOPIPELINE_ROOT, detect_videoautopipeline_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect likely VideoAutoPipeline MP4 output folders.")
    parser.add_argument("--root", default=str(DEFAULT_VIDEOAUTOPIPELINE_ROOT), help="VideoAutoPipeline project root.")
    parser.add_argument("--depth", type=int, default=4, help="Recursive folder depth limit under the root.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = detect_videoautopipeline_outputs(args.root, depth_limit=args.depth)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"root: {result.get('root')}")
    print(f"found: {result.get('found')}")
    if result.get("recommended_input_folder"):
        print(f"recommended_input_folder: {result['recommended_input_folder']}")
    print()

    candidates = result.get("candidates") or []
    if candidates:
        print("candidates:")
        for index, candidate in enumerate(candidates, start=1):
            print(f"{index}. {candidate['folder_path']}")
            print(f"   mp4_count: {candidate['mp4_count']}")
            print(f"   newest_modification_time: {candidate['newest_modification_time']}")
            print(f"   total_size_bytes: {candidate['total_size_bytes']}")
            print(f"   sample_filenames: {', '.join(candidate['sample_filenames'])}")
        return 0

    print(result.get("message") or "No VideoAutoPipeline output folders found.")
    print("Fallback command:")
    print(r'py tools\auto_qc_fix_folder.py data\temp\manual_videoautopipeline_outputs --auto-fix --copy-results --limit 5 --allow-original-short --short-clip-min-duration 5')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
