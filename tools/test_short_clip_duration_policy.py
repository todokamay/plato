import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.auto_fix_evaluator import evaluate_fix


def report(score, verdict="REWORK", duration=6.5, p0=0, p1=0):
    points = []
    for index in range(p0):
        points.append({"priority": "P0", "issue_type": f"p0_{index}", "severity": "high"})
    for index in range(p1):
        points.append({"priority": "P1", "issue_type": f"p1_{index}", "severity": "medium"})
    return {
        "asset_overview": {"duration": duration},
        "scoring": {
            "adjusted_score": score,
            "final_verdict": verdict,
            "cap_final_verdict": verdict,
            "adjusted_score_verdict": verdict,
            "verdict_source": "tie",
        },
        "edit_points": points,
        "technical_quality": {"issues": []},
    }


def opts():
    return {
        "allow_original_short": True,
        "short_clip_min_duration": 5.0,
        "ultra_short_threshold": 8.0,
        "min_duration": 8.0,
        "max_duration_loss_ratio": 0.15,
        "min_improvement": 2.0,
    }


def main() -> int:
    accepted = evaluate_fix(report(50, duration=6.5), report(51, duration=6.3), opts())
    assert accepted["accepted"], accepted
    assert accepted["duration_policy"] == "accepted"
    assert accepted["is_original_short"] is True
    assert accepted["min_duration_used"] == 5.0

    too_short = evaluate_fix(report(50, duration=6.5), report(60, duration=4.0), opts())
    assert not too_short["accepted"]
    assert too_short["duration_policy"] == "rejected"
    assert "below 5.0s" in too_short["fix_rejection_reason"]

    too_much_loss = evaluate_fix(report(50, duration=9.0), report(60, duration=6.0), opts())
    assert not too_much_loss["accepted"]
    assert too_much_loss["is_original_short"] is False
    assert "below 8.0s" in too_much_loss["fix_rejection_reason"]

    verdict_regression = evaluate_fix(report(60, "SAFE TO TEST", 6.5), report(70, "REWORK", 6.3), opts())
    assert not verdict_regression["accepted"]
    assert "final verdict worsened" in verdict_regression["fix_rejection_reason"]

    new_p0 = evaluate_fix(report(50, duration=6.5), report(60, duration=6.3, p0=1), opts())
    assert not new_p0["accepted"]
    assert "new P0 blocker appeared" in new_p0["fix_rejection_reason"]

    print("test_short_clip_duration_policy: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
