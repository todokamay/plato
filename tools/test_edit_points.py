import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.edit_point_generator import generate_edit_points


def main() -> int:
    analyses = {
        "metadata": {"duration": 24, "aspect_ratio": 1.778},
        "opening": {
            "opening_issues": [
                {
                    "issue_type": "opening_low_visual_change",
                    "severity": "medium",
                    "start_time": 0.0,
                    "end_time": 0.5,
                    "description": "First half-second has low visual change.",
                    "recommendation": "Cut the first 0.5 seconds.",
                }
            ]
        },
        "retention": {
            "drawdown_segments": [
                {
                    "issue_type": "static_segment",
                    "severity": "medium",
                    "start_time": 20.0,
                    "end_time": 23.5,
                    "reason": "Low visual change can feel like dead time.",
                    "recommendation": "Cut or compress this static section.",
                }
            ]
        },
        "rhythm": {
            "segments": [
                {
                    "issue_type": "static_ending",
                    "severity": "high",
                    "start_time": 20.0,
                    "end_time": 23.5,
                    "reason": "The ending appears static.",
                    "recommendation": "Shorten the ending.",
                }
            ]
        },
        "audio": {
            "audio_issues": [
                {
                    "issue_type": "silence_segment",
                    "severity": "medium",
                    "start_time": 10.0,
                    "end_time": 12.0,
                    "description": "Audio drops to silence.",
                    "recommendation": "Cut the silent gap.",
                }
            ],
            "audio_drop_segments": [],
        },
        "visual": {"issues": []},
    }
    scores = {
        "technical_issues": [
            {
                "issue_type": "low_bitrate",
                "severity": "medium",
                "description": "Video bitrate is low at 1768 kbps.",
                "recommendation": "Re-export with a higher video bitrate.",
            }
        ],
        "format_issues": [],
        "critical_issues": [],
    }
    points = generate_edit_points({"id": "clip1"}, analyses, scores, {})
    assert points, points
    assert all(required in points[0] for required in ["id", "start_time", "issue_type", "priority", "action", "expected_lift", "detected_by"])
    types = [point["issue_type"] for point in points]
    assert "low_visual_change_opening" in types
    assert "low_bitrate" in types
    assert "static_ending" in types
    assert "silence_segment" in types
    assert points == sorted(
        points,
        key=lambda item: (
            {"P0": 0, "P1": 1, "P2": 2, "P3": 3}[item["priority"]],
            -item["expected_lift"]["investment"],
            {"critical": 0, "high": 1, "medium": 2, "low": 3}[item["severity"]],
            item["start_time"] if item["start_time"] is not None else 999999,
        ),
    )
    assert len([point for point in points if point["issue_type"] in {"static_segment", "dead_time_segment", "repeated_frame_segment", "low_motion_segment"}]) <= 1

    print("test_edit_points: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
