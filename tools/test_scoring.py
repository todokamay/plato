import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.scoring import formula_score, score_clip, verdict_for_score


def _base_inputs():
    metadata = {
        "ok": True,
        "duration": 30,
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "video_bitrate_kbps": 4000,
        "aspect_ratio": 1.777,
        "has_audio": True,
    }
    visual = {
        "avg_sharpness": 180,
        "black_ratio": 0,
        "static_ratio": 0,
        "credits_like_segments": [],
        "issues": [],
        "active_content": {
            "active_content_ratio": 0.75,
            "active_width_ratio": 0.90,
            "active_height_ratio": 0.90,
            "black_border_ratio": 0.25,
            "pillarbox_detected": False,
            "letterbox_detected": False,
            "small_center_content_detected": False,
        },
    }
    audio = {"has_audio": True, "mean_volume_db": -18, "silence_ratio": 0, "opening_silence": False}
    opening = {"opening_score": 90, "opening_static": False, "opening_black": False, "opening_first_half_static": False, "opening_issues": []}
    retention = {"retention_score": 85, "drawdown_segments": []}
    return metadata, visual, audio, opening, retention


def main() -> int:
    assert formula_score({"opening": 100, "retention": 100, "technical": 100, "audio": 100, "format": 100}) == 100
    assert verdict_for_score(90) == "STRONG PUBLISH"
    assert verdict_for_score(79) == "SAFE TO TEST"
    assert verdict_for_score(49) == "HOLD"

    metadata, visual, audio, opening, retention = _base_inputs()
    result = score_clip(metadata, visual, audio, opening, retention)
    assert result["investment_score"] > 80
    assert result["verdict"] == "STRONG PUBLISH"

    metadata, visual, audio, opening, retention = _base_inputs()
    metadata["video_bitrate_kbps"] = 1767
    low_bitrate = score_clip(metadata, visual, audio, opening, retention)
    assert low_bitrate["verdict"] == "SAFE TO TEST"
    assert low_bitrate["verdict"] != "STRONG PUBLISH"

    metadata, visual, audio, opening, retention = _base_inputs()
    opening.update({"opening_score": 60, "opening_static": True})
    opening["opening_issues"] = [{"issue_type": "weak_entry_point", "severity": "high"}]
    static_opening = score_clip(metadata, visual, audio, opening, retention)
    assert static_opening["verdict"] in {"REWORK", "SAFE TO TEST"}

    metadata, visual, audio, opening, retention = _base_inputs()
    visual["active_content"]["active_content_ratio"] = 0.45
    visual["active_content"]["active_width_ratio"] = 0.55
    visual["active_content"]["active_height_ratio"] = 0.80
    weak_active = score_clip(metadata, visual, audio, opening, retention)
    assert weak_active["verdict"] in {"REWORK", "SAFE TO TEST"}
    assert weak_active["verdict_cap"]["applied"] is True

    metadata, visual, audio, opening, retention = _base_inputs()
    visual["issues"] = [{"issue_type": "static_segment", "severity": "high", "description": "Static segment."}]
    high_issue = score_clip(metadata, visual, audio, opening, retention)
    assert high_issue["verdict"] != "STRONG PUBLISH"

    visual["black_ratio"] = 0.8
    rejected = score_clip(metadata, visual, audio, opening, retention)
    assert rejected["verdict"] == "REJECT"

    metadata, visual, audio, opening, retention = _base_inputs()
    metadata.update({"duration": 120, "width": 1920, "height": 1080, "aspect_ratio": 0.562})
    horizontal = score_clip(metadata, visual, audio, opening, retention)
    assert horizontal["verdict"] in {"HOLD / CLIP FIRST", "REWORK", "HOLD"}
    assert horizontal["verdict"] != "PUBLISH"

    print("test_scoring: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
