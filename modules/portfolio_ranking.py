from __future__ import annotations

from pathlib import Path


BUCKET_PUBLISH = "Publish Candidate"
BUCKET_SAFE = "Safe Test"
BUCKET_QUICK_FIX = "Quick Fix"
BUCKET_HIGH_UPSIDE = "High Upside Rework"
BUCKET_HOLD = "Hold / Source Material"
BUCKET_REJECT = "Reject"


BUCKET_FOLDER_MAP = {
    BUCKET_PUBLISH: "publish_ready",
    BUCKET_SAFE: "safe_to_test",
    BUCKET_QUICK_FIX: "needs_davinci_fix",
    BUCKET_HIGH_UPSIDE: "high_upside_rework",
    BUCKET_HOLD: "hold_source",
    BUCKET_REJECT: "reject",
}


VERDICT_BONUS = {
    "STRONG PUBLISH": 12,
    "PUBLISH": 10,
    "SAFE TO TEST": 5,
    "REWORK": 0,
    "HOLD": -20,
    "HOLD / CLIP FIRST": -20,
    "REJECT": -40,
}


EASY_ACTION_BONUS = {
    "re_export": 8,
    "cut": 8,
    "normalize_audio": 8,
    "shorten_ending": 8,
    "compress": 4,
    "boost_audio": 4,
    "replace_first_frame": 4,
}


def is_old_schema(report_data: dict | None) -> bool:
    if not report_data:
        return True
    scoring = report_data.get("scoring") or {}
    required = ("cap_final_verdict", "adjusted_score_verdict", "final_verdict", "verdict_source")
    return any(field not in scoring for field in required)


def _as_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _score(report_data: dict, scoring: dict, key: str, fallback: str | None = None) -> float:
    return _as_float(scoring.get(key, report_data.get(fallback or key)))


def priority_counts(edit_points: list[dict]) -> dict:
    return {
        "P0_count": sum(1 for point in edit_points if point.get("priority") == "P0"),
        "P1_count": sum(1 for point in edit_points if point.get("priority") == "P1"),
        "P2_count": sum(1 for point in edit_points if point.get("priority") == "P2"),
        "P3_count": sum(1 for point in edit_points if point.get("priority") == "P3"),
    }


def _top_edit_point(edit_points: list[dict]) -> dict:
    return edit_points[0] if edit_points else {}


def _critical_issue_count(report_data: dict, edit_points: list[dict]) -> int:
    weak_points = report_data.get("weak_points") or []
    technical = (report_data.get("technical_quality") or {}).get("issues") or []
    all_items = list(edit_points) + list(weak_points) + list(technical)
    return sum(1 for item in all_items if item.get("severity") == "critical" or item.get("priority") == "P0")


def _has_issue_text(report_data: dict, text: str) -> bool:
    haystack = " ".join(
        str(value)
        for value in [
            report_data.get("main_bottleneck"),
            report_data.get("verdict_cap"),
            report_data.get("edit_points"),
            report_data.get("weak_points"),
        ]
    ).lower()
    return text in haystack


def publish_priority_score(adjusted_score: float, final_verdict: str, p0_count: int, p1_count: int, alignment: str, old_schema: bool) -> float:
    alignment_penalty = {"aligned": 0, "minor_gap": 5, "major_gap": 10, "cap_limited": 0}.get(alignment or "aligned", 5)
    if old_schema:
        alignment_penalty += 10
    score = adjusted_score - (p0_count * 15) - (p1_count * 5) + VERDICT_BONUS.get(final_verdict, -40) - alignment_penalty
    return round(score, 1)


def upside_score(adjusted_score: float, estimated_after_p0_p1: float) -> float:
    return round(max(0.0, min(30.0, estimated_after_p0_p1 - adjusted_score)), 1)


def quick_fix_score(upside: float, adjusted_score: float, final_verdict: str, p0_count: int, top_action: str, critical_issue_count: int) -> float:
    easy_bonus = EASY_ACTION_BONUS.get(top_action or "", 0)
    current_quality_bonus = 10 if adjusted_score >= 68 else (5 if adjusted_score >= 60 else 0)
    critical_penalty = 30 if final_verdict == "REJECT" or critical_issue_count else 0
    return round(upside + easy_bonus - (p0_count * 8) - critical_penalty + current_quality_bonus, 1)


def risk_score(report_data: dict, p0_count: int, p1_count: int, critical_issue_count: int, old_schema: bool, alignment: str) -> tuple[int, str]:
    scoring = report_data.get("scoring") or {}
    edit_points = report_data.get("edit_points") or []
    risk = p0_count * 20 + p1_count * 8 + critical_issue_count * 15
    if old_schema:
        risk += 20
    if alignment in {"major_gap", "cap_limited"}:
        risk += 12
    if _has_issue_text(report_data, "bitrate"):
        risk += 8
    if _has_issue_text(report_data, "opening"):
        risk += 8
    if _has_issue_text(report_data, "active content"):
        risk += 8
    if _has_issue_text(report_data, "no audio"):
        risk += 15
    visual = (report_data.get("technical_quality") or {}).get("visual_metrics") or {}
    if _as_float(visual.get("black_ratio")) >= 0.4 or _as_float(visual.get("static_ratio")) >= 0.7:
        risk += 20
    if (scoring.get("final_verdict") or report_data.get("verdict")) == "REJECT":
        risk += 25
    if any(point.get("issue_type") in {"black_segment", "static_segment"} and point.get("priority") == "P0" for point in edit_points):
        risk += 15
    risk = int(max(0, min(100, risk)))
    if risk >= 80:
        level = "CRITICAL"
    elif risk >= 55:
        level = "HIGH"
    elif risk >= 30:
        level = "MEDIUM"
    else:
        level = "LOW"
    return risk, level


