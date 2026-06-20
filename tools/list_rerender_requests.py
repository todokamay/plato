from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.rerender_requests import get_rerender_stats, list_rerender_requests


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List Plato rerender requests.")
    parser.add_argument("--status", default="requested", help="requested, accepted, completed, failed, skipped, or all")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    items = list_rerender_requests(args.status)
    payload = {"ok": True, "status": args.status, "count": len(items), "stats": get_rerender_stats(), "items": items}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"Rerender requests: {len(items)}")
    for item in items[:20]:
        changes = ", ".join(item.get("requested_changes") or [])
        print(f"{item.get('request_id')}  {item.get('job_id')}  {item.get('blocker_type')}  {changes}  {item.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
