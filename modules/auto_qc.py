from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from config import REPORTS_DIR, SUPPORTED_EXTENSIONS, project_path
from modules import db, video_probe
from modules.auto_fix_evaluator import evaluate_fix, verdict_rank
from modules.auto_fix_executor import apply_auto_fix_plan
from modules.auto_fix_planner import create_auto_fix_plan
from modules.batch_qc import _copy_with_suffix, _parse_report, scan_video_files
from modules.clip_identity import get_clip_identity
from modules.pipeline import analyze_clip, import_clip_file
from modules.portfolio_ranking import (
    BUCKET_HIGH_UPSIDE,
    BUCKET_HOLD,
    BUCKET_PUBLISH,
    BUCKET_QUICK_FIX,
    BUCKET_REJECT,
    BUCKET_SAFE,
    build_portfolio_metrics,
    safe_filename,
)


FINAL_BUCKETS = [
    "publish_ready",
    "safe_to_test",
    "fixed_publish_ready",
    "fixed_safe_to_test",
    "rejected",
    "failed_fix",
    "hold_source",
    "debug_review",
]


RUN_COLUMNS = [
    "rank",
    "filename",
    "original_path",
    "original_report_path",
    "original_adjusted_score",
    "original_final_verdict",
    "original_bucket",
    "auto_fix_attempted",
    "auto_fix_allowed",
    "auto_fix_plan",
    "fixes_applied",
    "fixed_path",
    "fixed_report_path",
    "fixed_adjusted_score",
    "fixed_final_verdict",
    "delta_score",
    "duration_policy",
    "original_duration_sec",
    "fixed_duration_sec",
    "duration_delta_sec",
    "duration_loss_ratio",
    "is_original_short",
    "min_duration_used",
    "duration_acceptance_reason",
    "fix_acceptance_reason",
    "fix_rejection_reason",
    "verdict_improved",
    "fix_accepted",
    "final_output_path",
    "final_bucket",
    "replace_status",
    "backup_path",
    "replace_error",
    "failure_reason",
    "P0_before",
    "P1_before",
    "P0_after",
    "P1_after",
    "top_original_issue",
    "top_remaining_issue",
]


FIX_PLAN_COLUMNS = [
    "filename",
    "can_auto_fix",
    "reason",
    "fix_id",
    "priority",
    "issue_type",
    "action",
    "ffmpeg_strategy",
    "start_time",
    "end_time",
    "confidence",
    "expected_lift_investment",
    "manual_only_count",
    "blocked_reasons",
]


def run_id_now() -> str:
    return "run_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _as_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _report_json_path(report: dict | None) -> Path | None:
    if not report:
        return None
    report_id = report.get("id") or report.get("report_id")
    return project_path(REPORTS_DIR) / f"{report_id}.json" if report_id else None


def _copy_report_artifacts(report: dict | None, target_dir: Path, stem: str) -> dict:
    target_dir.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {"html": "", "json": ""}
    if not report:
        return copied
    report_id = report.get("id") or report.get("report_id") or stem
    html_path = Path(report.get("html_path") or "")
    if html_path.exists():
        target = target_dir / f"{safe_filename(stem)}_{report_id}.html"
        target.write_bytes(html_path.read_bytes())
        copied["html"] = str(target)
    json_path = _report_json_path(report)
    if json_path and json_path.exists():
        target = target_dir / f"{safe_filename(stem)}_{report_id}.json"
        target.write_bytes(json_path.read_bytes())
        copied["json"] = str(target)
    return copied


def _safe_fixed_output(output_dir: Path, source: Path) -> Path:
    fixed_dir = output_dir / "fixed_clips"
    fixed_dir.mkdir(parents=True, exist_ok=True)
    base = Path(safe_filename(source.name)).stem
    target = fixed_dir / f"{base}_plato_fixed.mp4"
    if not target.exists():
        return target
    for index in range(2, 10000):
        candidate = fixed_dir / f"{base}_plato_fixed_{index}.mp4"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find available fixed output name for {source}")


def _top_issue(report_data: dict | None) -> str:
    if not report_data:
        return ""
    point = (report_data.get("edit_points") or [{}])[0] if report_data.get("edit_points") else {}
    return point.get("description") or point.get("issue_type") or point.get("action") or ""


