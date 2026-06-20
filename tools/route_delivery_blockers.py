from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.blocker_router import classify_blockers
from modules.delivery_decision_explainer import explain_delivery_row
from modules.rerender_requests import build_rerender_request


def _read_json(path: str | Path) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def build_routes(delivery_summary: str | Path) -> dict:
    path = Path(delivery_summary)
    payload = _read_json(path)
    routes = []
    for row in payload.get("jobs") or []:
        if not isinstance(row, dict):
            continue
        explanation = explain_delivery_row(row, path)
        route = classify_blockers(explanation, row)
        preview = build_rerender_request(row, route)
        routes.append({
            "job_id": row.get("job_id") or "",
            "delivery_status": row.get("delivery_status") or "",
            "plato_verdict": row.get("plato_verdict") or "",
            "rerender_request_preview": preview,
            **route,
        })
    return {"count": len(routes), "routes": routes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route blocked Plato deliveries to the safest next action.")
    parser.add_argument("delivery_summary", help="Path to delivery_summary.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_routes(args.delivery_summary)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for route in result["routes"]:
            print(f"{route['job_id']}: {route['route']} - {route['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
