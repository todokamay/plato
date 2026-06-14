import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.report_generator import generate_report_html, generate_report_json


def main() -> int:
    clip = {"id": "clip1", "original_filename": "sample.mp4", "file_size": 123, "status": "analyzed"}
    analyses = {
        "metadata": {"duration": 10, "width": 1080, "height": 1920, "fps": 30, "aspect_ratio": 1.777, "has_audio": True},
        "opening": {"opening_score": 90},
        "retention": {"drawdown_segments": []},
        "visual": {
            "avg_brightness": 80,
            "avg_sharpness": 120,
            "black_ratio": 0,
            "static_ratio": 0,
            "active_content_ratio": 0.62,
            "active_width_ratio": 0.70,
            "active_height_ratio": 0.88,
            "black_border_ratio": 0.38,
            "active_content": {
                "active_content_ratio": 0.62,
                "active_width_ratio": 0.70,
                "active_height_ratio": 0.88,
                "black_border_ratio": 0.38,
                "pillarbox_detected": False,
                "letterbox_detected": False,
                "small_center_content_detected": False,
                "confidence": "medium",
                "issues": [],
            },
        },
        "audio": {"has_audio": True, "mean_volume_db": -18, "max_volume_db": -2, "silence_ratio": 0, "opening_silence": False},
    }
    scores = {
        "investment_score": 82,
        "raw_investment_score": 91,
        "adjusted_investment_score": 82,
        "total_consistency_penalty": 9,
        "verdict": "PUBLISH",
        "raw_verdict": "STRONG PUBLISH",
        "verdict_cap": {
            "applied": True,
            "raw_verdict": "STRONG PUBLISH",
            "final_verdict": "PUBLISH",
            "raw_score": 91,
            "cap_reasons": ["active content fills 62% of the frame"],
            "cap_messages": ["Verdict capped to PUBLISH because active content fills 62% of the frame."],
            "strong_publish_requirements": [],
            "strong_publish_blockers": [],
        },
        "strong_publish_requirements": [
            {"label": "Active content fills at least 70%", "passed": False, "detail": "Active content ratio is 0.62."}
        ],
        "scoring": {
            "raw_score": 91,
            "adjusted_score": 82,
            "total_consistency_penalty": 9,
            "raw_verdict": "STRONG PUBLISH",
            "final_verdict": "PUBLISH",
            "score_verdict_alignment": "aligned",
            "score_verdict_gap": "raw_strong_publish_final_publish",
            "consistency_penalties": [
                {
                    "code": "active_content_cap",
                    "label": "Composition blocker",
                    "amount": 9,
                    "reason": "Active content does not fill enough of the vertical frame.",
                    "related_cap_reason": "active content fills 62% of the frame",
                    "related_edit_point_id": None,
                    "related_cap_reasons": ["active content fills 62% of the frame"],
                    "related_edit_point_ids": [],
                }
            ],
            "cap_reasons": ["active content fills 62% of the frame"],
            "consistency_flags": [],
        },
        "scores": {"opening": 90, "retention": 85, "technical": 80, "audio": 92, "format": 95, "risk": 100},
        "penalties": {},
        "technical_issues": [],
    }
    recommendations = {
        "main_bottleneck": {"label": "Technical quality", "description": "Lowest component.", "formula_weight": 0.2},
        "best_fix": {"description": "Re-export", "recommendation": "Raise bitrate.", "expected_score_lift": 2.8},
        "edit_points": [
            {
                "id": "edit_001",
                "start_time": 0.0,
                "end_time": 0.5,
                "issue_type": "low_visual_change_opening",
                "severity": "medium",
                "priority": "P1",
                "action": "cut",
                "description": "First half-second has low visual change.",
                "why_it_matters": "Short-form viewers decide quickly.",
                "recommended_edit": "Cut the first 0.5 seconds.",
                "expected_lift": {"opening": 10, "retention": 2, "investment": 3.0},
                "affected_scores": ["opening", "retention"],
                "difficulty": "easy",
                "confidence": "high",
                "detected_by": ["opening_analyzer", "frame_diff"],
                "source": "deterministic",
            }
        ],
        "estimated_after_fixes": {
            "current_score": 82,
            "estimated_after_p0": 82,
            "estimated_after_p0_p1": 85,
            "estimated_verdict_after_p0_p1": "PUBLISH",
            "notes": "Formula-based estimate, not historically validated.",
        },
        "weak_points": [],
        "improvement_plan": [],
        "expected_score_after_fixes": 84.8,
        "expected_score_note": "Formula-based estimate.",
    }
    report = generate_report_json(clip, analyses, scores, recommendations, "report1")
    html = generate_report_html(report)
    assert "executive_summary" in report
    assert "score_breakdown" in report
    assert report["verdict_cap"]["applied"] is True
    assert report["investment_score"] == 82
    assert report["raw_investment_score"] == 91
    assert report["scoring"]["adjusted_score"] == 82
    assert report["scoring"]["total_consistency_penalty"] == 9
    assert report["scoring"]["consistency_penalties"][0]["label"] == "Composition blocker"
    active_rows = [item for item in report["cap_evaluation_parameters"] if item["parameter_name"] == "Active Content Ratio"]
    assert active_rows
    assert "0.70" in active_rows[0]["threshold"]
    assert report["composition"]["active_content_ratio"] == 0.62
    assert report["edit_points"][0]["id"] == "edit_001"
    assert "timeline" in report
    assert "evaluation_parameters" in report
    assert report["estimated_after_fixes"]["estimated_after_p0_p1"] == 85
    assert "<html" in html.lower()
    assert "Verdict Cap Explanation" in html
    assert "Score Consistency" in html
    assert "Measured Value" in html
    assert "Active Content Ratio" in html
    assert "Adjusted score is formula-based" in json.dumps(report)
    assert "Active Content / Composition" in html
    assert "Edit Point Timeline" in html
    assert "Traceback" not in html

    print("test_report_generator: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