def assign_portfolio_bucket(report_data: dict) -> tuple[str, str]:
    scoring = report_data.get("scoring") or {}
    edit_points = report_data.get("edit_points") or []
    counts = priority_counts(edit_points)
    final_verdict = scoring.get("final_verdict") or report_data.get("final_verdict") or report_data.get("verdict")
    adjusted = _score(report_data, scoring, "adjusted_score", "investment_score")
    estimate = report_data.get("estimated_after_fixes") or {}
    after_p0_p1 = _as_float(estimate.get("estimated_after_p0_p1"), adjusted)
    upside = upside_score(adjusted, after_p0_p1)
    top_action = _top_edit_point(edit_points).get("action")
    critical_count = _critical_issue_count(report_data, edit_points)
    old_schema = is_old_schema(report_data)

    if old_schema:
        return BUCKET_HOLD, "Old report schema; reanalysis required before ranking."
    if final_verdict == "REJECT" or critical_count >= 3:
        return BUCKET_REJECT, "Reject verdict or too many critical blockers."
    if final_verdict in {"HOLD", "HOLD / CLIP FIRST"} or _has_issue_text(report_data, "source footage") or _has_issue_text(report_data, "duration is above"):
        return BUCKET_HOLD, "Source-like or hold verdict."
    if final_verdict in {"STRONG PUBLISH", "PUBLISH"} and adjusted >= 80 and counts["P0_count"] == 0 and counts["P1_count"] <= 1:
        return BUCKET_PUBLISH, "High adjusted score with publish verdict and low fix burden."
    if final_verdict == "SAFE TO TEST" and counts["P0_count"] == 0:
        if counts["P1_count"] <= 2 and upside < 8:
            return BUCKET_SAFE, "Safe to test without mandatory DaVinci fixes."
        return BUCKET_QUICK_FIX, "Safe test candidate with quick fix upside."
    if final_verdict == "REWORK" and counts["P0_count"] <= 1 and counts["P1_count"] <= 4 and top_action in EASY_ACTION_BONUS and after_p0_p1 >= 68:
        return BUCKET_QUICK_FIX, "Rework verdict but few easy fixes can cross a useful threshold."
    if final_verdict != "REJECT" and upside >= 12 and adjusted >= 35:
        return BUCKET_HIGH_UPSIDE, "Meaningful estimated lift after P0/P1 fixes."
    if final_verdict == "REWORK":
        return BUCKET_HIGH_UPSIDE, "Needs rework; keep below quick-fix priority."
    return BUCKET_REJECT, "Low current value and limited deterministic upside."


def build_portfolio_metrics(report_data: dict) -> dict:
    scoring = report_data.get("scoring") or {}
    edit_points = report_data.get("edit_points") or []
    counts = priority_counts(edit_points)
    adjusted = _score(report_data, scoring, "adjusted_score", "investment_score")
    raw = _score(report_data, scoring, "raw_score", "raw_investment_score")
    total_penalty = _score(report_data, scoring, "total_consistency_penalty")
    final_verdict = scoring.get("final_verdict") or report_data.get("final_verdict") or report_data.get("verdict")
    alignment = scoring.get("score_verdict_alignment") or "aligned"
    old_schema = is_old_schema(report_data)
    estimate = report_data.get("estimated_after_fixes") or {}
    after_p0 = _as_float(estimate.get("estimated_after_p0"), adjusted)
    after_p0_p1 = _as_float(estimate.get("estimated_after_p0_p1"), adjusted)
    up = upside_score(adjusted, after_p0_p1)
    top = _top_edit_point(edit_points)
    top_action = top.get("action")
    critical_count = _critical_issue_count(report_data, edit_points)
    quick = quick_fix_score(up, adjusted, final_verdict, counts["P0_count"], top_action, critical_count)
    publish = publish_priority_score(adjusted, final_verdict, counts["P0_count"], counts["P1_count"], alignment, old_schema)
    risk, level = risk_score(report_data, counts["P0_count"], counts["P1_count"], critical_count, old_schema, alignment)
    bucket, reason = assign_portfolio_bucket(report_data)
    return {
        "adjusted_score": round(adjusted, 1),
        "raw_score": round(raw, 1),
        "total_penalty": round(total_penalty, 1),
        "final_verdict": final_verdict,
        "raw_verdict": scoring.get("raw_verdict") or report_data.get("raw_verdict"),
        "cap_final_verdict": scoring.get("cap_final_verdict") or report_data.get("cap_final_verdict"),
        "adjusted_score_verdict": scoring.get("adjusted_score_verdict") or report_data.get("adjusted_score_verdict"),
        "verdict_source": scoring.get("verdict_source") or report_data.get("verdict_source"),
        "score_verdict_alignment": alignment,
        "portfolio_bucket": bucket,
        "portfolio_reason": reason,
        "publish_priority_score": publish,
        "quick_fix_score": quick,
        "upside_score": up,
        "risk_score": risk,
        "risk_level": level,
        **counts,
        "top_edit_point": top.get("description") or top.get("issue_type") or "",
        "top_action": top_action or "",
        "estimated_after_p0": round(after_p0, 1),
        "estimated_after_p0_p1": round(after_p0_p1, 1),
        "old_schema": old_schema,
        "needs_reanalysis": old_schema,
    }


def bucket_folder(bucket: str) -> str:
    return BUCKET_FOLDER_MAP.get(bucket, "reject")


def safe_filename(name: str) -> str:
    keep = [char if char.isalnum() or char in "._- " else "_" for char in Path(name).name]
    cleaned = "".join(keep).strip(" .")
    return cleaned or "clip.mp4"
