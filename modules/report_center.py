from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import project_path
from modules.auto_qc import recent_auto_qc_runs
from modules.history_engine import history_summary
from modules.queue_engine import queue_stats


DEFAULT_REPORT_DIR = project_path("data/report_center")


def _period_start(view: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if view == "daily":
        return now - timedelta(days=1)
    if view == "weekly":
        return now - timedelta(days=7)
    return None


def _in_period(value: str, start: datetime | None) -> bool:
    if start is None:
        return True
    try:
        created = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return True
    return created >= start


def report_payload(view: str = "all-time") -> dict:
    start = _period_start(view)
    runs = [run for run in recent_auto_qc_runs(limit=1000) if _in_period(run.get("created_at", ""), start)]
    accepted = sum((run.get("counts") or {}).get("accepted_fix_count", 0) for run in runs)
    attempted = sum((run.get("counts") or {}).get("auto_fix_attempted_count", 0) for run in runs)
    scanned = sum((run.get("counts") or {}).get("scanned_count", 0) for run in runs)
    return {
        "view": view,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runs": runs,
        "counts": {
            "run_count": len(runs),
            "scanned_count": scanned,
            "auto_fix_attempted_count": attempted,
            "accepted_fix_count": accepted,
            "accept_rate": round(accepted / attempted, 4) if attempted else 0,
        },
        "queue": queue_stats(),
        "history": history_summary(),
    }


def generate_report_center(view: str = "all-time", *, output_dir: str | Path = DEFAULT_REPORT_DIR) -> dict:
    payload = report_payload(view)
    root = Path(output_dir) / view
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "report.json"
    csv_path = root / "report.csv"
    html_path = root / "report.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "value"])
        writer.writeheader()
        for key, value in payload["counts"].items():
            writer.writerow({"metric": key, "value": value})
    html_path.write_text(
        "<!doctype html><html><head><meta charset='utf-8'><title>Plato Report Center</title></head>"
        f"<body><h1>Report Center - {view}</h1><pre>{json.dumps(payload['counts'], indent=2)}</pre></body></html>",
        encoding="utf-8",
    )
    return {"payload": payload, "paths": {"json": str(json_path), "csv": str(csv_path), "html": str(html_path)}}
