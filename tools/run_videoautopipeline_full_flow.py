from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run VideoAutoPipeline, then process its outputs through Plato.")
    parser.add_argument("--vap-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--input-video", default="")
    parser.add_argument("--input-folder", default="")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--auto-fix", action="store_true")
    parser.add_argument("--copy-results", action="store_true")
    parser.add_argument("--send-telegram", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    vap_root = Path(args.vap_root)
    vap_app = vap_root / "app.py"
    if not vap_app.exists():
        print(f"VideoAutoPipeline app.py not found: {vap_app}", file=sys.stderr)
        return 2
    if not args.input_video and not args.input_folder:
        print("Provide --input-video or --input-folder.", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env.update({
        "SEND_MODE": "after_plato",
        "VAP_SEND_MODE": "after_plato",
        "VAP_OUTPUT_DIR": str(Path(args.output_root)),
        "VIDEOAUTOPIPELINE_ROOT": str(vap_root),
        "VIDEOAUTOPIPELINE_OUTPUT_ROOT": str(Path(args.output_root)),
    })

    vap_cmd = [sys.executable, str(vap_app), "--worker", args.input_video] if args.input_video else [sys.executable, str(vap_app), "--batch", args.input_folder]
    if args.input_folder and args.limit:
        vap_cmd.extend(["--limit", str(args.limit)])
    completed = subprocess.run(vap_cmd, cwd=vap_root, env=env, shell=False)
    if completed.returncode:
        return completed.returncode

    plato_cmd = [sys.executable, str(ROOT / "tools" / "process_videoautopipeline_outputs.py"), str(Path(args.output_root))]
    if args.auto_fix:
        plato_cmd.append("--auto-fix")
    if args.copy_results:
        plato_cmd.append("--copy-results")
    if args.dry_run:
        plato_cmd.append("--dry-run")
    if args.send_telegram:
        plato_cmd.append("--send-telegram")
    return subprocess.run(plato_cmd, cwd=ROOT, env=env, shell=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
