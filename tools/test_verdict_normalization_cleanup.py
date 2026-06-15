from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.auto_fix_evaluator import evaluate_fix, verdict_rank as auto_fix_rank
from modules.portfolio_ranking import (
    BUCKET_HIGH_UPSIDE,
    BUCKET_HOLD,
    BUCKET_PUBLISH,
    BUCKET_QUICK_FIX,
    BUCKET_REJECT,
    BUCKET_SAFE,
    build_portfolio_metrics,
)
from modules.verdict_resolver import (
    more_conservative_verdict,
    normalize_verdict,
    verdict_from_score,
    verdict_rank,
)


def report(score, verdict, p0=0, p1=0, duration=12.0, old=False):
    points = [{"priority": "P0", "severity": "high"} for _ in range(p0)]
    points.extend({"priority": "P1", "severity": "medium"} for _ in range(p1))
    scoring = {
        "raw_score": score,
        "adjusted_score": score,
        "total_consistency_penalty": 0,
        "raw_verdict": verdict,
        "cap_final_verdict": verdict,
        "adjusted_score_verdict": verdict,
        "final_verdict": verdict,
        "verdict_source": "tie",
        "score_verdict_alignment": "aligned",
    }
    if old:
        scoring.pop("cap_final_verdict")
        scoring.pop("adjusted_score_verdict")
        scoring.pop("verdict_source")
    return {
        "investment_score": score,
        "raw_investment_score": score,
        "verdict": verdict,
        "asset_overview": {"duration": duration},
        "scoring": scoring,
        "edit_points": points,
        "estimated_after_fixes": {"estimated_after_p0": score, "estimated_after_p0_p1": score + 12},
        "verdict_cap": {"cap_reasons": []},
        "technical_quality": {"visual_metrics": {"black_ratio": 0, "static_ratio": 0}, "issues": []},
    }


def point(priority="P1", action="cut", issue_type="weak_opening"):
    return {
        "priority": priority,
        "action": action,
        "issue_type": issue_type,
        "description": issue_type,
        "expected_lift": {"investment": 8},
    }


def portfolio_report(final="PUBLISH", adjusted=86, edit_points=None, estimated=None, old=False):
    data = report(adjusted, final, old=old)
    data["edit_points"] = edit_points or []
    data["estimated_after_fixes"] = estimated or {"estimated_after_p0": adjusted, "estimated_after_p0_p1": adjusted}
    return data


def main() -> int:
    assert normalize_verdict(" safe_to_test ") == "SAFE TO TEST"
    assert normalize_verdict("hold-clip-first") == "HOLD / CLIP FIRST"
    assert normalize_verdict("  strong   publish ") == "STRONG PUBLISH"
    assert normalize_verdict("unknown") == "REJECT"

    assert verdict_rank("STRONG PUBLISH") < verdict_rank("PUBLISH") < verdict_rank("SAFE TO TEST")
    assert verdict_rank("SAFE TO TEST") < verdict_rank("REWORK") < verdict_rank("HOLD") < verdict_rank("REJECT")
    assert auto_fix_rank("STRONG PUBLISH") > auto_fix_rank("PUBLISH") > auto_fix_rank("SAFE TO TEST")
    assert auto_fix_rank("HOLD / CLIP FIRST") == auto_fix_rank("HOLD")
    assert more_conservative_verdict("PUBLISH", "REWORK") == "REWORK"
    assert more_conservative_verdict("REJECT", "PUBLISH") == "REJECT"

    thresholds = [
        (90, "STRONG PUBLISH"),
        (89.99, "PUBLISH"),
        (80, "PUBLISH"),
        (79.99, "SAFE TO TEST"),
        (68, "SAFE TO TEST"),
        (67.99, "REWORK"),
        (50, "REWORK"),
        (49.99, "HOLD"),
        (35, "HOLD"),
        (34.99, "REJECT"),
        (None, "REJECT"),
    ]
    for score, expected in thresholds:
        assert verdict_from_score(score) == expected

    assert evaluate_fix(report(60, "REWORK"), report(60.5, "SAFE TO TEST"))["accepted"]
    worsened = evaluate_fix(report(60, "SAFE TO TEST"), report(57, "REWORK"))
    assert not worsened["accepted"]
    assert "final verdict worsened" in worsened["regressions"]
    assert evaluate_fix(report(70, "REWORK"), report(70.5, "SAFE TO TEST"), {"target_verdict": "safe_to_test"})["target_verdict_reached"]

    assert build_portfolio_metrics(portfolio_report("PUBLISH", 86))["portfolio_bucket"] == BUCKET_PUBLISH
    assert build_portfolio_metrics(portfolio_report("SAFE TO TEST", 74))["portfolio_bucket"] == BUCKET_SAFE
    assert build_portfolio_metrics(
        portfolio_report("REWORK", 62, [point("P1", "cut")], {"estimated_after_p0": 62, "estimated_after_p0_p1": 72})
    )["portfolio_bucket"] == BUCKET_QUICK_FIX
    assert build_portfolio_metrics(
        portfolio_report("REWORK", 42, [point("P1", "reframe", "low_active_content_area")], {"estimated_after_p0": 42, "estimated_after_p0_p1": 60})
    )["portfolio_bucket"] == BUCKET_HIGH_UPSIDE
    assert build_portfolio_metrics(portfolio_report("HOLD", 45))["portfolio_bucket"] == BUCKET_HOLD
    assert build_portfolio_metrics(portfolio_report("REJECT", 20, [point("P0", "remove_segment", "black_segment")]))["portfolio_bucket"] == BUCKET_REJECT
    assert build_portfolio_metrics(portfolio_report(old=True))["needs_reanalysis"]

    print("test_verdict_normalization_cleanup: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
