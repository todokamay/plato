from config import THRESHOLDS


def _issue(issue_type: str, severity: str, description: str, recommendation: str, start: float = 0.0, end: float = 2.0) -> dict:
    return {
        "issue_type": issue_type,
        "severity": severity,
        "start_time": start,
        "end_time": end,
        "description": description,
        "recommendation": recommendation,
    }


def analyze_opening(visual_analysis: dict, audio_analysis: dict, duration: float) -> dict:
    opening_seconds = min(float(duration or 0), THRESHOLDS["opening_seconds"])
    opening_frames = [
        frame for frame in visual_analysis.get("frames", [])
        if frame.get("timestamp", 999) <= THRESHOLDS["opening_seconds"]
    ]
    score = 100.0
    issues = []

    opening_black = bool(opening_frames) and sum(1 for frame in opening_frames if frame.get("is_black")) / len(opening_frames) >= 0.5
    opening_static = bool(opening_frames) and sum(1 for frame in opening_frames if frame.get("is_static") or frame.get("low_motion")) / max(len(opening_frames) - 1, 1) >= 0.6
    early_motion_frames = [
        frame for frame in opening_frames
        if 0 < float(frame.get("timestamp") or 0) <= 0.5
    ]
    opening_first_half_static = bool(early_motion_frames) and all(
        frame.get("is_static") or frame.get("low_motion") or float(frame.get("motion_score") or 0) < 8
        for frame in early_motion_frames
    )
    opening_silence = bool(audio_analysis.get("opening_silence"))
    opening_motion_score = (
        sum(float(frame.get("motion_score") or 0) for frame in opening_frames) / len(opening_frames)
        if opening_frames
        else 0.0
    )
    first_frame = opening_frames[0] if opening_frames else {}

    if opening_black:
        score -= 35
        issues.append(
            _issue(
                "opening_black",
                "high",
                "The entry point is visually too dark or black.",
                "Cut the dark opening or replace it with a clear first frame.",
                0.0,
                opening_seconds,
            )
        )
    if opening_static:
        score -= 25
        issues.append(
            _issue(
                "weak_entry_point",
                "high",
                "The first two seconds are static or low motion.",
                "Cut the slow opening or add a strong first-frame hook.",
                0.0,
                opening_seconds,
            )
        )
        score = min(score, 60.0)
    elif opening_first_half_static:
        score -= 8
        score = min(score, 84.0)
        issues.append(
            _issue(
                "opening_low_visual_change",
                "medium",
                "The first half-second has low visual change.",
                "Cut the first beat tighter or add a stronger first-frame hook.",
                0.0,
                0.5,
            )
        )
    if opening_silence:
        score -= 20
        issues.append(
            _issue(
                "opening_silence",
                "high",
                "The opening starts without meaningful audio.",
                "Start with immediate sound or cut to the first audible moment.",
                0.0,
                opening_seconds,
            )
        )
        if opening_static:
            score = min(score, 45.0)
    if first_frame and first_frame.get("sharpness", 0) < THRESHOLDS["sharpness_bad"]:
        score -= 12
        issues.append(
            _issue(
                "soft_first_frame",
                "medium",
                "The first sampled frame is low clarity.",
                "Use a sharper first frame or re-export the clip.",
                0.0,
                0.5,
            )
        )
    if first_frame and first_frame.get("brightness", 255) < 35:
        score -= 10
        issues.append(
            _issue(
                "dark_first_frame",
                "medium",
                "The first sampled frame is dark.",
                "Start on a brighter moment or grade the opening.",
                0.0,
                0.5,
            )
        )
    if opening_black:
        score = min(score, 50.0)

    recommended_start_time = None
    for frame in opening_frames:
        timestamp = float(frame.get("timestamp") or 0)
        if timestamp >= 0.5 and not frame.get("is_black") and float(frame.get("motion_score") or 0) >= 10:
            recommended_start_time = timestamp
            break

    if recommended_start_time and (opening_static or opening_black or opening_silence):
        for issue in issues:
            if issue["issue_type"] in {"weak_entry_point", "opening_black", "opening_silence"}:
                issue["recommendation"] = f"Cut to around {recommended_start_time:.1f}s or add a stronger first-frame hook."

    return {
        "opening_score": round(max(0.0, min(100.0, score)), 1),
        "opening_issues": issues,
        "recommended_start_time": recommended_start_time,
        "opening_static": opening_static,
        "opening_first_half_static": opening_first_half_static,
        "opening_black": opening_black,
        "opening_silence": opening_silence,
        "opening_motion_score": round(opening_motion_score, 1),
    }
