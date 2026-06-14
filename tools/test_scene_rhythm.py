import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.rhythm_analyzer import analyze_rhythm


def main() -> int:
    visual = {
        "frames": [
            {"timestamp": 0.0, "motion_score": 0, "frame_diff": None},
            {"timestamp": 1.0, "motion_score": 1, "frame_diff": 0.4},
            {"timestamp": 2.0, "motion_score": 1, "frame_diff": 0.3},
            {"timestamp": 3.0, "motion_score": 60, "frame_diff": 32.0},
            {"timestamp": 4.0, "motion_score": 1, "frame_diff": 0.4},
            {"timestamp": 5.0, "motion_score": 1, "frame_diff": 0.3},
        ],
        "low_motion_segments": [{"start_time": 0.0, "end_time": 2.0, "issue_type": "low_motion"}],
        "static_segments": [{"start_time": 4.0, "end_time": 5.0, "issue_type": "static_segment"}],
        "black_segments": [],
        "credits_like_segments": [],
    }
    result = analyze_rhythm(visual, duration=5.0)
    assert result["scene_change_count"] >= 1, result
    assert result["scene_change_density_per_10s"] > 0
    assert result["dead_time_ratio"] > 0
    assert result["repeated_frame_ratio"] > 0
    assert result["longest_dead_segment"] is not None
    assert any(item["issue_type"] == "dead_time_segment" for item in result["segments"])
    assert any(item["issue_type"] == "static_ending" for item in result["segments"])

    print("test_scene_rhythm: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
