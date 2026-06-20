from __future__ import annotations

import json
from pathlib import Path


def _read_json(path: str | Path) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_job(payload: dict) -> dict:
    jobs = payload.get("jobs") or []
    return jobs[0] if jobs and isinstance(jobs[0], dict) else {}


def _as_int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _same_path_or_name(left: str, right: str) -> bool:
    if not left or not right:
        return False
    left_path = Path(str(left))
    right_path = Path(str(right))
    if str(left_path).lower() == str(right_path).lower():
        return True
    return left_path.name.lower() == right_path.name.lower()


def _qc_summary_path(delivery_summary_path: str | Path | None, row: dict) -> Path | None:
    if not delivery_summary_path or not row.get("job_id"):
        return None
    return Path(delivery_summary_path).parent / "qc_runs" / str(row["job_id"]) / "run_summary.json"


def _matching_qc_clip(delivery_summary_path: str | Path | None, row: dict) -> tuple[dict, str]:
    path = _qc_summary_path(delivery_summary_path, row)
    if not path:
        return {}, ""
    payload = _read_json(path)
    clips = payload.get("clips") or []
    if not clips:
        return {}, str(path)
    source = str(row.get("source_final_path") or "")
    approved = str(row.get("approved_output_path") or "")
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        candidates = [
            str(clip.get("original_path") or ""),
            str(clip.get("final_output_path") or ""),
            str(clip.get("fixed_path") or ""),
            str(clip.get("filename") or ""),
        ]
        if any(_same_path_or_name(source, candidate) or _same_path_or_name(approved, candidate) for candidate in candidates):
            return clip, str(path)
    return (clips[0], str(path)) if len(clips) == 1 and isinstance(clips[0], dict) else ({}, str(path))


def _field(row: dict, clip: dict, *names: str):
    for name in names:
        if name in row and row.get(name) not in (None, ""):
            return row.get(name), f"delivery_summary.jobs[0].{name}"
        if name in clip and clip.get(name) not in (None, ""):
            return clip.get(name), f"qc_run.clips[0].{name}"
    return "", ""


def _reason(row: dict, clip: dict) -> tuple[str, str]:
    for name in [
        "reason",
        "improvement_reason",
        "fix_rejection_reason",
        "failure_reason",
        "top_remaining_issue",
        "top_original_issue",
    ]:
        value, source = _field(row, clip, name)
        if value:
            return str(value), source
    return "", ""


def _uses_fixed_output(row: dict) -> bool:
    return _as_bool(row.get("improvement_accepted")) or (
        bool(row.get("approved_output_path"))
        and bool(row.get("fixed_output_path"))
        and _same_path_or_name(str(row.get("approved_output_path")), str(row.get("fixed_output_path")))
    )


def _blocker_counts(row: dict, clip: dict) -> tuple[int, int, int, str]:
    prefix = "after" if _uses_fixed_output(row) else "before"
    critical, critical_source = _field(row, clip, "critical_issue_count", f"critical_{prefix}", f"critical_{prefix}_count")
    p0, p0_source = _field(row, clip, f"P0_{prefix}", "P0_count")
    p1, p1_source = _field(row, clip, f"P1_{prefix}", "P1_count")
    source = ", ".join(part for part in [critical_source, p0_source, p1_source] if part)
    return _as_int(critical), _as_int(p0), _as_int(p1), source


def _blocker_items(row: dict, clip: dict, reason: str) -> list[str]:
    items: list[str] = []
    for name in ["top_remaining_issue", "top_original_issue", "failure_reason", "improvement_reason", "reason"]:
        value, _source = _field(row, clip, name)
        text = str(value or "").strip()
        if text and text not in items:
            items.append(text)
    if reason and reason not in items:
        items.append(reason)
    return items[:5]


def _decision_status(row: dict, blocker_count: int) -> str:
    if not row:
        return "pending"
    if row.get("approved_output_path") and blocker_count == 0:
        return "approved"
    if row.get("delivery_status") in {"approved", "ready", "sent"} and blocker_count == 0:
        return "approved"
    return "blocked"


def _next_action(row: dict, blockers: dict, fix: dict, reason: str) -> str:
    verdict = str(row.get("plato_verdict") or "").upper()
    if row.get("approved_output_path") and not (blockers["critical"] or blockers["p0"] or blockers["p1"]):
        return "Approved output is ready for delivery."
    if not row:
        return "Run Plato processing to create a delivery summary."
    if blockers["critical"] or blockers["p0"] or blockers["p1"]:
        lead = "SAFE TO TEST, but blocked by critical/P0/P1 issues." if verdict == "SAFE TO TEST" else "Blocked by critical/P0/P1 issues."
        if fix["can_auto_fix"] and not fix["fix_attempted"]:
            return f"{lead} Run Check & Fix With Plato, then review again."
        if fix["fix_attempted"] and not fix["fix_accepted"]:
            return f"{lead} Plato fix was not accepted; manual edit or re-export is needed."
        return f"{lead} Fix the listed blockers, then rerun Plato QC."
    if "no clip row" in reason.lower():
        return "Rerun Plato processing; no matching QC clip row was found."
    if fix["can_auto_fix"] and not fix["fix_attempted"]:
        return "Run Check & Fix With Plato, then review the fixed output."
    return "Review the reason, fix the source/final output, then rerun Plato QC."


def explain_delivery_summary(path: str | Path) -> dict:
    payload = _read_json(path)
    return explain_delivery_row(_first_job(payload), path)


def explain_delivery_row(row: dict | None, delivery_summary_path: str | Path | None = None) -> dict:
    row = row or {}
    clip, qc_path = _matching_qc_clip(delivery_summary_path, row)
    reason, reason_source = _reason(row, clip)
    critical, p0, p1, blocker_source = _blocker_counts(row, clip)
    blockers = {
        "critical": critical,
        "p0": p0,
        "p1": p1,
        "reason": reason,
        "source_field": blocker_source or reason_source or ("qc_run" if qc_path else ""),
        "items": _blocker_items(row, clip, reason),
    }
    fix = {
        "can_auto_fix": _as_bool(clip.get("auto_fix_allowed") or row.get("auto_fix_allowed")),
        "fix_attempted": _as_bool(row.get("improvement_attempted") or clip.get("auto_fix_attempted")),
        "fix_accepted": _as_bool(row.get("improvement_accepted") or clip.get("fix_accepted")),
        "suggested_next_action": "",
    }
    blocker_count = critical + p0 + p1
    fix["suggested_next_action"] = _next_action(row, blockers, fix, reason)
    return {
        "decision": {
            "status": _decision_status(row, blocker_count),
            "score": row.get("plato_score", ""),
            "verdict": str(row.get("plato_verdict") or ""),
            "bucket": str(row.get("plato_bucket") or ""),
            "approved_output_path": str(row.get("approved_output_path") or ""),
            "delivery_status": str(row.get("delivery_status") or ""),
        },
        "blockers": blockers,
        "fix_recommendation": fix,
        "qc_summary_path": qc_path,
    }
