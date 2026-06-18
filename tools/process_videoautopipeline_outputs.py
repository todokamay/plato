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
from modules.verdict_resolver import normalize_verdict, verdict_from_score
from modules.videoautopipeline_contract import default_delivery_root, find_waiting_jobs


APPROVED_BUCKETS = {"publish_ready", "safe_to_test", "fixed_publish_ready", "fixed_safe_to_test"}
ORIGINAL_APPROVED_BUCKETS = {"publish_ready", "safe_to_test"}
FIXED_APPROVED_BUCKETS = {"fixed_publish_ready", "fixed_safe_to_test"}
DELIVERY_VERDICTS = {"STRONG PUBLISH", "PUBLISH", "SAFE TO TEST"}
FIELDS = [
    "job_id",
    "source_final_path",
    "approved_output_path",
    "delivery_status",
    "plato_status",
    "plato_score",
    "plato_verdict",
    "plato_bucket",
    "improvement_status",
    "improvement_attempted",
    "improvement_accepted",
    "improvement_reason",
    "fixed_output_path",
    "reanalysis_status",
    "reanalysis_score",
    "reanalysis_verdict",
    "telegram_status",
    "sent",
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


def _existing_mp4(path: str) -> bool:
    return bool(path and Path(path).exists() and Path(path).is_file() and Path(path).suffix.lower() == ".mp4")


def _as_int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _has_blocking_issue(issues: list) -> bool:
    for issue in issues or []:
        if isinstance(issue, dict):
            priority = str(issue.get("priority") or "").upper()
            severity = str(issue.get("severity") or "").lower()
            if priority in {"P0", "P1"} or severity == "critical":
                return True
        else:
            text = str(issue).lower()
            if "critical" in text or "p0" in text or "p1" in text:
                return True
    return False


def is_delivery_publishable(verdict, score=None, issues: list | None = None) -> bool:
    final_verdict = normalize_verdict(verdict or verdict_from_score(score))
    return final_verdict in DELIVERY_VERDICTS and not _has_blocking_issue(issues or [])


def _issues_for(row: dict, prefix: str) -> list:
    issues = []
    issues.extend({"priority": "P0"} for _ in range(_as_int(row.get(f"P0_{prefix}"))))
    issues.extend({"priority": "P1"} for _ in range(_as_int(row.get(f"P1_{prefix}"))))
    if row.get("critical_issue_count"):
        issues.append({"severity": "critical"})
    return issues


def _approved_output(row: dict, original: str, *, improvement_enabled: bool = True) -> tuple[str, str]:
    if not row:
        return "", "Plato analysis returned no clip row"
    bucket = row.get("final_bucket", "")
    if row.get("fix_accepted") and row.get("fixed_path"):
        fixed_verdict = normalize_verdict(row.get("fixed_final_verdict") or verdict_from_score(row.get("fixed_adjusted_score")))
        fixed_issues = _issues_for(row, "after")
        if _has_blocking_issue(fixed_issues):
            return "", "fixed output has critical/P0/P1 delivery blockers"
        if bucket not in FIXED_APPROVED_BUCKETS and not is_delivery_publishable(fixed_verdict, row.get("fixed_adjusted_score"), fixed_issues):
            return "", f"fixed output verdict {fixed_verdict} is not delivery-publishable"
        fixed = row["fixed_path"]
        return (fixed, "accepted fixed output") if _existing_mp4(fixed) else ("", "accepted fixed output is missing")
    verdict = normalize_verdict(row.get("original_final_verdict") or verdict_from_score(row.get("original_adjusted_score")))
    issues = _issues_for(row, "before")
    if not is_delivery_publishable(verdict, row.get("original_adjusted_score"), issues):
        if _has_blocking_issue(issues):
            return "", f"original has critical/P0/P1 delivery blockers"
        return "", f"original verdict {verdict} is not delivery-publishable"
    approved = row.get("final_output_path") or original
    return (approved, f"original is {verdict} and no critical issues") if _existing_mp4(approved) else ("", "approved original output is missing")


def process_job(job: dict, args: argparse.Namespace, delivery_root: Path) -> dict:
    row = {
        "job_id": job["job_id"],
        "source_final_path": job["final_path"],
        "approved_output_path": "",
        "delivery_status": "dry_run" if args.dry_run else "pending",
        "plato_status": "pending",
        "plato_score": "",
        "plato_verdict": "",
        "plato_bucket": "",
        "improvement_status": "pending",
        "improvement_attempted": False,
        "improvement_accepted": False,
        "improvement_reason": "",
        "fixed_output_path": "",
        "reanalysis_status": "pending",
        "reanalysis_score": "",
        "reanalysis_verdict": "",
        "telegram_status": "skipped",
        "sent": False,
        "reason": "",
        "metadata_path": job.get("metadata_path", ""),
        "status_path": job.get("status_path", ""),
    }
    if args.dry_run:
        row["reason"] = "dry run"
        row["plato_status"] = "skipped"
        row["improvement_status"] = "skipped"
        row["improvement_reason"] = "dry run"
        row["reanalysis_status"] = "skipped"
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
        row.update({
            "plato_score": clip.get("original_adjusted_score", ""),
            "plato_verdict": clip.get("original_final_verdict", ""),
            "plato_bucket": clip.get("original_bucket", ""),
            "improvement_attempted": bool(clip.get("auto_fix_attempted")),
            "improvement_accepted": bool(clip.get("fix_accepted")) and _existing_mp4(clip.get("fixed_path", "")),
            "fixed_output_path": clip.get("fixed_path", ""),
            "reanalysis_score": clip.get("fixed_adjusted_score", ""),
            "reanalysis_verdict": clip.get("fixed_final_verdict", ""),
        })
        if row["improvement_accepted"]:
            row["improvement_status"] = "accepted"
            row["reanalysis_status"] = "succeeded"
        elif row["improvement_attempted"]:
            row["improvement_status"] = "rejected"
            row["reanalysis_status"] = "succeeded" if row["reanalysis_verdict"] else "failed"
        else:
            row["improvement_status"] = "skipped"
            row["reanalysis_status"] = "skipped"
        approved, reason = _approved_output(clip, job["final_path"], improvement_enabled=args.auto_fix)
        row["improvement_reason"] = clip.get("fix_acceptance_reason") or clip.get("fix_rejection_reason") or clip.get("failure_reason") or reason
        row["approved_output_path"] = approved
        row["plato_status"] = "approved" if approved else "rejected"
        row["reason"] = reason
        row["delivery_status"] = "approved" if approved else "not_sent"
        if approved and args.send_telegram:
            sent = send_video(approved, f"Plato approved: {Path(approved).name}")
            if sent.get("ok"):
                row["telegram_status"] = "sent"
            elif sent.get("skipped") and "missing" in str(sent.get("reason", "")).lower():
                row["telegram_status"] = "skipped_missing_env"
            else:
                row["telegram_status"] = "skipped" if sent.get("skipped") else "failed"
            row["sent"] = bool(sent.get("ok"))
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
