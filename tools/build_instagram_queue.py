from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.instagram_queue import QUEUE_FILE, build_queue_item, enqueue, export_summary, load_queue
from modules.videoautopipeline_contract import default_delivery_root


def _load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _delivery_rows(payload: dict) -> list[dict]:
    jobs = payload.get("jobs")
    if isinstance(jobs, list):
        return [row for row in jobs if isinstance(row, dict)]
    return [payload] if isinstance(payload, dict) else []


def build_from_delivery(
    delivery_summary: str | Path,
    *,
    dry_run: bool = False,
    force: bool = False,
    queue_file: str | Path = QUEUE_FILE,
    allow_safe_to_test: bool | None = None,
) -> dict:
    payload = _load_json(delivery_summary)
    queued = []
    skipped = []
    existing_paths = {
        str(item.get("approved_output_path") or "").strip().lower()
        for item in load_queue(queue_file).get("items", [])
    }
    for row in _delivery_rows(payload):
        item, reason = build_queue_item(row, allow_safe_to_test=allow_safe_to_test)
        label = row.get("job_id") or row.get("approved_output_path") or row.get("source_final_path") or "unknown"
        if not item:
            skipped.append({"job_id": str(label), "reason": reason})
            continue
        key = str(item.get("approved_output_path") or "").strip().lower()
        if dry_run:
            action = "would_queue" if force or key not in existing_paths else "duplicate"
            queued.append({**item, "action": action})
            continue
        stored, created = enqueue(item, queue_file=queue_file, force=force)
        if created:
            queued.append(stored)
        else:
            skipped.append({"job_id": str(item.get("job_id") or label), "reason": "duplicate"})
    stats = {"queued": len(queued), "skipped": len(skipped), "reasons": skipped, "items": queued, "dry_run": bool(dry_run)}
    if not dry_run:
        stats["queue_summary"] = export_summary(queue_file=queue_file)
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Plato Instagram queue from delivery_summary.json.")
    parser.add_argument("delivery_summary", nargs="?", default=str(default_delivery_root() / "delivery_summary.json"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = build_from_delivery(args.delivery_summary, dry_run=args.dry_run, force=args.force)
    except Exception as exc:
        result = {"ok": False, "error": str(exc), "queued": 0, "skipped": 0, "reasons": [], "dry_run": bool(args.dry_run)}
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"error: {exc}")
        return 1
    result["ok"] = True
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"queued={result['queued']} skipped={result['skipped']} dry_run={result['dry_run']}")
        for item in result["reasons"]:
            print(f"skipped {item['job_id']}: {item['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
