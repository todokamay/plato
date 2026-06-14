import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.portfolio_ranking import (
    BUCKET_HIGH_UPSIDE,
    BUCKET_HOLD,
    BUCKET_PUBLISH,
    BUCKET_QUICK_FIX,
    BUCKET_REJECT,
    BUCKET_SAFE,
    build_portfolio_metrics,
    publish_priority_score,
)


def _report(final="PUBLISH", adjusted=86, raw=90, edit_points=None, estimated=None, old=False, cap_reasons=None, alignment="aligned"):
    scoring = {
        "raw_score": raw,
        "adjusted_score": adjusted,
        "total_consistency_penalty": round(max(0, raw - adjusted), 1),
        "raw_verdict": "PUBLISH",
        "cap_final_verdict": final,
        "adjusted_score_verdict": final,
        "final_verdict": final,
        "verdict_source": "tie",
        "score_verdict_alignment": alignment,
        "cap_reasons": cap_reasons or [],
    }
    if old:
        scoring.pop("cap_final_verdict")
        scoring.pop("adjusted_score_verdict")
        scoring.pop("verdict_source")
    return {
        "investment_score": adjusted,
        "raw_investment_score": raw,
        "verdict": final,
        "scoring": scoring,
        "edit_points": edit_points or [],
        "estimated_after_fixes": estimated or {
            "estimated_after_p0": adjusted,
            "estimated_after_p0_p1": adjusted,
        },
        "verdict_cap": {"cap_reasons": cap_reasons or []},
        "technical_quality": {"visual_metrics": {"black_ratio": 0, "static_ratio": 0}, "issues": []},
    }


def _point(priority="P1", action="cut", issue_type="weak_opening", lift=8):
    return {
        "priority": priority,
        "action": action,
        "issue_type": issue_type,
        "description": issue_type,
        "recommended_edit": "Fix it.",
        "expected_lift": {"investment": lift},
        "confidence": "high",
        "detected_by": ["test"],
    }


def main() -> int:
    publish = build_portfolio_metrics(_report(final="PUBLISH", adjusted=86))
    assert publish["portfolio_bucket"] == BUCKET_PUBLISH

    safe = build_portfolio_metrics(_report(final="SAFE TO TEST", adjusted=74))
    assert safe["portfolio_bucket"] == BUCKET_SAFE

    quick = build_portfolio_metrics(
        _report(
            final="REWORK",
            adjusted=62,
            edit_points=[_point("P1", "cut")],
            estimated={"estimated_after_p0": 62, "estimated_after_p0_p1": 72},
        )
    )
    assert quick["portfolio_bucket"] == BUCKET_QUICK_FIX

    high_upside = build_portfolio_metrics(
        _report(
            final="REWORK",
            adjusted=42,
            edit_points=[_point("P1", "reframe", "low_active_content_area")],
            estimated={"estimated_after_p0": 42, "estimated_after_p0_p1": 60},
        )
    )
    assert high_upside["portfolio_bucket"] == BUCKET_HIGH_UPSIDE

    reject = build_portfolio_metrics(_report(final="REJECT", adjusted=20, edit_points=[_point("P0", "remove_segment", "black_segment")]))
    assert reject["portfolio_bucket"] == BUCKET_REJECT

    hold = build_portfolio_metrics(_report(final="HOLD", adjusted=45, cap_reasons=["duration is above the short-form target"]))
    assert hold["portfolio_bucket"] == BUCKET_HOLD

    old = build_portfolio_metrics(_report(old=True))
    assert old["old_schema"] is True
    assert old["needs_reanalysis"] is True
    assert old["portfolio_bucket"] == BUCKET_HOLD

    assert publish_priority_score(86, "PUBLISH", 0, 1, "aligned", False) == 91

    aligned_risk = build_portfolio_metrics(_report(final="SAFE TO TEST", adjusted=74))
    cap_limited_risk = build_portfolio_metrics(_report(final="SAFE TO TEST", adjusted=74, alignment="cap_limited"))
    assert cap_limited_risk["risk_score"] == aligned_risk["risk_score"] + 12

    print("test_portfolio_ranking: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
