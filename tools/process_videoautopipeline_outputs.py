from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.auto_qc import run_auto_qc_fix
from modules.telegram_delivery import send_video
from modules.videoautopipeline_contract import default_delivery_root, find_waiting_jobs


APPROVED_BUCKETS = {"publish_ready", "safe_to_test", "fixed_publish_ready", "fixed_safe_to_test"}
FIELDS = [
    "job_id",
    "source_final_path",
    "approved_output_path",
    "delivery_status",
    "plato_status",
    "telegram_status",
    "reason",
    "metadata_path",
    "status_path",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process VideoAutoPipeline outputs through Plato before optional Telegram delivery.")
    parser.add_argument("output_root", help="VideoAutoPipeline output root.")
    parser.add_argument("--auto-fix", action="store_true")
    parser.add_argument("--copy-results", action="store_true")
    parser.add_argument("--replace-with-fixed", action="store_true")
    parser.add_argument("--confirm-replace", action="store_true")
    parser.add_argument("--send-telegram", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    return parser.parse_args(argv)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def _row_for_clip(payload: dict, final_path: str) -> dict:
    target = Path(final_path).name
    for row in payload.get("clips", []):
        if row.get("filename") == target or Path(row.get("original_path", "")).name == target:
            return row
    return {}


def _approved_output(row: dict, original: str) -> tuple[str, str]:
    bucket = row.get("final_bucket", "")
    if bucket not in APPROVED_BUCKETS:
        return "", row.get("failure_reason") or f"not approved: {bucket or 'unknown'}"
    if row.get("fix_accepted") and row.get("fixed_path"):
        return row["fixed_path"], "accepted fixed output"
    return row.get("final_output_path") or original, "original accepted"


def process_job(job: dict, args: argparse.Namespace, delivery_root: Path) -> dict:
    row = {
        "job_id": job["job_id"],
        "source_final_path": job["final_path"],
        "approved_output_path": "",
        "delivery_status": "dry_run" if args.dry_run else "pending",
        "plato_status": "pending",
        "telegram_status": "skipped",
        "reason": "",
        "metadata_path": job.get("metadata_path", ""),
        "status_path": job.get("status_path", ""),
    }
    if args.dry_run:
        row["reason"] = "dry run"
        return row
    try:
        payload = run_auto_qc_fix(
            Path(job["final_path"]).parent,
            auto_fix=args.auto_fix,
            copy_results=args.copy_results,
            output_dir=delivery_root / "qc_runs" / job["job_id"],
            limit=1,
            allow_original_short=True,
            short_clip_min_duration=5,
            replace_with_fixed=args.replace_with_fixed,
            confirm_replace=args.confirm_replace,
        )
        clip = _row_for_clip(payload, job["final_path"])
        approved, reason = _approved_output(clip, job["final_path"])
        row["approved_output_path"] = approved
        row["plato_status"] = "approved" if approved else "rejected"
        row["reason"] = reason
        row["delivery_status"] = "approved" if approved else "not_sent"
        if approved and args.send_telegram:
            sent = send_video(approved, f"Plato approved: {Path(approved).name}")
            row["telegram_status"] = "sent" if sent.get("ok") else "skipped" if sent.get("skipped") else "failed"
            row["delivery_status"] = "sent" if sent.get("ok") else "approved_not_sent"
            row["reason"] = sent.get("reason") or row["reason"]
    except Exception as exc:
        row["plato_status"] = "failed"
        row["delivery_status"] = "failed"
        row["reason"] = str(exc)
    return row


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    delivery_root = Path(os.environ.get("PLATO_VAP_DELIVERY_ROOT") or default_delivery_root())
    jobs = find_waiting_jobs(args.output_root, delivery_root=delivery_root, limit=args.limit)
    rows = [process_job(job, args, delivery_root) for job in jobs]
    payload = {
        "created_at": utc_now(),
        "output_root": str(Path(args.output_root).resolve()),
        "dry_run": bool(args.dry_run),
        "count": len(rows),
        "sent_count": sum(1 for row in rows if row["telegram_status"] == "sent"),
        "approved_count": sum(1 for row in rows if row["plato_status"] == "approved"),
        "failed_count": sum(1 for row in rows if row["plato_status"] == "failed"),
        "jobs": rows,
    }
    write_json(delivery_root / "delivery_summary.json", payload)
    write_csv(delivery_root / "delivery_summary.csv", rows)
    for row in rows:
        write_json(delivery_root / "jobs" / f"{row['job_id']}.json", row)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if payload["failed_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
