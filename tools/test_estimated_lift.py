import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.edit_point_generator import estimate_after_fixes


def main() -> int:
    score_result = {
        "investment_score": 79.8,
        "raw_investment_score": 87.3,
        "adjusted_investment_score": 79.8,
        "verdict": "SAFE TO TEST",
        "cap_final_verdict": "SAFE TO TEST",
        "adjusted_score_verdict": "SAFE TO TEST",
        "final_verdict": "SAFE TO TEST",
        "verdict_source": "tie",
        "verdict_cap": {
            "applied": True,
            "cap_reasons": ["video bitrate is low at 1768 kbps", "the first half-second has low visual change"],
        },
    }
    points = [
        {"priority": "P1", "issue_type": "low_bitrate", "expected_lift": {"investment": 3.6}},
        {"priority": "P1", "issue_type": "low_visual_change_opening", "expected_lift": {"investment": 2.5}},
        {"priority": "P0", "issue_type": "black_segment", "expected_lift": {"investment": 20}},
    ]
    estimate = estimate_after_fixes(score_result, points)
    assert estimate["current_score"] == 79.8
    assert estimate["estimated_after_p0"] == 99.8
    assert estimate["estimated_after_p0_p1"] == 100.0
    assert estimate["estimated_verdict_after_p0_p1"] == "STRONG PUBLISH"
    assert "Formula-based" in estimate["notes"]

    capped = estimate_after_fixes(
        score_result,
        [{"priority": "P1", "issue_type": "low_bitrate", "expected_lift": {"investment": 3.6}}],
    )
    assert capped["estimated_verdict_after_p0_p1"] == "SAFE TO TEST"
    assert capped["estimated_after_p0_p1"] <= 100

    print("test_estimated_lift: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
