from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.orchestrator import OrchestratorConfig, START_COMMAND, VideoFactoryOrchestrator
from modules.videoautopipeline_detector import DEFAULT_VIDEOAUTOPIPELINE_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Plato Video Factory orchestrator.")
    parser.add_argument("--once", action="store_true", help="Run one orchestration cycle and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Discover/watch/enqueue only; do not process videos or call ffmpeg.")
    parser.add_argument("--status-only", action="store_true", help="Print current factory state and exit.")
    parser.add_argument("--recover", action="store_true", help="Run state recovery before starting.")
    parser.add_argument("--detect-videoautopipeline-outputs", action="store_true", help="Detect local VideoAutoPipeline output folders.")
    parser.add_argument("--videoautopipeline-root", default=str(DEFAULT_VIDEOAUTOPIPELINE_ROOT), help="VideoAutoPipeline project root used for detection.")
    parser.add_argument("--watch", action="store_true", help="Run the watch/queue scan for discovered sources.")
    parser.add_argument("--auto-fix", action="store_true", help="Accepted for operator workflow compatibility; dry-run mode never applies fixes.")
    parser.add_argument("--copy-results", action="store_true", help="Accepted for operator workflow compatibility; dry-run mode writes no result copies.")
    parser.add_argument("--allow-original-short", action="store_true", help="Allow original short clips in downstream auto-fix policy.")
    parser.add_argument("--short-clip-min-duration", type=float, default=5.0, help="Short-clip minimum duration for downstream auto-fix policy.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    orchestrator = VideoFactoryOrchestrator(
        OrchestratorConfig(
            detect_videoautopipeline_outputs=args.detect_videoautopipeline_outputs,
            videoautopipeline_root=Path(args.videoautopipeline_root),
            watch_enabled=args.watch or args.once or args.dry_run,
            dry_run=args.dry_run,
            auto_fix=args.auto_fix,
            copy_results=args.copy_results,
            allow_original_short=args.allow_original_short,
            short_clip_min_duration=args.short_clip_min_duration,
        )
    )
    payload = {"status": orchestrator.health()}
    if args.recover:
        payload["recovery"] = orchestrator.recover()
    if args.status_only:
        pass
    elif args.once:
        payload["cycle"] = orchestrator.run_once(dry_run=args.dry_run, watch=True)
    else:
        orchestrator.transition("ready", "orchestrator initialized")
        payload["status"] = orchestrator.health()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"orchestrator_state: {payload['status'].get('orchestrator_state')}")
        print(f"health_state: {payload['status'].get('health', {}).get('state')}")
        detection = payload["status"].get("detection")
        if detection:
            print(f"detector_found: {detection.get('found')}")
            if detection.get("recommended_input_folder"):
                print(f"recommended_input_folder: {detection.get('recommended_input_folder')}")
            else:
                print(detection.get("message") or "No VideoAutoPipeline output folder found.")
                print(f"Suggested next command: {START_COMMAND}")
        if payload.get("cycle"):
            print(f"cycle_state: {payload['cycle'].get('state')}")
            print(f"dry_run: {payload['cycle'].get('dry_run')}")
            watch = payload["cycle"].get("watch") or {}
            print(f"watch_sources: {len(watch.get('sources') or [])}")
            if watch.get("operator_message"):
                print(watch["operator_message"])
                print(f"Suggested next command: {watch.get('suggested_command')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
