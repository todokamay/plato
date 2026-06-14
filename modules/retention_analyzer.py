from config import THRESHOLDS


def _drawdown(start: float | None, end: float | None, issue_type: str, severity: str, reason: str, recommendation: str) -> dict:
    return {
        "start_time": start,
        "end_time": end,
        "issue_type": issue_type,
        "severity": severity,
        "reason": reason,
        "recommendation": recommendation,
    }


def analyze_retention(visual_analysis: dict, audio_analysis: dict, duration: float) -> dict:
    duration = float(duration or 0)
    score = 100.0
    drawdowns = []

    black_ratio = float(visual_analysis.get("black_ratio") or 0)
    static_ratio = float(visual_analysis.get("static_ratio") or 0)

    score -= black_ratio * 45
    score -= static_ratio * 35

    for segment in visual_analysis.get("black_segments", []):
        drawdowns.append(
            _drawdown(
                segment["start_time"],
                segment["end_time"],
                "black_segment",
                "high",
                "Black frames create a strong retention risk.",
                "Remove this section or replace it with visible action.",
            )
        )
    for segment in visual_analysis.get("static_segments", []):
        severity = "high" if segment["end_time"] - segment["start_time"] >= 4 else "medium"
        score -= 6 if severity == "high" else 3
        drawdowns.append(
            _drawdown(
                segment["start_time"],
                segment["end_time"],
                "static_segment",
                severity,
                "Low visual change can feel like dead time.",
                "Cut or compress this static section.",
            )
        )
    for segment in visual_analysis.get("low_motion_segments", []):
        if segment["end_time"] - segment["start_time"] >= 3:
            score -= 3
            drawdowns.append(
                _drawdown(
                    segment["start_time"],
                    segment["end_time"],
                    "low_motion_segment",
                    "medium",
                    "Motion proxy stays low for several seconds.",
                    "Add a cut, zoom, caption beat, or remove the segment.",
                )
            )
    for segment in visual_analysis.get("credits_like_segments", []):
        score -= 8
        drawdowns.append(
            _drawdown(
                segment["start_time"],
                segment["end_time"],
                "credits_like_static_text_card",
                "medium",
                "This resembles a static text-card or credits-like block with low confidence.",
                "Shorten or remove if it is not essential to the hook.",
            )
        )

    if audio_analysis.get("opening_silence"):
        score -= 8
        drawdowns.append(
            _drawdown(
                0.0,
                min(2.0, duration),
                "opening_silence",
                "high",
                "Silent opening can delay engagement.",
                "Cut to immediate sound or add an intentional audio hook.",
            )
        )

    if duration > THRESHOLDS["max_short_duration"]:
        score -= 18
        drawdowns.append(
            _drawdown(
                THRESHOLDS["max_short_duration"],
                duration,
                "too_long_for_short_form",
                "high",
                "Duration is above the v0.1 short-form limit.",
                "Extract a 20-45 second short-form candidate.",
            )
        )
    elif duration and duration < 8:
        score -= 12
        drawdowns.append(
            _drawdown(
                0.0,
                duration,
                "too_short_to_develop",
                "medium",
                "The clip is very short and may not develop enough payoff.",
                "Use only if the hook and payoff are both immediate.",
            )
        )

    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    drawdowns.sort(key=lambda item: (severity_rank.get(item["severity"], 4), item["start_time"] or 0))

    return {
        "retention_score": round(max(0.0, min(100.0, score)), 1),
        "drawdown_segments": drawdowns,
    }
