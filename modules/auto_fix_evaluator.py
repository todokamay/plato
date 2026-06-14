from __future__ import annotations

from modules.portfolio_ranking import priority_counts


VERDICT_ORDER = {
    "REJECT": 0,
    "HOLD": 1,
    "HOLD / CLIP FIRST": 1,
    "REWORK": 2,
    "SAFE TO TEST": 3,
    "PUBLISH": 4,
    "STRONG PUBLISH": 5,
}


def _as_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_verdict(verdict: str | None) -> str:
    value = (verdict or "REJECT").replace("_", " ").strip().upper()
    if value == "SAFE TO_TEST":
        value = "SAFE TO TEST"
    return value


def verdict_rank(verdict: str | None) -> int:
    return VERDICT_ORDER.get(normalize_verdict(verdict), 0)


def _summary(report: dict | None) -> dict:
    if not report:
        return {
            "adjusted_score": 0.0,
            "final_verdict": "REJECT",
            "P0_count": 0,
            "P1_count": 0,
            "duration": 0.0,
        }
    scoring = report.get("scoring") or {}
    overview = report.get("asset_overview") or {}
    counts = priority_counts(report.get("edit_points") or [])
    return {
        "adjusted_score": _as_float(scoring.get("adjusted_score"), _as_float(report.get("investment_score"), 0.0)),
        "final_verdict": normalize_verdict(scoring.get("final_verdict") or report.get("final_verdict") or report.get("verdict")),
        "P0_count": counts["P0_count"],
        "P1_count": counts["P1_count"],
        "duration": _as_float(overview.get("duration"), 0.0),
    }


def _critical_issue_count(report: dict | None) -> int:
    if not report:
        return 1
    edit_points = report.get("edit_points") or []
    weak_points = report.get("weak_points") or []
    technical = (report.get("technical_quality") or {}).get("issues") or []
    items = list(edit_points) + list(weak_points) + list(technical)
    return sum(1 for item in items if item.get("priority") == "P0" or item.get("severity") == "critical")


def evaluate_fix(original_report: dict | None, fixed_report: dict | None, options: dict | None = None) -> dict:
    options = options or {}
    min_improvement = _as_float(options.get("min_improvement"), 2.0)
    min_duration = _as_float(options.get("min_final_duration"), 8.0)
    target_verdict = normalize_verdict(options.get("target_verdict") or "SAFE TO TEST")

    before = _summary(original_report)
    after = _summary(fixed_report)
    delta = round(after["adjusted_score"] - before["adjusted_score"], 1)
    verdict_improved = verdict_rank(after["final_verdict"]) > verdict_rank(before["final_verdict"])
    target_reached = verdict_rank(after["final_verdict"]) >= verdict_rank(target_verdict)
    p0_decreased = after["P0_count"] < before["P0_count"]

    regressions: list[str] = []
    if not fixed_report:
        regressions.append("fixed report missing or unreadable")
    if delta < -1.0:
        regressions.append("adjusted score decreased by more than 1.0")
    if verdict_rank(after["final_verdict"]) < verdict_rank(before["final_verdict"]):
        regressions.append("final verdict worsened")
    if after["duration"] and after["duration"] < min_duration:
        regressions.append(f"duration is below {min_duration:.1f}s")
    if _critical_issue_count(fixed_report) > _critical_issue_count(original_report):
        regressions.append("new critical issue appeared")

    acceptance_reasons: list[str] = []
    if delta >= min_improvement:
        acceptance_reasons.append(f"adjusted score improved by {delta:.1f}")
    if verdict_improved:
        acceptance_reasons.append("final verdict improved")
    if target_reached:
        acceptance_reasons.append(f"target verdict {target_verdict} reached")
    if p0_decreased and delta >= -1.0:
        acceptance_reasons.append("P0 count decreased without score regression")

    accepted = bool(acceptance_reasons) and not regressions
    if accepted:
        reason = " and ".join(acceptance_reasons)
    elif regressions:
        reason = "; ".join(regressions)
    else:
        reason = "fixed output did not improve enough"

    return {
        "accepted": accepted,
        "reason": reason,
        "before": before,
        "after": after,
        "delta_score": delta,
        "verdict_improved": verdict_improved,
        "target_verdict_reached": target_reached,
        "P0_decreased": p0_decreased,
        "regressions": regressions,
    }
