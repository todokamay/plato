from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.rerender_requests import mark_request_status


def _read_json(path: str | Path) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid_status_json: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid_status_json: expected object")
    return payload


def import_result(status_path: str | Path) -> dict:
    path = Path(status_path).resolve()
    status = _read_json(path)
    request_id = str(status.get("request_id") or "")
    if not request_id:
        return {"ok": False, "status": "failed", "error": "missing_request_id"}

    state = str(status.get("status") or "").lower()
    output = str(status.get("rerendered_output_path") or "")
    updates = {
        "rerender_status_path": str(path),
        "rerendered_output_path": output,
        "rerender_error": str(status.get("error") or ""),
    }
    if state == "completed" and output and Path(output).exists() and Path(output).is_file():
        result = mark_request_status(request_id, "completed", "rerender completed", updates=updates)
    elif state == "failed":
        result = mark_request_status(request_id, "failed", str(status.get("error") or "rerender failed"), updates=updates)
    else:
        updates["rerender_error"] = updates["rerender_error"] or "rerendered_output_missing"
        result = mark_request_status(request_id, "failed", updates["rerender_error"], updates=updates)
    return {**result, "imported_status": state}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import a VideoAutoPipeline rerender result into Plato.")
    parser.add_argument("status_json", help="Path to VAP rerender status JSON.")
    args = parser.parse_args(argv)
    result = import_result(args.status_json)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
