import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.auto_fix_evaluator import evaluate_fix


def report(score, verdict, p0=0, p1=0, duration=12.0, critical=False):
    points = []
    for index in range(p0):
        points.append({"priority": "P0", "issue_type": f"critical_{index}", "severity": "high"})
    for index in range(p1):
        points.append({"priority": "P1", "issue_type": f"issue_{index}", "severity": "medium"})
    if critical:
        points.append({"priority": "P0", "issue_type": "new_critical", "severity": "critical"})
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


def main() -> int:
    improved = evaluate_fix(report(60, "REWORK"), report(63, "REWORK"))
    assert improved["accepted"]
    assert improved["delta_score"] == 3

    verdict = evaluate_fix(report(60, "REWORK"), report(60.5, "SAFE TO TEST"))
    assert verdict["accepted"]
    assert verdict["verdict_improved"]

    worsened = evaluate_fix(report(60, "SAFE TO TEST"), report(57, "REWORK"))
    assert not worsened["accepted"]
    assert "final verdict worsened" in worsened["regressions"]

    unreadable = evaluate_fix(report(60, "REWORK"), None)
    assert not unreadable["accepted"]
    assert "fixed report missing or unreadable" in unreadable["regressions"]

    critical = evaluate_fix(report(60, "REWORK"), report(65, "SAFE TO TEST", critical=True))
    assert not critical["accepted"]
    assert "new critical issue appeared" in critical["regressions"]

    target = evaluate_fix(report(70, "REWORK"), report(70.5, "SAFE TO TEST"), {"target_verdict": "SAFE TO TEST"})
    assert target["accepted"]
    assert target["target_verdict_reached"]

    p0_drop = evaluate_fix(report(60, "REWORK", p0=1), report(59.5, "REWORK", p0=0))
    assert p0_drop["accepted"]
    assert p0_drop["P0_decreased"]

    print("test_auto_fix_evaluator: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
