from __future__ import annotations

import csv
import json
from pathlib import Path

from modules.portfolio_ranking import safe_filename


FIX_PLAN_COLUMNS = [
    "filename",
    "clip_path",
    "portfolio_bucket",
    "final_verdict",
    "adjusted_score",
    "priority",
    "start_time",
    "end_time",
    "start_timecode",
    "end_timecode",
    "issue_type",
    "action",
    "recommended_edit",
    "expected_lift_investment",
    "confidence",
    "detected_by",
    "html_report_path",
]


MARKER_COLUMNS = [
    "timecode",
    "name",
    "note",
    "color",
    "duration_frames",
    "start_seconds",
    "end_seconds",
    "action",
    "priority",
]


def _fps(value) -> float:
    try:
        fps = float(value)
    except (TypeError, ValueError):
        fps = 30.0
    return fps if fps > 0 else 30.0


def seconds_to_timecode(seconds: float | int | None, fps: float | int | None = 30.0) -> str:
    fps_value = _fps(fps)
    total_frames = int(round(max(0.0, float(seconds or 0.0)) * fps_value))
    frames_per_second = int(round(fps_value)) or 30
    hours = total_frames // (frames_per_second * 3600)
    total_frames %= frames_per_second * 3600
    minutes = total_frames // (frames_per_second * 60)
    total_frames %= frames_per_second * 60
    secs = total_frames // frames_per_second
    frames = total_frames % frames_per_second
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"


def marker_color(point: dict) -> str:
    issue_type = point.get("issue_type") or ""
    if "audio" in issue_type or "silence" in issue_type:
        return "Blue"
    if "bitrate" in issue_type or "export" in issue_type or "sharpness" in issue_type:
        return "Purple"
    priority = point.get("priority")
    return {"P0": "Red", "P1": "Orange", "P2": "Yellow", "P3": "Blue"}.get(priority, "Blue")


def _duration_frames(point: dict, fps: float) -> int:
    start = float(point.get("start_time") or 0)
    end = point.get("end_time")
    if end is None:
        return 0
    return max(0, int(round((float(end) - start) * _fps(fps))))


def marker_rows_for_clip(entry: dict, include_priorities: set[str] | None = None) -> list[dict]:
    include_priorities = include_priorities or {"P0", "P1", "P2"}
    fps = _fps(entry.get("fps"))
    rows = []
    for point in entry.get("edit_points", []):
        if point.get("priority") not in include_priorities:
            continue
        rows.append(
            {
                "timecode": seconds_to_timecode(point.get("start_time"), fps),
                "name": f"{point.get('priority', '-')}: {point.get('issue_type') or point.get('action') or 'edit'}",
                "note": point.get("recommended_edit") or point.get("description") or "",
                "color": marker_color(point),
                "duration_frames": _duration_frames(point, fps),
                "start_seconds": point.get("start_time"),
                "end_seconds": point.get("end_time"),
                "action": point.get("action") or "",
                "priority": point.get("priority") or "",
            }
        )
    return rows


def fix_plan_rows(entries: list[dict], include_priorities: set[str] | None = None) -> list[dict]:
    include_priorities = include_priorities or {"P0", "P1", "P2"}
    rows = []
    for entry in entries:
        fps = _fps(entry.get("fps"))
        for point in entry.get("edit_points", []):
            if point.get("priority") not in include_priorities:
                continue
            rows.append(
                {
                    "filename": entry.get("filename"),
                    "clip_path": entry.get("file_path"),
                    "portfolio_bucket": entry.get("portfolio_bucket"),
                    "final_verdict": entry.get("final_verdict"),
                    "adjusted_score": entry.get("adjusted_score"),
                    "priority": point.get("priority"),
                    "start_time": point.get("start_time"),
                    "end_time": point.get("end_time"),
                    "start_timecode": seconds_to_timecode(point.get("start_time"), fps),
                    "end_timecode": seconds_to_timecode(point.get("end_time"), fps) if point.get("end_time") is not None else "",
                    "issue_type": point.get("issue_type"),
                    "action": point.get("action"),
                    "recommended_edit": point.get("recommended_edit") or point.get("description"),
                    "expected_lift_investment": (point.get("expected_lift") or {}).get("investment", 0),
                    "confidence": point.get("confidence"),
                    "detected_by": "/".join(point.get("detected_by") or []),
                    "html_report_path": entry.get("html_report_path"),
                }
            )
    return rows


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def export_davinci_files(entries: list[dict], output_dir: Path) -> dict:
    fix_dir = output_dir / "davinci_fix_plans"
    marker_dir = fix_dir / "markers"
    marker_dir.mkdir(parents=True, exist_ok=True)

    rows = fix_plan_rows(entries)
    csv_path = fix_dir / "batch_davinci_fix_plan.csv"
    json_path = fix_dir / "batch_davinci_fix_plan.json"
    _write_csv(csv_path, FIX_PLAN_COLUMNS, rows)
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    marker_paths: dict[str, str] = {}
    for entry in entries:
        marker_rows = marker_rows_for_clip(entry)
        if not marker_rows:
            continue
        marker_path = marker_dir / f"{Path(safe_filename(entry.get('filename') or entry.get('clip_id') or 'clip')).stem}_markers.csv"
        _write_csv(marker_path, MARKER_COLUMNS, marker_rows)
        entry["davinci_marker_path"] = str(marker_path)
        marker_paths[entry.get("clip_id") or entry.get("filename")] = str(marker_path)

    return {
        "fix_plan_csv": str(csv_path),
        "fix_plan_json": str(json_path),
        "marker_paths": marker_paths,
    }
