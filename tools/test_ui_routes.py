import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app
from modules import db
from modules.report_generator import generate_report_json


def main() -> int:
    db.init_db()
    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/upload").status_code == 200
    assert client.get("/clips").status_code == 200

    clip = db.create_clip("route_sample.mp4", "route_sample.mp4", "data/temp/route_sample.mp4", 10)
    score_result = {
        "investment_score": 64,
        "raw_investment_score": 66,
        "adjusted_investment_score": 64,
        "total_consistency_penalty": 2,
        "verdict": "REWORK",
        "raw_verdict": "SAFE TO TEST",
        "verdict_cap": {
            "applied": True,
            "raw_verdict": "SAFE TO TEST",
            "final_verdict": "REWORK",
            "raw_score": 66,
            "cap_reasons": ["opening score is 55"],
        },
        "scoring": {
            "raw_score": 66,
            "adjusted_score": 64,
            "total_consistency_penalty": 2,
            "raw_verdict": "SAFE TO TEST",
            "final_verdict": "REWORK",
            "score_verdict_alignment": "aligned",
            "consistency_penalties": [
                {"code": "weak_opening_cap", "label": "Weak opening", "amount": 2, "reason": "Opening score is low."}
            ],
            "cap_reasons": ["opening score is 55"],
            "consistency_flags": [],
        },
        "scores": {"opening": 55, "retention": 65, "technical": 80, "audio": 75, "format": 70, "risk": 100},
        "penalties": {},
        "technical_issues": [],
    }
    recommendations = {
        "main_bottleneck": {"label": "Opening / entry point", "description": "Lowest component.", "formula_weight": 0.25},
        "best_fix": {"description": "Cut opening.", "recommendation": "Cut first second.", "expected_score_lift": 4.5},
        "weak_points": [],
        "improvement_plan": [],
        "expected_score_after_fixes": 68.5,
        "expected_score_note": "Formula-based estimate.",
    }
    analyses = {
        "metadata": {"duration": 10, "width": 1080, "height": 1920, "fps": 30, "aspect_ratio": 1.777, "has_audio": True},
        "opening": {},
        "retention": {"drawdown_segments": []},
        "visual": {"avg_brightness": 80, "avg_sharpness": 120, "black_ratio": 0, "static_ratio": 0},
        "audio": {"has_audio": True, "mean_volume_db": -18, "max_volume_db": -2, "silence_ratio": 0, "opening_silence": False},
    }
    report_id = "route_report_" + clip["id"][:8]
    report_json = generate_report_json(clip, analyses, score_result, recommendations, report_id)
    db.create_report(report_id, clip["id"], score_result, report_json, "data/reports/route_report.html")

    html_response = client.get(f"/reports/{report_id}")
    assert html_response.status_code == 200
    assert "Score Consistency" in html_response.text
    assert "Measured Value" in html_response.text
    json_response = client.get(f"/reports/{report_id}/json")
    assert json_response.status_code == 200
    assert json_response.json()["report_id"] == report_id
    assert json_response.json()["scoring"]["raw_score"] == 66
    assert json_response.json()["cap_evaluation_parameters"][0]["parameter_name"] == "Opening Visual Change"

    print("test_ui_routes: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
