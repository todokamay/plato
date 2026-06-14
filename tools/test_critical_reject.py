import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.edit_point_generator import generate_edit_points
from modules.score_consistency import apply_score_consistency, calculate_consistency_penalties
from modules.scoring import score_clip


def main() -> int:
    metadata = {
        "ok": True,
        "duration": 20,
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "video_bitrate_kbps": 4000,
        "aspect_ratio": 1.777,
        "has_audio": True,
    }
    visual = {
        "avg_sharpness": 120,
        "black_ratio": 0.80,
        "static_ratio": 0.90,
        "issues": [],
        "active_content": {
            "active_content_ratio": 0.75,
            "active_width_ratio": 0.90,
            "active_height_ratio": 0.90,
            "black_border_ratio": 0.10,
        },
    }
    audio = {"has_audio": True, "mean_volume_db": -18, "silence_ratio": 0, "opening_silence": False, "audio_issues": []}
    opening = {"opening_score": 90, "opening_static": False, "opening_black": False, "opening_first_half_static": False, "opening_issues": []}
    retention = {"retention_score": 90, "drawdown_segments": []}
    analyses = {
        "metadata": metadata,
        "visual": visual,
        "audio": audio,
        "opening": opening,
        "retention": retention,
        "rhythm": {"segments": [], "dead_time_ratio": 0},
    }
    clip = {"id": "critical_black", "original_filename": "critical_black.mp4"}

    score_result = score_clip(metadata, visual, audio, opening, retention)
    assert score_result["raw_verdict"] == "REJECT"
    assert score_result["verdict"] == "REJECT"
    assert score_result["penalties"]["critical_penalty"] == 80.0
    assert any(issue["issue_type"] == "black_frames_dominate" for issue in score_result["critical_issues"])

    edit_points = generate_edit_points(clip, analyses, score_result, {})
    assert edit_points
    assert edit_points[0]["priority"] == "P0"
    assert edit_points[0]["issue_type"] in {"black_segment", "static_segment"}

    consistency = calculate_consistency_penalties(score_result, analyses, edit_points)
    adjusted = apply_score_consistency(score_result, consistency)
    assert adjusted["verdict"] == "REJECT"
    assert adjusted["raw_verdict"] == "REJECT"
    assert adjusted["investment_score"] <= score_result["raw_investment_score"]

    print("test_critical_reject: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
