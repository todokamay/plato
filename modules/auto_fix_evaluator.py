from __future__ import annotations

from modules.portfolio_ranking import priority_counts
from modules.verdict_resolver import normalize_verdict, verdict_rank as conservative_verdict_rank


def _as_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def verdict_rank(verdict: str | None) -> int:
    return 5 - conservative_verdict_rank(verdict)


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


def _duration_policy(before: dict, after: dict, options: dict) -> dict:
    min_duration = _as_float(options.get("min_duration", options.get("min_final_duration")), 8.0)
    short_clip_min_duration = _as_float(options.get("short_clip_min_duration"), 5.0)
    ultra_short_threshold = _as_float(options.get("ultra_short_threshold"), 8.0)
    max_loss_ratio = _as_float(options.get("max_duration_loss_ratio"), 0.15)
    allow_original_short = bool(options.get("allow_original_short"))
    original_duration = _as_float(before.get("duration"), 0.0)
    fixed_duration = _as_float(after.get("duration"), 0.0)
    duration_delta = round(fixed_duration - original_duration, 3)
    duration_loss_ratio = 0.0
    if original_duration > 0 and fixed_duration < original_duration:
        duration_loss_ratio = round((original_duration - fixed_duration) / original_duration, 4)
    is_original_short = bool(original_duration and original_duration < min_duration)
    use_short_policy = allow_original_short and is_original_short and original_duration < ultra_short_threshold
    min_duration_used = short_clip_min_duration if use_short_policy else min_duration

    accepted = True
    reasons: list[str] = []
    if not fixed_duration:
        accepted = False
        reasons.append("fixed duration is unknown")
    if fixed_duration and fixed_duration < min_duration_used:
        accepted = False
        reasons.append(f"fixed duration {fixed_duration:.1f}s is below {min_duration_used:.1f}s")
    if duration_loss_ratio > max_loss_ratio:
        accepted = False
        reasons.append(f"duration loss {duration_loss_ratio:.1%} exceeds {max_loss_ratio:.1%}")
    if accepted:
        if use_short_policy:
            reasons.append(f"original short clip allowed; fixed duration {fixed_duration:.1f}s passes {min_duration_used:.1f}s floor")
        else:
            reasons.append(f"fixed duration {fixed_duration:.1f}s passes {min_duration_used:.1f}s floor")
        if duration_loss_ratio:
            reasons.append(f"duration loss {duration_loss_ratio:.1%} within {max_loss_ratio:.1%}")

    return {
        "duration_policy": "accepted" if accepted else "rejected",
        "duration_policy_passed": accepted,
        "original_duration_sec": round(original_duration, 3),
        "fixed_duration_sec": round(fixed_duration, 3),
        "duration_delta_sec": duration_delta,
        "duration_loss_ratio": duration_loss_ratio,
        "is_original_short": is_original_short,
        "min_duration_used": min_duration_used,
        "duration_acceptance_reason": "; ".join(reasons),
    }


def evaluate_fix(original_report: dict | None, fixed_report: dict | None, options: dict | None = None) -> dict:
    options = options or {}
    min_improvement = _as_float(options.get("min_improvement"), 2.0)
    target_verdict = normalize_verdict(options.get("target_verdict") or "SAFE TO TEST")

    before = _summary(original_report)
    after = _summary(fixed_report)
    duration = _duration_policy(before, after, options)
    delta = round(after["adjusted_score"] - before["adjusted_score"], 1)
    verdict_improved = verdict_rank(after["final_verdict"]) > verdict_rank(before["final_verdict"])
    verdict_same_or_better = verdict_rank(after["final_verdict"]) >= verdict_rank(before["final_verdict"])
    target_reached = verdict_rank(after["final_verdict"]) >= verdict_rank(target_verdict)
    p0_decreased = after["P0_count"] < before["P0_count"]
    no_new_priority_issues = after["P0_count"] <= before["P0_count"] and after["P1_count"] <= before["P1_count"]

    regressions: list[str] = []
    if not fixed_report:
        regressions.append("fixed report missing or unreadable")
    if delta < 0:
        regressions.append("adjusted score regressed")
    if not verdict_same_or_better:
        regressions.append("final verdict worsened")
    if not duration["duration_policy_passed"]:
        regressions.append(duration["duration_acceptance_reason"])
    if after["P0_count"] > before["P0_count"]:
        regressions.append("new P0 blocker appeared")
    if after["P1_count"] > before["P1_count"]:
        regressions.append("new P1 issue appeared")
    if _critical_issue_count(fixed_report) > _critical_issue_count(original_report):
        regressions.append("new critical issue appeared")

    acceptance_reasons: list[str] = []
    if delta >= min_improvement:
        acceptance_reasons.append(f"adjusted score improved by {delta:.1f}")
    elif delta > 0 and duration["is_original_short"] and options.get("allow_original_short"):
        acceptance_reasons.append(f"short-clip score improved by {delta:.1f}")
    if verdict_improved:
        acceptance_reasons.append("final verdict improved")
    if target_reached:
        acceptance_reasons.append(f"target verdict {target_verdict} reached")
    if p0_decreased and delta >= 0:
        acceptance_reasons.append("P0 count decreased without score regression")
    if delta > 0 and verdict_same_or_better and no_new_priority_issues and duration["duration_policy_passed"]:
        acceptance_reasons.append("score improved with same-or-better verdict and no new P0/P1")

    accepted = bool(acceptance_reasons) and not regressions
    if accepted:
        reason = " and ".join(acceptance_reasons)
    elif regressions:
        reason = "; ".join(regressions)
    else:
        reason = "fixed output did not improve enough"
    fix_acceptance_reason = reason if accepted else ""
    fix_rejection_reason = "" if accepted else reason

    result = {
        "accepted": accepted,
        "reason": reason,
        "before": before,
        "after": after,
        "delta_score": delta,
        "verdict_improved": verdict_improved,
        "target_verdict_reached": target_reached,
        "P0_decreased": p0_decreased,
        "regressions": regressions,
        "fix_acceptance_reason": fix_acceptance_reason,
        "fix_rejection_reason": fix_rejection_reason,
    }
    result.update(duration)
    return result
