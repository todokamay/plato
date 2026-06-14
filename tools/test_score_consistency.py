import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.score_consistency import _alignment_status, apply_score_consistency, calculate_consistency_penalties


def _score(raw=87.3, raw_verdict="PUBLISH", final_verdict="SAFE TO TEST", cap_reasons=None):
    return {
        "investment_score": raw,
        "raw_investment_score": raw,
        "raw_verdict": raw_verdict,
        "verdict": final_verdict,
        "verdict_cap": {
            "applied": raw_verdict != final_verdict,
            "raw_verdict": raw_verdict,
            "final_verdict": final_verdict,
            "raw_score": raw,
            "cap_reasons": cap_reasons or [],
        },
    }


def _analyses(bitrate=1768, active_ratio=0.75):
    return {
        "metadata": {"video_bitrate_kbps": bitrate},
        "visual": {"active_content": {"active_content_ratio": active_ratio}},
        "opening": {"opening_first_half_static": True},
    }


def main() -> int:
    score_result = _score(
        cap_reasons=[
            "video bitrate is low at 1768 kbps",
            "the first half-second has low visual change",
        ]
    )
    edit_points = [
        {"id": "edit_001", "priority": "P1", "issue_type": "low_bitrate"},
        {"id": "edit_002", "priority": "P1", "issue_type": "low_visual_change_opening"},
        {"id": "edit_003", "priority": "P1", "issue_type": "dead_time_segment"},
        {"id": "edit_004", "priority": "P2", "issue_type": "audio_too_quiet"},
    ]
    consistency = calculate_consistency_penalties(score_result, _analyses(), edit_points)
    adjusted = apply_score_consistency(score_result, consistency)
    assert consistency["raw_score"] == 87.3
    assert consistency["adjusted_score"] == 78.3
    assert consistency["total_consistency_penalty"] == 9.0
    assert round(sum(item["amount"] for item in consistency["consistency_penalties"]), 1) == 9.0
    assert consistency["consistency_penalty_capped"] is False
    assert consistency["cap_final_verdict"] == "SAFE TO TEST"
    assert consistency["adjusted_score_verdict"] == "SAFE TO TEST"
    assert consistency["final_verdict"] == "SAFE TO TEST"
    assert consistency["verdict_source"] == "tie"
    assert consistency["score_verdict_alignment"] == "aligned"
    assert adjusted["investment_score"] == consistency["adjusted_score"]
    assert adjusted["raw_investment_score"] == 87.3
    assert adjusted["verdict"] == "SAFE TO TEST"
    assert adjusted["final_verdict"] == "SAFE TO TEST"
    assert adjusted["consistency_penalty_capped"] is False

    adjusted_downgrade = calculate_consistency_penalties(
        _score(raw=82, raw_verdict="PUBLISH", final_verdict="PUBLISH"),
        _analyses(bitrate=1768),
        [{"id": "edit_001", "priority": "P1", "issue_type": "low_bitrate"}],
    )
    assert adjusted_downgrade["adjusted_score"] == 76.5
    assert adjusted_downgrade["cap_final_verdict"] == "PUBLISH"
    assert adjusted_downgrade["adjusted_score_verdict"] == "SAFE TO TEST"
    assert adjusted_downgrade["final_verdict"] == "SAFE TO TEST"
    assert adjusted_downgrade["verdict_source"] == "adjusted_score"

    rework_downgrade = calculate_consistency_penalties(
        _score(raw=74, raw_verdict="SAFE TO TEST", final_verdict="PUBLISH"),
        _analyses(bitrate=900),
        [{"id": "edit_001", "priority": "P1", "issue_type": "very_low_bitrate"}],
    )
    assert rework_downgrade["adjusted_score"] == 62
    assert rework_downgrade["adjusted_score_verdict"] == "REWORK"
    assert rework_downgrade["final_verdict"] == "REWORK"
    assert rework_downgrade["final_verdict"] not in {"SAFE TO TEST", "PUBLISH"}
    assert rework_downgrade["verdict_source"] == "adjusted_score"

    cap_cannot_be_upgraded = calculate_consistency_penalties(
        _score(raw=85, raw_verdict="PUBLISH", final_verdict="REWORK", cap_reasons=["manual hard cap"]),
        _analyses(bitrate=4000),
        [],
    )
    assert cap_cannot_be_upgraded["adjusted_score"] == 85
    assert cap_cannot_be_upgraded["adjusted_score_verdict"] == "PUBLISH"
    assert cap_cannot_be_upgraded["final_verdict"] == "REWORK"
    assert cap_cannot_be_upgraded["verdict_source"] == "cap"
    assert cap_cannot_be_upgraded["score_verdict_alignment"] == "cap_limited"

    low_bitrate = calculate_consistency_penalties(
        _score(cap_reasons=["video bitrate is low at 1768 kbps"]),
        _analyses(bitrate=1768),
        [{"id": "edit_001", "priority": "P1", "issue_type": "low_bitrate"}],
    )
    assert low_bitrate["total_consistency_penalty"] >= 5

    p0 = calculate_consistency_penalties(
        _score(raw=84, raw_verdict="PUBLISH", final_verdict="REWORK"),
        _analyses(bitrate=4000),
        [{"id": "edit_001", "priority": "P0", "issue_type": "black_segment"}],
    )
    assert p0["total_consistency_penalty"] >= 6
    assert p0["adjusted_score"] <= 78

    duplicate = calculate_consistency_penalties(
        _score(cap_reasons=["video bitrate is low at 1768 kbps"]),
        _analyses(bitrate=1768),
        [
            {"id": "edit_001", "priority": "P1", "issue_type": "low_bitrate"},
            {"id": "edit_002", "priority": "P1", "issue_type": "low_bitrate"},
        ],
    )
    assert len([item for item in duplicate["consistency_penalties"] if item["code"] == "low_bitrate_cap"]) == 1
    assert duplicate["total_consistency_penalty"] < 9

    clean = calculate_consistency_penalties(
        _score(raw=82, raw_verdict="PUBLISH", final_verdict="PUBLISH"),
        _analyses(bitrate=4000),
        [],
    )
    assert clean["adjusted_score"] == 82
    assert clean["total_consistency_penalty"] == 0

    critical = calculate_consistency_penalties(
        _score(
            raw=82,
            raw_verdict="PUBLISH",
            final_verdict="REJECT",
            cap_reasons=["a critical unreadable, black, or static-video issue is present"],
        ),
        _analyses(bitrate=4000),
        [{"id": "edit_001", "priority": "P0", "issue_type": "black_segment"}],
    )
    assert critical["adjusted_score"] < 35
    assert critical["score_verdict_alignment"] == "aligned"

    capped = calculate_consistency_penalties(
        _score(
            raw=10,
            raw_verdict="PUBLISH",
            final_verdict="REJECT",
            cap_reasons=["a critical unreadable, black, or static-video issue is present"],
        ),
        _analyses(bitrate=900),
        [
            {"id": "edit_001", "priority": "P0", "issue_type": "black_segment"},
            {"id": "edit_002", "priority": "P1", "issue_type": "very_low_bitrate"},
        ],
    )
    assert capped["adjusted_score"] == 0
    assert capped["total_consistency_penalty"] == 10
    assert capped["consistency_penalty_capped"] is True
    assert round(sum(item["amount"] for item in capped["consistency_penalties"]), 1) == capped["total_consistency_penalty"]
    assert any("uncapped_amount" in item for item in capped["consistency_penalties"])

    cap_only = calculate_consistency_penalties(
        _score(
            raw=91,
            raw_verdict="STRONG PUBLISH",
            final_verdict="PUBLISH",
            cap_reasons=["Strong Publish requirements are not fully met"],
        ),
        _analyses(bitrate=4000),
        [],
    )
    assert cap_only["total_consistency_penalty"] == 0
    assert cap_only["adjusted_score"] == 91
    assert cap_only["final_verdict"] == "PUBLISH"
    assert cap_only["verdict_source"] == "cap"
    assert cap_only["score_verdict_alignment"] == "cap_limited"

    assert _alignment_status(
        {"final_verdict": "PUBLISH", "adjusted_score_verdict": "STRONG PUBLISH", "verdict_source": "adjusted_score"},
        95,
        91,
        [],
    ) == "minor_gap"
    assert _alignment_status(
        {"final_verdict": "REWORK", "adjusted_score_verdict": "PUBLISH", "verdict_source": "adjusted_score"},
        88,
        82,
        [],
    ) == "major_gap"
    assert _alignment_status(
        {"final_verdict": "REWORK", "adjusted_score_verdict": "PUBLISH", "verdict_source": "cap"},
        88,
        82,
        ["manual cap"],
    ) == "cap_limited"

    print("test_score_consistency: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
