from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.orchestrator import VideoFactoryOrchestrator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Plato Video Factory orchestrator.")
    parser.add_argument("--once", action="store_true", help="Run one orchestration cycle and exit.")
    parser.add_argument("--recover", action="store_true", help="Run state recovery before starting.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    orchestrator = VideoFactoryOrchestrator()
    payload = {"status": orchestrator.health()}
    if args.recover:
        payload["recovery"] = orchestrator.recover()
    if args.once:
        payload["cycle"] = orchestrator.run_once()
    else:
        orchestrator.transition("ready", "orchestrator initialized")
        payload["status"] = orchestrator.health()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"orchestrator_state: {payload['status'].get('orchestrator_state')}")
        print(f"health_state: {payload['status'].get('health', {}).get('state')}")
        if payload.get("cycle"):
            print(f"cycle_state: {payload['cycle'].get('state')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
