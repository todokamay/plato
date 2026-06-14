import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.auto_fix_planner import create_auto_fix_plan


def report(points, duration=12.0, has_audio=True, bitrate=900):
    return {
        "asset_overview": {"filename": "planner.mp4", "duration": duration, "has_audio": has_audio},
        "technical_quality": {"metadata": {"duration": duration, "has_audio": has_audio, "video_bitrate_kbps": bitrate}},
        "edit_points": points,
        "scoring": {
            "adjusted_score": 55,
            "final_verdict": "REWORK",
            "cap_final_verdict": "REWORK",
            "adjusted_score_verdict": "REWORK",
            "verdict_source": "tie",
        },
    }


def point(issue_type, action, start=None, end=None, priority="P1", confidence="high"):
    return {
        "id": f"{issue_type}_{start}_{end}",
        "issue_type": issue_type,
        "action": action,
        "start_time": start,
        "end_time": end,
        "priority": priority,
        "confidence": confidence,
        "expected_lift": {"investment": 5},
    }


def strategies(plan):
    return [fix["ffmpeg_strategy"] for fix in plan["fixes"]]


def main() -> int:
    assert "re_export" in strategies(create_auto_fix_plan(report([point("low_bitrate", "re_export")])))
    assert "normalize_audio" in strategies(create_auto_fix_plan(report([point("audio_too_quiet", "normalize_audio")])))
    assert "trim_start" in strategies(create_auto_fix_plan(report([point("low_visual_change_opening", "cut", 0, 0.5)])))
    assert "trim_end" in strategies(create_auto_fix_plan(report([point("static_ending", "shorten_ending", 10, 12)])))

    unsupported = create_auto_fix_plan(report([point("low_active_content_area", "zoom_in")]))
    assert not unsupported["can_auto_fix"]
    assert unsupported["manual_only"][0]["reason"] == "not auto-fixable in v0.2.2"

    many = create_auto_fix_plan(
        report(
            [
                point("low_bitrate", "re_export"),
                point("audio_too_quiet", "normalize_audio"),
                point("opening_silence", "boost_audio", 0, 1),
                point("low_sharpness", "re_export"),
            ]
        ),
        {"max_fixes_per_clip": 2},
    )
    assert len(many["fixes"]) == 2
    assert any("limited to 2 fixes" in reason for reason in many["blocked_reasons"])

    too_short = create_auto_fix_plan(report([point("opening_black", "cut", 0, 0.5)], duration=1.0))
    assert not too_short["can_auto_fix"]
    assert too_short["blocked_reasons"]

    no_audio = create_auto_fix_plan(report([point("no_audio", "boost_audio")], has_audio=False))
    assert not no_audio["can_auto_fix"]
    assert "no source audio" in no_audio["manual_only"][0]["reason"]

    print("test_auto_fix_planner: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