def _report_duration(report_data: dict | None) -> float:
    if not report_data:
        return 0.0
    overview = report_data.get("asset_overview") or {}
    metadata = (report_data.get("technical_quality") or {}).get("metadata") or {}
    return _as_float(overview.get("duration"), _as_float(metadata.get("duration"), 0.0))


def _min_duration_for_clip(report_data: dict | None, options: dict) -> float:
    min_duration = _as_float(options.get("min_duration"), 8.0)
    short_clip_min_duration = _as_float(options.get("short_clip_min_duration"), 5.0)
    ultra_short_threshold = _as_float(options.get("ultra_short_threshold"), 8.0)
    duration = _report_duration(report_data)
    if options.get("allow_original_short") and duration and duration < min_duration and duration < ultra_short_threshold:
        return short_clip_min_duration
    return min_duration


def _fix_lift(fix: dict) -> float:
    return _as_float((fix.get("expected_lift") or {}).get("investment"), 0.0)


def _plan_rows(filename: str, plan: dict) -> list[dict]:
    if not plan.get("fixes"):
        return [
            {
                "filename": filename,
                "can_auto_fix": plan.get("can_auto_fix"),
                "reason": plan.get("reason"),
                "manual_only_count": len(plan.get("manual_only") or []),
                "blocked_reasons": "; ".join(plan.get("blocked_reasons") or []),
            }
        ]
    rows = []
    for fix in plan.get("fixes") or []:
        rows.append(
            {
                "filename": filename,
                "can_auto_fix": plan.get("can_auto_fix"),
                "reason": plan.get("reason"),
                "fix_id": fix.get("fix_id"),
                "priority": fix.get("priority"),
                "issue_type": fix.get("source_issue_type"),
                "action": fix.get("action"),
                "ffmpeg_strategy": fix.get("ffmpeg_strategy"),
                "start_time": fix.get("start_time"),
                "end_time": fix.get("end_time"),
                "confidence": fix.get("confidence"),
                "expected_lift_investment": _fix_lift(fix),
                "manual_only_count": len(plan.get("manual_only") or []),
                "blocked_reasons": "; ".join(plan.get("blocked_reasons") or []),
            }
        )
    return rows


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _html(payload: dict) -> str:
    counts = payload.get("counts") or {}
    rows = "\n".join(
        f"""
        <tr>
          <td>{clip.get('rank', '')}</td>
          <td>{clip.get('filename', '')}</td>
          <td>{clip.get('original_adjusted_score', '')}</td>
          <td>{clip.get('original_final_verdict', '')}</td>
          <td>{clip.get('original_bucket', '')}</td>
          <td>{clip.get('auto_fix_allowed', '')}</td>
          <td>{clip.get('auto_fix_attempted', '')}</td>
          <td>{clip.get('fix_accepted', '')}</td>
          <td>{clip.get('fixed_adjusted_score', '')}</td>
          <td>{clip.get('fixed_final_verdict', '')}</td>
          <td>{clip.get('delta_score', '')}</td>
          <td>{clip.get('duration_policy', '')}</td>
          <td>{clip.get('original_duration_sec', '')}</td>
          <td>{clip.get('fixed_duration_sec', '')}</td>
          <td>{clip.get('duration_loss_ratio', '')}</td>
          <td>{clip.get('final_bucket', '')}</td>
          <td>{clip.get('fix_acceptance_reason') or clip.get('fix_rejection_reason') or clip.get('failure_reason', '')}</td>
        </tr>
        """
        for clip in payload.get("clips", [])
    )
    bucket_items = "\n".join(
        f"<li>{bucket}: {counts.get(bucket + '_count', 0)}</li>"
        for bucket in FINAL_BUCKETS
    )
    accepted = "\n".join(
        f"<li>{clip.get('filename')}: {clip.get('delta_score')} points, {clip.get('fixed_final_verdict')} - {clip.get('fix_acceptance_reason')}</li>"
        for clip in payload.get("accepted_fixes", [])
    ) or "<li>No accepted fixes.</li>"
    failed = "\n".join(
        f"<li>{clip.get('filename')}: {clip.get('failure_reason')}</li>"
        for clip in payload.get("rejected_fixes", []) + payload.get("failures", [])
    ) or "<li>No failed fixes.</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Plato Auto QC Run Report</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; background:#101216; color:#eef3f8; margin:0; }}
    main {{ max-width:1280px; margin:0 auto; padding:28px; }}
    section {{ background:#191e27; border:1px solid #303947; border-radius:8px; padding:18px; margin:18px 0; }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ border-bottom:1px solid #303947; padding:8px; text-align:left; vertical-align:top; }}
    th {{ color:#9da8b7; }}
    a {{ color:#8bd3ff; }}
  </style>
</head>
<body>
<main>
  <h1>Auto QC Run Report</h1>
  <section>
    <h2>Executive Summary</h2>
    <p>Input: {payload.get('input_folder')}</p>
    <p>Scanned: {counts.get('scanned_count')} | Analyzed: {counts.get('analyzed_count')} | Planned: {counts.get('planned_count')} | Fix attempts: {counts.get('auto_fix_attempted_count')} | Accepted: {counts.get('accepted_fix_count')} | Rejected: {counts.get('rejected_fix_count')} | Failed: {counts.get('failed_count')}</p>
  </section>
  <section><h2>Final Output Counts</h2><ul>{bucket_items}</ul></section>
  <section><h2>Auto-Fix Results</h2><h3>Accepted</h3><ul>{accepted}</ul><h3>Failed / Rejected</h3><ul>{failed}</ul></section>
  <section>
    <h2>Full Table</h2>
    <table>
      <thead><tr><th>Rank</th><th>Filename</th><th>Before</th><th>Original Verdict</th><th>Original Bucket</th><th>Allowed</th><th>Attempted</th><th>Accepted</th><th>After</th><th>Fixed Verdict</th><th>Delta</th><th>Duration Policy</th><th>Original Sec</th><th>Fixed Sec</th><th>Loss Ratio</th><th>Final Bucket</th><th>Reason</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
</main>
</body>
</html>"""


def _payload(run_id: str, input_folder: Path, output_dir: Path | None, options: dict, entries: list[dict], counts: dict, paths: dict) -> dict:
    return {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_folder": str(input_folder.resolve()),
        "output_dir": str(output_dir) if output_dir else "",
        "options": options,
        "counts": counts,
        "paths": paths,
        "clips": entries,
        "failures": [entry for entry in entries if entry.get("failure_reason") and entry.get("final_bucket") in {"failed_fix", "debug_review"}],
        "accepted_fixes": [entry for entry in entries if entry.get("fix_accepted")],
        "rejected_fixes": [entry for entry in entries if entry.get("auto_fix_attempted") and not entry.get("fix_accepted")],
        "final_outputs": [entry.get("final_output_path") for entry in entries if entry.get("final_output_path")],
    }


def _analyze_source(source: Path, force: bool) -> tuple[dict, dict, dict, bool]:
    identity = get_clip_identity(source)
    existing = db.find_clip_by_identity(identity)
    report = db.get_latest_report_for_clip(existing["id"]) if existing else None
    if existing and report and not force:
        return existing, report, _parse_report(report) or {}, True
    clip = existing if existing else import_clip_file(source)
    result = analyze_clip(clip["id"])
    report = db.get_report(result["report_id"])
    return db.get_clip(clip["id"]) or clip, report, _parse_report(report) or {}, False


def _analyze_fixed(fixed_path: Path) -> tuple[dict, dict, dict]:
    clip = import_clip_file(fixed_path)
    result = analyze_clip(clip["id"])
    report = db.get_report(result["report_id"])
    return db.get_clip(clip["id"]) or clip, report, _parse_report(report) or {}


def _final_bucket_for_original(bucket: str) -> str:
    if bucket == BUCKET_PUBLISH:
        return "publish_ready"
    if bucket == BUCKET_SAFE:
        return "safe_to_test"
    if bucket == BUCKET_REJECT:
        return "rejected"
    if bucket == BUCKET_HOLD:
        return "hold_source"
    return "debug_review"


def _final_bucket_for_fixed(fixed_verdict: str | None, original_bucket: str) -> str:
    verdict = fixed_verdict or "REJECT"
    if verdict in {"STRONG PUBLISH", "PUBLISH"}:
        return "fixed_publish_ready"
    if verdict == "SAFE TO TEST":
        return "fixed_safe_to_test"
    if verdict == "REJECT" or original_bucket == BUCKET_REJECT:
        return "rejected"
    return "failed_fix"


def _copy_final(source: Path, output_dir: Path, bucket: str, copy_results: bool, no_copy_original_rejects: bool = False) -> str:
    if not copy_results:
        return ""
    if bucket == "rejected" and no_copy_original_rejects:
        return ""
    if not source.exists() or not source.is_file():
        return ""
    return str(_copy_with_suffix(source, output_dir / bucket))


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe_mp4_file(path: Path) -> str:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        return str(exc)
    if path.is_symlink():
        return "symlink paths are not replace-safe"
    if resolved.suffix.lower() != ".mp4":
        return "only .mp4 files can be replaced"
    if not resolved.is_file():
        return "path is not a file"
    return ""


def _next_backup_path(backup_dir: Path, original: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    safe_name = safe_filename(original.name)
    candidate = backup_dir / safe_name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(2, 10000):
        numbered = backup_dir / f"{stem}_{index}{suffix}"
        if not numbered.exists():
            return numbered
    raise RuntimeError(f"Could not find available backup name for {original}")


def _replace_original_with_fixed(original: Path, fixed: Path, backup_dir: Path, input_root: Path) -> dict:
    item = {
        "filename": original.name,
        "original_path": str(original),
        "fixed_path": str(fixed),
        "backup_path": "",
        "status": "skipped",
        "reason": "",
    }
    for label, path in [("original", original), ("fixed", fixed)]:
        reason = _safe_mp4_file(path)
        if reason:
            item["reason"] = f"{label} path unsafe: {reason}"
            return item
    if not _is_under(original, input_root):
        item["reason"] = "original path is outside input folder"
        return item
    if original.resolve() == fixed.resolve():
        item["reason"] = "fixed path matches original path"
        return item

    probe = video_probe.probe_video(str(fixed))
    item["ffprobe_ok"] = bool(probe.get("ok"))
    if not probe.get("ok"):
        item["reason"] = f"fixed ffprobe failed: {probe.get('error') or 'unreadable video'}"
        return item

    try:
        backup = _next_backup_path(backup_dir, original)
        shutil.copy2(original, backup)
        item["backup_path"] = str(backup)
        if backup.stat().st_size != original.stat().st_size:
            item["reason"] = "backup size verification failed"
            return item
    except Exception as exc:
        item["reason"] = f"backup failed: {exc}"
        return item

    temp = original.with_name(original.name + ".plato_replace_tmp")
    try:
        shutil.copy2(fixed, temp)
        temp.replace(original)
    except Exception as exc:
        item["reason"] = f"replace failed: {exc}"
        if temp.exists():
            temp.unlink(missing_ok=True)
        return item

    item["status"] = "replaced"
    item["reason"] = "accepted fixed clip replaced original"
    return item


def _replace_accepted_fixed_clips(
    entries: list[dict],
    *,
    input_root: Path,
    output_dir: Path,
    backup_dir: str | Path | None,
    confirm_replace: bool,
) -> dict:
    root = Path(backup_dir) if backup_dir else output_dir / "replace_backups"
    log = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_root": str(input_root.resolve()),
        "backup_dir": str(root),
        "confirmed": bool(confirm_replace),
        "items": [],
    }
    for row in entries:
        if not row.get("auto_fix_attempted") and not row.get("fix_accepted"):
            continue
        fixed_path = row.get("fixed_path")
        original = Path(row.get("original_path") or "")
        fixed = Path(fixed_path or "")
        if not row.get("fix_accepted"):
            item = {
                "filename": row.get("filename", ""),
                "original_path": row.get("original_path", ""),
                "fixed_path": fixed_path or "",
                "backup_path": "",
                "status": "skipped",
                "reason": "fixed clip was not accepted",
            }
        elif not confirm_replace:
            item = {
                "filename": row.get("filename", ""),
                "original_path": row.get("original_path", ""),
                "fixed_path": fixed_path or "",
                "backup_path": "",
                "status": "skipped",
                "reason": "--confirm-replace is required",
            }
        else:
            item = _replace_original_with_fixed(original, fixed, root, input_root)
        row["replace_status"] = item.get("status", "")
        row["backup_path"] = item.get("backup_path", "")
        row["replace_error"] = "" if item.get("status") == "replaced" else item.get("reason", "")
        log["items"].append(item)
    log["replaced_count"] = sum(1 for item in log["items"] if item.get("status") == "replaced")
    log["skipped_count"] = sum(1 for item in log["items"] if item.get("status") != "replaced")
    return log


def rollback_replace_log(log_path: str | Path) -> dict:
    path = Path(log_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    input_root = Path(payload.get("input_root") or ".")
    items = []
    for item in payload.get("items", []):
        if item.get("status") != "replaced":
            continue
        original = Path(item.get("original_path") or "")
        backup = Path(item.get("backup_path") or "")
        result = {
            "filename": item.get("filename", ""),
            "original_path": str(original),
            "backup_path": str(backup),
            "status": "skipped",
            "reason": "",
        }
        reason = _safe_mp4_file(original)
        if reason:
            result["reason"] = f"original path unsafe: {reason}"
            items.append(result)
            continue
        if payload.get("input_root") and not _is_under(original, input_root):
            result["reason"] = "original path is outside logged input folder"
            items.append(result)
            continue
        reason = _safe_mp4_file(backup)
        if reason:
            result["reason"] = f"backup path unsafe: {reason}"
            items.append(result)
            continue
        temp = original.with_name(original.name + ".plato_rollback_tmp")
        try:
            shutil.copy2(backup, temp)
            temp.replace(original)
            result["status"] = "restored"
            result["reason"] = "backup restored"
        except Exception as exc:
            result["reason"] = f"rollback failed: {exc}"
            if temp.exists():
                temp.unlink(missing_ok=True)
        items.append(result)
    rollback = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": items,
        "restored_count": sum(1 for item in items if item.get("status") == "restored"),
        "failed_count": sum(1 for item in items if item.get("status") != "restored"),
    }
    payload["rollback"] = rollback
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": rollback["failed_count"] == 0, **rollback}


def _create_dirs(output_dir: Path) -> None:
    for folder in [
        "original_reports",
        "fixed_reports",
        "fixed_clips",
        "logs",
        "fix_plans/per_clip",
        *FINAL_BUCKETS,
    ]:
        (output_dir / folder).mkdir(parents=True, exist_ok=True)


def _counts(entries: list[dict], scanned: int, analyzed: int, skipped: int, failed: int, planned_rows: int) -> dict:
    counts = {
        "scanned_count": scanned,
        "analyzed_count": analyzed,
        "skipped_count": skipped,
        "failed_count": failed,
        "planned_count": planned_rows,
        "auto_fix_allowed_count": sum(1 for entry in entries if entry.get("auto_fix_allowed")),
        "auto_fix_attempted_count": sum(1 for entry in entries if entry.get("auto_fix_attempted")),
        "accepted_fix_count": sum(1 for entry in entries if entry.get("fix_accepted")),
        "rejected_fix_count": sum(1 for entry in entries if entry.get("auto_fix_attempted") and not entry.get("fix_accepted")),
    }
    for bucket in FINAL_BUCKETS:
        counts[f"{bucket}_count"] = sum(1 for entry in entries if entry.get("final_bucket") == bucket)
    return counts


def run_auto_qc_fix(
    input_folder: str | Path,
    *,
    auto_fix: bool = False,
    dry_run: bool = False,
    force: bool = False,
    recursive: bool = False,
    copy_results: bool = False,
    output_dir: str | Path | None = None,
    limit: int | None = None,
    max_fixes_per_clip: int = 3,
    min_improvement: float = 2.0,
    target_verdict: str = "SAFE TO TEST",
    min_duration: float = 8.0,
    short_clip_min_duration: float = 5.0,
    ultra_short_threshold: float = 8.0,
    max_duration_loss_ratio: float = 0.15,
    allow_original_short: bool = False,
    keep_temp: bool = False,
    no_copy_original_rejects: bool = False,
    replace_with_fixed: bool = False,
    confirm_replace: bool = False,
    backup_dir: str | Path | None = None,
    target_file: str | Path | None = None,
    force_auto_fix: bool = False,
) -> dict:
    db.init_db()
    folder = Path(input_folder)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Input folder not found: {folder}")

    run_id = run_id_now()
    output = Path(output_dir) if output_dir else project_path("data/auto_qc_runs") / run_id
    if target_file:
        target = Path(target_file).resolve()
        if not target.exists() or not target.is_file() or target.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise FileNotFoundError(f"Target video not found: {target}")
        files = [target]
    else:
        files = scan_video_files(folder, recursive=recursive, limit=limit)
    options = {
        "auto_fix": auto_fix,
        "dry_run": dry_run,
        "force": force,
        "recursive": recursive,
        "copy_results": copy_results,
        "limit": limit,
        "max_fixes_per_clip": max_fixes_per_clip,
        "min_improvement": min_improvement,
        "target_verdict": target_verdict,
        "min_duration": min_duration,
        "short_clip_min_duration": short_clip_min_duration,
        "ultra_short_threshold": ultra_short_threshold,
        "max_duration_loss_ratio": max_duration_loss_ratio,
        "allow_original_short": allow_original_short,
        "keep_temp": keep_temp,
        "no_copy_original_rejects": no_copy_original_rejects,
        "replace_with_fixed": replace_with_fixed,
        "confirm_replace": confirm_replace,
        "backup_dir": str(backup_dir) if backup_dir else "",
        "force_auto_fix": force_auto_fix,
    }

    if dry_run:
        entries = [
            {
                "rank": index,
                "filename": source.name,
                "original_path": str(source.resolve()),
                "auto_fix_attempted": False,
                "auto_fix_allowed": False,
                "final_bucket": "debug_review",
                "failure_reason": "dry run: analysis/fixing/copying skipped",
            }
            for index, source in enumerate(files, start=1)
        ]
        counts = _counts(entries, len(files), 0, 0, 0, 0)
        return _payload(run_id, folder, None, options, entries, counts, {})

    _create_dirs(output)
    plan_dir = output / "fix_plans"
    per_clip_plan_dir = plan_dir / "per_clip"
    log_path = output / "logs" / "auto_fix.log"
    entries: list[dict] = []
    plan_rows: list[dict] = []
    analyzed_count = 0
    skipped_count = 0
    failed_count = 0
    log_lines: list[str] = []

    for source in files:
        row = {
            "filename": source.name,
            "original_path": str(source.resolve()),
            "auto_fix_attempted": False,
            "auto_fix_allowed": False,
            "fix_accepted": False,
            "verdict_improved": False,
            "delta_score": "",
            "fixed_path": "",
            "fixed_report_path": "",
            "final_output_path": "",
            "failure_reason": "",
            "duration_policy": "",
            "original_duration_sec": "",
            "fixed_duration_sec": "",
            "duration_delta_sec": "",
            "duration_loss_ratio": "",
            "is_original_short": "",
            "min_duration_used": "",
            "duration_acceptance_reason": "",
            "fix_acceptance_reason": "",
            "fix_rejection_reason": "",
            "final_bucket": "debug_review",
        }
        try:
            clip, report, report_data, skipped = _analyze_source(source, force)
            skipped_count += 1 if skipped else 0
            analyzed_count += 0 if skipped else 1
            original_copies = _copy_report_artifacts(report, output / "original_reports", Path(source.name).stem)
            metrics = build_portfolio_metrics(report_data)
            row.update(
                {
                    "original_report_path": original_copies.get("html") or report.get("html_path") or "",
                    "original_adjusted_score": metrics.get("adjusted_score"),
                    "original_final_verdict": metrics.get("final_verdict"),
                    "original_bucket": metrics.get("portfolio_bucket"),
                    "P0_before": metrics.get("P0_count"),
                    "P1_before": metrics.get("P1_count"),
                    "top_original_issue": _top_issue(report_data),
                }
            )

            min_duration_after_cut = _min_duration_for_clip(report_data, options)
            plan_options = {"max_fixes_per_clip": max_fixes_per_clip, "min_duration_after_cut": min_duration_after_cut}
            plan = create_auto_fix_plan(report_data, plan_options)
            plan_path = per_clip_plan_dir / f"{Path(safe_filename(source.name)).stem}_fix_plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
            row["auto_fix_plan"] = str(plan_path)
            plan_rows.extend(_plan_rows(source.name, plan))
            auto_fix_allowed = plan.get("can_auto_fix") and (force_auto_fix or metrics.get("portfolio_bucket") in {BUCKET_QUICK_FIX, BUCKET_HIGH_UPSIDE})
            row["auto_fix_allowed"] = bool(auto_fix_allowed)

            if auto_fix and auto_fix_allowed:
                row["auto_fix_attempted"] = True
                fixed_output = _safe_fixed_output(output, source)
                exec_result = apply_auto_fix_plan(
                    source,
                    plan,
                    fixed_output,
                    {
                        "keep_temp": keep_temp,
                        "max_fixes_per_clip": max_fixes_per_clip,
                        "min_duration_after_cut": min_duration_after_cut,
                    },
                )
                row["fixes_applied"] = ",".join(exec_result.get("strategies") or [fix.get("ffmpeg_strategy", "") for fix in plan.get("fixes", [])])
                if not exec_result.get("ok"):
                    row["failure_reason"] = exec_result.get("error") or "auto-fix failed"
                    row["final_bucket"] = "failed_fix"
                    row["final_output_path"] = _copy_final(source, output, "failed_fix", copy_results)
                    failed_count += 1
                    log_lines.append(f"{source.name}: fix failed: {row['failure_reason']}")
                    entries.append(row)
                    continue

                row["fixed_path"] = str(fixed_output)
                fixed_clip, fixed_report, fixed_data = _analyze_fixed(fixed_output)
                analyzed_count += 1
                fixed_copies = _copy_report_artifacts(fixed_report, output / "fixed_reports", fixed_output.stem)
                fixed_metrics = build_portfolio_metrics(fixed_data)
                evaluation = evaluate_fix(
                    report_data,
                    fixed_data,
                    {
                        "min_improvement": min_improvement,
                        "target_verdict": target_verdict,
                        "min_duration": min_duration,
                        "short_clip_min_duration": short_clip_min_duration,
                        "ultra_short_threshold": ultra_short_threshold,
                        "max_duration_loss_ratio": max_duration_loss_ratio,
                        "allow_original_short": allow_original_short,
                    },
                )
                row.update(
                    {
                        "fixed_report_path": fixed_copies.get("html") or fixed_report.get("html_path") or "",
                        "fixed_adjusted_score": fixed_metrics.get("adjusted_score"),
                        "fixed_final_verdict": fixed_metrics.get("final_verdict"),
                        "delta_score": evaluation.get("delta_score"),
                        "duration_policy": evaluation.get("duration_policy"),
                        "original_duration_sec": evaluation.get("original_duration_sec"),
                        "fixed_duration_sec": evaluation.get("fixed_duration_sec"),
                        "duration_delta_sec": evaluation.get("duration_delta_sec"),
                        "duration_loss_ratio": evaluation.get("duration_loss_ratio"),
                        "is_original_short": evaluation.get("is_original_short"),
                        "min_duration_used": evaluation.get("min_duration_used"),
                        "duration_acceptance_reason": evaluation.get("duration_acceptance_reason"),
                        "fix_acceptance_reason": evaluation.get("fix_acceptance_reason"),
                        "fix_rejection_reason": evaluation.get("fix_rejection_reason"),
                        "verdict_improved": evaluation.get("verdict_improved"),
                        "fix_accepted": evaluation.get("accepted"),
                        "P0_after": fixed_metrics.get("P0_count"),
                        "P1_after": fixed_metrics.get("P1_count"),
                        "top_remaining_issue": _top_issue(fixed_data),
                    }
                )
                if evaluation.get("accepted"):
                    final_bucket = _final_bucket_for_fixed(fixed_metrics.get("final_verdict"), metrics.get("portfolio_bucket"))
                    row["final_bucket"] = final_bucket
                    row["failure_reason"] = "" if final_bucket in {"fixed_publish_ready", "fixed_safe_to_test"} else "fixed version improved but is not publish/safe"
                    row["final_output_path"] = _copy_final(fixed_output, output, final_bucket, copy_results)
                    log_lines.append(f"{source.name}: accepted fix: {evaluation.get('reason')}")
                else:
                    row["failure_reason"] = evaluation.get("reason") or "fixed version rejected"
                    row["fix_rejection_reason"] = evaluation.get("fix_rejection_reason") or row["failure_reason"]
                    final_bucket = "rejected" if metrics.get("portfolio_bucket") == BUCKET_REJECT else "failed_fix"
                    row["final_bucket"] = final_bucket
                    row["final_output_path"] = _copy_final(source, output, final_bucket, copy_results)
                    log_lines.append(f"{source.name}: rejected fix: {row['failure_reason']}")
            else:
                if plan.get("can_auto_fix") and not auto_fix:
                    row["failure_reason"] = "auto-fix plan generated; --auto-fix not enabled"
                elif plan.get("can_auto_fix") and not auto_fix_allowed:
                    row["failure_reason"] = "safe fixes exist but bucket is not auto-fix eligible"
                final_bucket = _final_bucket_for_original(metrics.get("portfolio_bucket"))
                row["final_bucket"] = final_bucket
                row["final_output_path"] = _copy_final(source, output, final_bucket, copy_results, no_copy_original_rejects)
            entries.append(row)
        except Exception as exc:
            failed_count += 1
            row["failure_reason"] = str(exc)
            row["final_bucket"] = "debug_review"
            row["final_output_path"] = _copy_final(source, output, "debug_review", copy_results)
            log_lines.append(f"{source.name}: failed: {exc}")
            entries.append(row)

    entries.sort(
        key=lambda item: (
            0 if item.get("fix_accepted") else 1,
            -verdict_rank(item.get("fixed_final_verdict") or item.get("original_final_verdict")),
            -_as_float(item.get("fixed_adjusted_score"), _as_float(item.get("original_adjusted_score"), 0.0)),
            item.get("filename") or "",
        )
    )
    for index, entry in enumerate(entries, start=1):
        entry["rank"] = index

    replace_log = None
    replace_log_path = output / "logs" / "replace_log.json"
    if replace_with_fixed:
        replace_log = _replace_accepted_fixed_clips(
            entries,
            input_root=folder,
            output_dir=output,
            backup_dir=backup_dir,
            confirm_replace=confirm_replace,
        )
        replace_log_path.write_text(json.dumps(replace_log, ensure_ascii=False, indent=2), encoding="utf-8")

    paths = {
        "run_summary_json": str(output / "run_summary.json"),
        "run_summary_csv": str(output / "run_summary.csv"),
        "run_report_html": str(output / "run_report.html"),
        "run_fix_plan_csv": str(plan_dir / "run_fix_plan.csv"),
        "run_fix_plan_json": str(plan_dir / "run_fix_plan.json"),
        "auto_fix_log": str(log_path),
    }
    if replace_log is not None:
        paths["replace_log_json"] = str(replace_log_path)
    counts = _counts(entries, len(files), analyzed_count, skipped_count, failed_count, len(plan_rows))
    payload = _payload(run_id, folder, output, options, entries, counts, paths)
    if replace_log is not None:
        payload["replace_log"] = replace_log

    _write_csv(output / "run_summary.csv", RUN_COLUMNS, entries)
    (output / "run_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "run_report.html").write_text(_html(payload), encoding="utf-8")
    _write_csv(plan_dir / "run_fix_plan.csv", FIX_PLAN_COLUMNS, plan_rows)
    (plan_dir / "run_fix_plan.json").write_text(json.dumps(plan_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    log_path.write_text("\n".join(log_lines), encoding="utf-8")
    return payload


def recent_auto_qc_runs(limit: int = 8) -> list[dict]:
    root = project_path("data/auto_qc_runs")
    if not root.exists():
        return []
    summaries = sorted(root.glob("run_*/run_summary.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    output = []
    for path in summaries[:limit]:
        try:
            output.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return output
