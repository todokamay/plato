from __future__ import annotations

import csv
import json
from pathlib import Path


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _number(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [part.strip() for part in str(value).replace("|", ";").split(";") if part.strip()]


def load_summary(path: str | Path) -> list[dict]:
    source = Path(path)
    if source.suffix.lower() == ".csv":
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    payload = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return list(payload.get("clips") or [])
    if isinstance(payload, list):
        return payload
    return []


def find_clip(rows: list[dict], filename: str) -> dict:
    target = Path(filename).name.lower()
    for row in rows:
        if Path(str(row.get("filename") or row.get("clip") or "")).name.lower() == target:
            return row
    raise KeyError(f"Clip not found: {filename}")


def explain_decision(row: dict) -> dict:
    score = _number(row.get("adjusted_score") or row.get("original_adjusted_score"))
    fixed_score = _number(row.get("fixed_adjusted_score"))
    score_lift = _number(row.get("delta_score"))
    if score_lift is None and score is not None and fixed_score is not None:
        score_lift = round(fixed_score - score, 3)

    fix_attempted = _bool(row.get("auto_fix_attempted") or row.get("fix_attempted"))
    fix_accepted = _bool(row.get("fix_accepted"))
    replace_performed = str(row.get("replace_status") or "").lower() == "replaced"
    bucket = row.get("final_bucket") or row.get("bucket") or row.get("portfolio_bucket") or row.get("original_bucket") or ""
    verdict = row.get("fixed_final_verdict") if fix_accepted else ""
    verdict = verdict or row.get("final_verdict") or row.get("original_final_verdict") or row.get("verdict") or ""

    reasons = []
    for key in [
        "fix_acceptance_reason",
        "fix_rejection_reason",
        "duration_acceptance_reason",
        "failure_reason",
        "portfolio_reason",
    ]:
        value = row.get(key)
        if value:
            reasons.append(str(value))
    reasons.extend(_list(row.get("cap_reasons")))
    reasons.extend(_list(row.get("recommendations")))
    if not reasons:
        reasons.append("No detailed reason fields were present in this result row.")

    warnings = []
    if row.get("replace_error"):
        warnings.append(str(row["replace_error"]))
    if fix_attempted and not fix_accepted:
        warnings.append("Fix was attempted but not accepted.")
    if "reject" in str(bucket).lower() or str(verdict).upper() == "REJECT":
        warnings.append("Clip ended in a reject path.")

    if replace_performed:
        next_action = "Use the replaced original, or rollback with replace_log.json if needed."
    elif fix_accepted:
        next_action = "Review the accepted fixed output before publishing or testing."
    elif fix_attempted:
        next_action = "Review the rejection reason and consider manual edit or source re-export."
    elif "reject" in str(bucket).lower() or str(verdict).upper() == "REJECT":
        next_action = "Reject the clip or inspect the source manually."
    else:
        next_action = "Follow the final bucket workflow."

    return {
        "clip": row.get("filename") or row.get("clip") or "",
        "verdict": verdict,
        "bucket": bucket,
        "score": score,
        "fixed_score": fixed_score,
        "score_lift": score_lift,
        "fix_attempted": fix_attempted,
        "fix_accepted": fix_accepted,
        "replace_performed": replace_performed,
        "reasons": reasons,
        "warnings": warnings,
        "next_action": next_action,
    }


def explain_from_file(path: str | Path, filename: str) -> dict:
    return explain_decision(find_clip(load_summary(path), filename))


def format_explanation(payload: dict) -> str:
    lines = [
        f"clip: {payload.get('clip')}",
        f"verdict: {payload.get('verdict') or '-'}",
        f"bucket: {payload.get('bucket') or '-'}",
        f"score: {payload.get('score')}",
        f"fixed_score: {payload.get('fixed_score')}",
        f"score_lift: {payload.get('score_lift')}",
        f"fix_attempted: {payload.get('fix_attempted')}",
        f"fix_accepted: {payload.get('fix_accepted')}",
        f"replace_performed: {payload.get('replace_performed')}",
        "reasons:",
    ]
    lines.extend(f"- {reason}" for reason in payload.get("reasons") or [])
    if payload.get("warnings"):
        lines.append("warnings:")
        lines.extend(f"- {warning}" for warning in payload.get("warnings") or [])
    lines.append(f"next_action: {payload.get('next_action')}")
    return "\n".join(lines)
