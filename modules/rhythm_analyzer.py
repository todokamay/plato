from statistics import mean


def _segment(start: float | None, end: float | None, issue_type: str, severity: str, reason: str, recommendation: str, confidence: str = "medium") -> dict:
    return {
        "start_time": round(float(start), 2) if start is not None else None,
        "end_time": round(float(end), 2) if end is not None else None,
        "issue_type": issue_type,
        "severity": severity,
        "reason": reason,
        "recommendation": recommendation,
        "confidence": confidence,
    }


def _duration(segment: dict) -> float:
    start = segment.get("start_time")
    end = segment.get("end_time")
    if start is None or end is None:
        return 0.0
    return max(0.0, float(end) - float(start))


def _scene_change_threshold(frame_diffs: list[float]) -> float:
    if not frame_diffs:
        return 18.0
    avg = mean(frame_diffs)
    spread = mean([abs(value - avg) for value in frame_diffs]) if len(frame_diffs) > 1 else 0.0
    return max(14.0, avg + spread * 1.2)


def analyze_rhythm(visual_analysis: dict, duration: float) -> dict:
    duration = float(duration or 0.0)
    frames = sorted(visual_analysis.get("frames", []), key=lambda item: item.get("timestamp") or 0)
    motion_values = [float(frame.get("motion_score") or 0) for frame in frames if frame.get("motion_score") is not None]
    frame_diffs = [float(frame.get("frame_diff") or 0) for frame in frames if frame.get("frame_diff") is not None]
    threshold = _scene_change_threshold(frame_diffs)
    scene_changes = [
        {
            "timestamp": round(float(frame.get("timestamp") or 0), 2),
            "frame_diff": round(float(frame.get("frame_diff") or 0), 2),
        }
        for frame in frames
        if frame.get("frame_diff") is not None and float(frame.get("frame_diff") or 0) >= threshold
    ]

    static_segments = list(visual_analysis.get("static_segments", []))
    low_motion_segments = list(visual_analysis.get("low_motion_segments", []))
    black_segments = list(visual_analysis.get("black_segments", []))
    credits_like_segments = list(visual_analysis.get("credits_like_segments", []))

    segments = []
    for segment in low_motion_segments:
        segment_duration = _duration(segment)
        if segment_duration >= 1.0:
            severity = "high" if segment_duration >= 4.0 else "medium"
            segments.append(
                _segment(
                    segment.get("start_time"),
                    segment.get("end_time"),
                    "dead_time_segment",
                    severity,
                    "Low motion and no clear scene change indicate possible dead time.",
                    "Cut, compress, or add a stronger visual beat.",
                )
            )
    for segment in static_segments:
        segment_duration = _duration(segment)
        if segment_duration >= 0.8:
            segments.append(
                _segment(
                    segment.get("start_time"),
                    segment.get("end_time"),
                    "repeated_frame_segment",
                    "high" if segment_duration >= 3.0 else "medium",
                    "Repeated or nearly identical frames were detected.",
                    "Remove repeated frames or shorten this beat.",
                )
            )
    for segment in credits_like_segments:
        if _duration(segment) >= 1.0:
            segments.append(
                _segment(
                    segment.get("start_time"),
                    segment.get("end_time"),
                    "credits_like_segment",
                    "high" if duration and _duration(segment) / duration > 0.2 else "medium",
                    "A static text-card or credits-like segment may slow retention.",
                    "Shorten or remove unless it directly supports the hook.",
                    confidence=segment.get("confidence", "low"),
                )
            )

    if duration:
        ending_window = min(5.0, max(1.0, duration * 0.20))
        ending_start = max(0.0, duration - ending_window)
        for segment in low_motion_segments + static_segments:
            end = segment.get("end_time")
            start = segment.get("start_time")
            if end is not None and start is not None and float(end) >= ending_start and _duration(segment) >= 1.0:
                segments.append(
                    _segment(
                        start,
                        end,
                        "static_ending",
                        "high" if _duration(segment) >= 3.0 else "medium",
                        "The ending appears static or low motion.",
                        "Shorten the ending or cut after the last strong beat.",
                    )
                )
                break

    dead_time_duration = sum(_duration(segment) for segment in segments if segment["issue_type"] in {"dead_time_segment", "repeated_frame_segment"})
    dead_time_ratio = round(dead_time_duration / duration, 3) if duration > 0 else 0.0
    repeated_duration = sum(_duration(segment) for segment in segments if segment["issue_type"] == "repeated_frame_segment")
    repeated_frame_ratio = round(repeated_duration / duration, 3) if duration > 0 else 0.0
    longest_dead_segment = None
    dead_segments = [segment for segment in segments if segment["issue_type"] in {"dead_time_segment", "repeated_frame_segment"}]
    if dead_segments:
        longest_dead_segment = max(dead_segments, key=_duration)

    scene_change_density = round(len(scene_changes) / max(duration / 10.0, 1.0), 2) if duration else 0.0
    average_motion_score = round(mean(motion_values), 2) if motion_values else 0.0
    visual_rhythm_score = max(0.0, min(100.0, 100.0 - dead_time_ratio * 55.0 - repeated_frame_ratio * 25.0))
    if duration > 8 and scene_change_density < 0.5:
        visual_rhythm_score -= 8

    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    segments.sort(key=lambda item: (severity_rank.get(item["severity"], 4), item.get("start_time") or 0))

    return {
        "scene_change_count": len(scene_changes),
        "scene_changes": scene_changes,
        "scene_change_density_per_10s": scene_change_density,
        "dead_time_ratio": dead_time_ratio,
        "repeated_frame_ratio": repeated_frame_ratio,
        "longest_dead_segment": longest_dead_segment,
        "average_motion_score": average_motion_score,
        "low_motion_segments": low_motion_segments,
        "black_segments": black_segments,
        "visual_rhythm_score": round(max(0.0, min(100.0, visual_rhythm_score)), 1),
        "segments": segments,
    }
