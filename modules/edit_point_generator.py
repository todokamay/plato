from config import SCORE_WEIGHTS
from modules.scoring import verdict_for_score


PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


TYPE_RULES = {
    "weak_entry_point": {
        "issue_type": "weak_opening",
        "action": "replace_first_frame",
        "affected_scores": ["opening", "retention"],
        "lift": {"opening": 12, "retention": 2},
        "why": "Short-form viewers decide quickly. A weak first moment can increase swipe risk.",
        "edit": "Cut the weak opening beat if the next frame is stronger, or replace the first frame with a stronger hook.",
        "detected_by": ["opening_analyzer", "frame_diff"],
    },
    "opening_low_visual_change": {
        "issue_type": "low_visual_change_opening",
        "action": "cut",
        "affected_scores": ["opening", "retention"],
        "lift": {"opening": 10, "retention": 2},
        "why": "The first half-second sets the swipe/no-swipe decision.",
        "edit": "Cut the first 0.5 seconds if the next frame is stronger, or add a stronger visual hook.",
        "detected_by": ["opening_analyzer", "frame_diff"],
    },
    "opening_black": {
        "issue_type": "opening_black",
        "action": "cut",
        "affected_scores": ["opening"],
        "lift": {"opening": 18},
        "why": "A black opening delays the first useful visual signal.",
        "edit": "Cut to the first visible frame or replace the opening with a clear hook.",
        "detected_by": ["opening_analyzer", "brightness"],
    },
    "opening_silence": {
        "issue_type": "opening_silence",
        "action": "boost_audio",
        "affected_scores": ["opening", "audio"],
        "lift": {"opening": 8, "audio": 10},
        "why": "Silent openings reduce immediate energy and can feel accidental.",
        "edit": "Start sound immediately, cut to the first audible moment, or add intentional audio.",
        "detected_by": ["audio_analyzer", "silencedetect"],
    },
    "soft_first_frame": {
        "issue_type": "first_frame_low_clarity",
        "action": "replace_first_frame",
        "affected_scores": ["opening", "technical"],
        "lift": {"opening": 6, "technical": 4},
        "why": "A soft first frame weakens perceived quality at the decision point.",
        "edit": "Use a sharper first frame or re-export from a cleaner source.",
        "detected_by": ["opening_analyzer", "laplacian_sharpness"],
    },
    "dark_first_frame": {
        "issue_type": "dark_scene",
        "action": "replace_first_frame",
        "affected_scores": ["opening"],
        "lift": {"opening": 5},
        "why": "A dark first frame hides the subject and weakens the hook.",
        "edit": "Start on a brighter frame or grade the opening brighter.",
        "detected_by": ["opening_analyzer", "brightness"],
    },
    "static_segment": {
        "issue_type": "static_segment",
        "action": "compress",
        "affected_scores": ["retention"],
        "lift": {"retention": 14},
        "why": "Static segments can feel like dead time and reduce retention.",
        "edit": "Cut, compress, or add a visual beat to this static segment.",
        "detected_by": ["visual_analyzer", "frame_diff"],
    },
    "low_motion_segment": {
        "issue_type": "low_motion_segment",
        "action": "compress",
        "affected_scores": ["retention"],
        "lift": {"retention": 10},
        "why": "Long low-motion stretches reduce perceived pace.",
        "edit": "Add a cut, zoom, caption beat, or remove the low-motion segment.",
        "detected_by": ["retention_analyzer", "motion_score"],
    },
    "dead_time_segment": {
        "issue_type": "dead_time_segment",
        "action": "remove_segment",
        "affected_scores": ["retention"],
        "lift": {"retention": 16},
        "why": "Dead time spends attention without adding new information.",
        "edit": "Remove or compress this section until the next meaningful visual beat.",
        "detected_by": ["rhythm_analyzer", "frame_diff"],
    },
    "repeated_frame_segment": {
        "issue_type": "repeated_frame_segment",
        "action": "remove_segment",
        "affected_scores": ["retention"],
        "lift": {"retention": 14},
        "why": "Repeated frames can signal stalled pacing.",
        "edit": "Remove repeated frames or shorten this beat.",
        "detected_by": ["rhythm_analyzer", "frame_similarity"],
    },
    "static_ending": {
        "issue_type": "static_ending",
        "action": "shorten_ending",
        "affected_scores": ["retention"],
        "lift": {"retention": 12},
        "why": "A static ending can leak retention after the payoff.",
        "edit": "Cut after the last strong beat or shorten the ending.",
        "detected_by": ["rhythm_analyzer", "ending_window"],
    },
    "credits_like_static_text_card": {
        "issue_type": "credits_like_segment",
        "action": "shorten_ending",
        "affected_scores": ["retention"],
        "lift": {"retention": 10},
        "why": "Static text-card or credits-like material may be a retention drag.",
        "edit": "Shorten or remove unless it directly supports the hook.",
        "detected_by": ["visual_analyzer", "edge_density"],
    },
    "credits_like_segment": {
        "issue_type": "credits_like_segment",
        "action": "shorten_ending",
        "affected_scores": ["retention"],
        "lift": {"retention": 10},
        "why": "Static text-card or credits-like material may be a retention drag.",
        "edit": "Shorten or remove unless it directly supports the hook.",
        "detected_by": ["rhythm_analyzer", "edge_density"],
    },
    "black_segment": {
        "issue_type": "black_segment",
        "action": "remove_segment",
        "affected_scores": ["retention"],
        "lift": {"retention": 18},
        "why": "Black frames create a strong retention risk.",
        "edit": "Remove the black section or replace it with visible action.",
        "detected_by": ["visual_analyzer", "brightness"],
    },
    "audio_too_quiet": {
        "issue_type": "audio_too_quiet",
        "action": "normalize_audio",
        "affected_scores": ["audio"],
        "lift": {"audio": 16},
        "why": "Quiet audio lowers perceived energy and can feel unfinished.",
        "edit": "Normalize audio toward a stronger short-form loudness target.",
        "detected_by": ["audio_analyzer", "volumedetect"],
    },
    "audio_too_loud": {
        "issue_type": "possible_clipping",
        "action": "normalize_audio",
        "affected_scores": ["audio"],
        "lift": {"audio": 10},
        "why": "Overly loud audio can distort and reduce perceived quality.",
        "edit": "Lower gain and check for clipping.",
        "detected_by": ["audio_analyzer", "volumedetect"],
    },
    "possible_clipping": {
        "issue_type": "possible_clipping",
        "action": "normalize_audio",
        "affected_scores": ["audio"],
        "lift": {"audio": 10},
        "why": "Peaks near 0 dB may clip after platform processing.",
        "edit": "Lower gain and check limiter/export settings.",
        "detected_by": ["audio_analyzer", "volumedetect"],
    },
    "no_audio": {
        "issue_type": "no_audio",
        "action": "boost_audio",
        "affected_scores": ["audio", "opening"],
        "lift": {"audio": 28, "opening": 8},
        "why": "Short-form clips usually need intentional sound to hold attention.",
        "edit": "Add music, voice, or intentional sound design before publishing.",
        "detected_by": ["audio_analyzer", "ffprobe"],
    },
    "silence_segment": {
        "issue_type": "silence_segment",
        "action": "remove_segment",
        "affected_scores": ["audio", "retention"],
        "lift": {"audio": 8, "retention": 4},
        "why": "Unexpected silent gaps can feel like dead time.",
        "edit": "Cut the silent gap, add intentional sound, or tighten the edit.",
        "detected_by": ["audio_analyzer", "silencedetect"],
    },
    "long_silence": {
        "issue_type": "silence_segment",
        "action": "remove_segment",
        "affected_scores": ["audio", "retention"],
        "lift": {"audio": 10, "retention": 4},
        "why": "Long silence reduces perceived energy.",
        "edit": "Cut long silent stretches or add intentional sound.",
        "detected_by": ["audio_analyzer", "silencedetect"],
    },
    "low_bitrate": {
        "issue_type": "low_bitrate",
        "action": "re_export",
        "affected_scores": ["technical"],
        "lift": {"technical": 18},
        "why": "Low bitrate can make otherwise good footage look cheap or fragile after upload.",
        "edit": "Re-export with a higher video bitrate before publishing.",
        "detected_by": ["video_probe", "scoring"],
    },
    "acceptable_but_low_bitrate": {
        "issue_type": "low_bitrate",
        "action": "re_export",
        "affected_scores": ["technical"],
        "lift": {"technical": 8},
        "why": "Bitrate is acceptable but still below the Strong Publish target.",
        "edit": "Use a higher bitrate export before aiming for Strong Publish.",
        "detected_by": ["video_probe", "scoring"],
    },
    "very_low_bitrate": {
        "issue_type": "very_low_bitrate",
        "action": "re_export",
        "affected_scores": ["technical"],
        "lift": {"technical": 22},
        "why": "Very low bitrate is a technical blocker for short-form quality.",
        "edit": "Re-export with a much higher video bitrate.",
        "detected_by": ["video_probe", "scoring"],
    },
    "horizontal_format": {
        "issue_type": "horizontal_source",
        "action": "crop_to_vertical",
        "affected_scores": ["format"],
        "lift": {"format": 24},
        "why": "Horizontal source footage is usually not final short-form creative.",
        "edit": "Crop or reframe to vertical 9:16, or analyze a shorter source clip.",
        "detected_by": ["video_probe", "scoring"],
    },
    "too_long_for_short_form": {
        "issue_type": "duration_too_long",
        "action": "analyze_as_source_clip",
        "affected_scores": ["format", "retention"],
        "lift": {"format": 20, "retention": 6},
        "why": "Long source footage should be clipped before spending a short-form slot.",
        "edit": "Extract a focused 20-45 second candidate and analyze that clip.",
        "detected_by": ["video_probe", "retention_analyzer"],
    },
    "too_short_to_develop": {
        "issue_type": "duration_too_short",
        "action": "keep",
        "affected_scores": ["format"],
        "lift": {"format": 8},
        "why": "Very short clips need instant hook and payoff.",
        "edit": "Use only if the hook and payoff are both immediate.",
        "detected_by": ["video_probe", "scoring"],
    },
    "soft_video": {
        "issue_type": "low_sharpness",
        "action": "re_export",
        "affected_scores": ["technical"],
        "lift": {"technical": 8},
        "why": "Soft video weakens perceived production value.",
        "edit": "Sharpen source/export quality before publishing.",
        "detected_by": ["visual_analyzer", "laplacian_sharpness"],
    },
    "very_soft_video": {
        "issue_type": "low_sharpness",
        "action": "re_export",
        "affected_scores": ["technical"],
        "lift": {"technical": 16},
        "why": "Very soft video is a strong technical risk.",
        "edit": "Use a sharper source or re-export with less compression.",
        "detected_by": ["visual_analyzer", "laplacian_sharpness"],
    },
    "active_content_too_small": {
        "issue_type": "low_active_content_area",
        "action": "zoom_in",
        "affected_scores": ["format", "technical"],
        "lift": {"format": 28, "technical": 8},
        "why": "Tiny active content wastes the mobile frame.",
        "edit": "Scale, crop, or redesign the composition so main content fills the vertical frame.",
        "detected_by": ["active_content", "composition"],
    },
    "active_content_weak": {
        "issue_type": "low_active_content_area",
        "action": "zoom_in",
        "affected_scores": ["format", "technical"],
        "lift": {"format": 18, "technical": 6},
        "why": "Weak active content area reduces mobile impact.",
        "edit": "Increase content size, crop tighter, or create a proper vertical composition.",
        "detected_by": ["active_content", "composition"],
    },
    "content_does_not_fill_vertical_frame": {
        "issue_type": "pillarbox_detected",
        "action": "reframe",
        "affected_scores": ["format"],
        "lift": {"format": 18},
        "why": "Black side areas signal a composition that is not native to vertical short-form.",
        "edit": "Reframe, crop, or scale content to fill more vertical space.",
        "detected_by": ["active_content", "black_border_ratio"],
    },
    "letterbox_detected": {
        "issue_type": "letterbox_detected",
        "action": "reframe",
        "affected_scores": ["format"],
        "lift": {"format": 16},
        "why": "Letterboxing wastes vertical screen area.",
        "edit": "Crop or rebuild the edit for a native vertical frame.",
        "detected_by": ["active_content", "black_border_ratio"],
    },
    "small_center_content": {
        "issue_type": "small_center_content",
        "action": "zoom_in",
        "affected_scores": ["format"],
        "lift": {"format": 18},
        "why": "Small centered content reduces mobile impact.",
        "edit": "Increase active content size, crop tighter, or redesign the layout.",
        "detected_by": ["active_content", "composition"],
    },
    "black_frames_dominate": {
        "issue_type": "black_segment",
        "action": "remove_segment",
        "affected_scores": ["retention", "technical"],
        "lift": {"retention": 30, "technical": 8},
        "why": "Black frames dominate the asset.",
        "edit": "Do not publish until black sections are removed or replaced.",
        "detected_by": ["visual_analyzer", "scoring"],
    },
    "static_video_dominates": {
        "issue_type": "static_segment",
        "action": "remove_segment",
        "affected_scores": ["retention"],
        "lift": {"retention": 28},
        "why": "Static frames dominate the asset.",
        "edit": "Cut down to the active segment before testing.",
        "detected_by": ["visual_analyzer", "scoring"],
    },
}


def _investment_lift(component_lift: dict) -> float:
    return round(sum(float(value) * SCORE_WEIGHTS.get(key, 0.0) for key, value in component_lift.items()), 1)


def _priority(issue_type: str, severity: str, investment_lift: float) -> str:
    p0 = {"black_segment", "no_audio", "low_active_content_area", "opening_black"}
    p1 = {
        "weak_opening",
        "low_visual_change_opening",
        "opening_silence",
        "low_bitrate",
        "very_low_bitrate",
        "static_ending",
        "dead_time_segment",
        "horizontal_source",
        "duration_too_long",
        "pillarbox_detected",
        "letterbox_detected",
        "small_center_content",
    }
    if severity == "critical" or issue_type in p0:
        return "P0"
    if severity == "high" or issue_type in p1 or investment_lift >= 3.0:
        return "P1"
    if severity == "medium":
        return "P2"
    return "P3"


def _confidence(source: dict, issue_type: str) -> str:
    if source.get("confidence"):
        return source["confidence"]
    if issue_type in {"low_visual_change_opening", "low_bitrate", "very_low_bitrate", "opening_silence", "audio_too_quiet"}:
        return "high"
    return "medium"


def _make_edit_point(source: dict, fallback_type: str | None = None) -> dict | None:
    source_type = source.get("issue_type") or fallback_type
    if not source_type:
        return None
    rule = TYPE_RULES.get(source_type)
    if not rule:
        return None

    issue_type = rule["issue_type"]
    severity = source.get("severity") or ("medium" if issue_type not in {"black_segment"} else "high")
    expected_lift = dict(rule["lift"])
    investment = _investment_lift(expected_lift)
    priority = _priority(issue_type, severity, investment)
    start = source.get("start_time")
    end = source.get("end_time")

    return {
        "id": "",
        "start_time": round(float(start), 2) if start is not None else None,
        "end_time": round(float(end), 2) if end is not None else None,
        "issue_type": issue_type,
        "severity": severity,
        "priority": priority,
        "action": rule["action"],
        "description": source.get("description") or source.get("reason") or issue_type.replace("_", " ").title(),
        "why_it_matters": rule["why"],
        "recommended_edit": source.get("recommendation") or rule["edit"],
        "expected_lift": {**expected_lift, "investment": investment},
        "affected_scores": list(rule["affected_scores"]),
        "difficulty": source.get("difficulty") or ("easy" if rule["action"] in {"cut", "compress", "remove_segment", "shorten_ending", "normalize_audio"} else "medium"),
        "confidence": _confidence(source, issue_type),
        "detected_by": list(rule["detected_by"]),
        "source": "deterministic",
    }


def _overlap(a: dict, b: dict) -> bool:
    if a.get("start_time") is None or a.get("end_time") is None or b.get("start_time") is None or b.get("end_time") is None:
        return False
    return max(a["start_time"], b["start_time"]) <= min(a["end_time"], b["end_time"])


def _better(a: dict, b: dict) -> dict:
    a_key = (PRIORITY_RANK.get(a["priority"], 4), SEVERITY_RANK.get(a["severity"], 4), -float(a["expected_lift"].get("investment") or 0))
    b_key = (PRIORITY_RANK.get(b["priority"], 4), SEVERITY_RANK.get(b["severity"], 4), -float(b["expected_lift"].get("investment") or 0))
    return a if a_key <= b_key else b


def _dedupe(edit_points: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    related_groups = [
        {"opening_silence"},
        {"weak_opening", "low_visual_change_opening", "opening_static"},
        {"static_segment", "dead_time_segment", "repeated_frame_segment", "low_motion_segment"},
        {"low_active_content_area", "pillarbox_detected", "letterbox_detected", "small_center_content"},
    ]
    for point in edit_points:
        replaced = False
        for index, existing in enumerate(deduped):
            same_type = point["issue_type"] == existing["issue_type"]
            related = any(point["issue_type"] in group and existing["issue_type"] in group for group in related_groups)
            same_time = (
                same_type
                and (point.get("start_time") is None or existing.get("start_time") is None)
            ) or _overlap(point, existing)
            if (same_type or related) and same_time:
                kept = _better(point, existing)
                merged_detected_by = sorted(set(point.get("detected_by", [])) | set(existing.get("detected_by", [])))
                kept["detected_by"] = merged_detected_by
                deduped[index] = kept
                replaced = True
                break
        if not replaced:
            deduped.append(point)
    opening_points = [
        point
        for point in deduped
        if point["issue_type"] in {"weak_opening", "low_visual_change_opening", "opening_black", "opening_silence"}
    ]
    filtered = []
    for point in deduped:
        if (
            point["issue_type"] in {"static_segment", "dead_time_segment", "repeated_frame_segment", "low_motion_segment"}
            and point.get("start_time") is not None
            and point["start_time"] < 2.0
            and any(_overlap(point, opening) for opening in opening_points)
        ):
            continue
        filtered.append(point)
    return filtered


def _source_items(analyses: dict, scores: dict) -> list[dict]:
    items = []
    items.extend(analyses.get("opening", {}).get("opening_issues", []))
    items.extend(analyses.get("retention", {}).get("drawdown_segments", []))
    items.extend(analyses.get("rhythm", {}).get("segments", []))
    items.extend(analyses.get("audio", {}).get("audio_issues", []))
    for segment in analyses.get("audio", {}).get("audio_drop_segments", []):
        items.append(
            {
                "issue_type": "silence_segment",
                "severity": "medium" if segment.get("duration", 0) < 3 else "high",
                "start_time": segment.get("start_time"),
                "end_time": segment.get("end_time"),
                "description": "Audio drops to silence or low energy.",
                "recommendation": "Cut the silent gap, add intentional sound, or tighten the edit.",
            }
        )
    items.extend(analyses.get("visual", {}).get("issues", []))
    items.extend(scores.get("technical_issues", []))
    items.extend(scores.get("format_issues", []))
    items.extend(scores.get("critical_issues", []))
    return items


def generate_edit_points(clip: dict, analyses: dict, scores: dict, recommendations: dict | None = None) -> list[dict]:
    edit_points = []
    for item in _source_items(analyses, scores):
        point = _make_edit_point(item)
        if point:
            edit_points.append(point)

    edit_points = _dedupe(edit_points)
    cap_reasons = " ".join((scores.get("verdict_cap") or {}).get("cap_reasons", [])).lower()
    for point in edit_points:
        issue_type = point["issue_type"]
        point["cap_related"] = bool(
            ("bitrate" in cap_reasons and issue_type in {"low_bitrate", "very_low_bitrate"})
            or (("opening" in cap_reasons or "first half-second" in cap_reasons) and issue_type in {"weak_opening", "low_visual_change_opening", "opening_black", "opening_silence"})
            or ("active content" in cap_reasons and issue_type in {"low_active_content_area", "pillarbox_detected", "letterbox_detected", "small_center_content"})
            or (("static" in cap_reasons or "motion" in cap_reasons) and issue_type in {"static_segment", "dead_time_segment", "repeated_frame_segment", "low_motion_segment"})
        )
    edit_points.sort(
        key=lambda item: (
            PRIORITY_RANK.get(item["priority"], 4),
            0 if item.get("cap_related") else 1,
            -float(item.get("expected_lift", {}).get("investment") or 0),
            SEVERITY_RANK.get(item["severity"], 4),
            item["start_time"] if item["start_time"] is not None else 999999,
        )
    )
    for index, point in enumerate(edit_points, start=1):
        point["id"] = f"edit_{index:03d}"
    return edit_points


def _fixed_issue_types(edit_points: list[dict], priorities: set[str]) -> set[str]:
    return {point["issue_type"] for point in edit_points if point.get("priority") in priorities}


def _cap_reasons_remaining(cap_reasons: list[str], fixed_types: set[str]) -> list[str]:
    remaining = []
    for reason in cap_reasons:
        lower = reason.lower()
        fixed = False
        if "bitrate" in lower and {"low_bitrate", "very_low_bitrate"} & fixed_types:
            fixed = True
        if ("opening" in lower or "first half-second" in lower) and {"weak_opening", "low_visual_change_opening", "opening_black", "opening_silence"} & fixed_types:
            fixed = True
        if "active content" in lower and {"low_active_content_area", "pillarbox_detected", "letterbox_detected", "small_center_content"} & fixed_types:
            fixed = True
        if ("static" in lower or "motion" in lower) and {"static_segment", "dead_time_segment", "repeated_frame_segment", "low_motion_segment"} & fixed_types:
            fixed = True
        if not fixed:
            remaining.append(reason)
    return remaining


def estimate_after_fixes(score_result: dict, edit_points: list[dict]) -> dict:
    current = float(score_result.get("investment_score") or 0)
    p0_lift = sum(float(point.get("expected_lift", {}).get("investment") or 0) for point in edit_points if point.get("priority") == "P0")
    p0_p1_lift = sum(
        float(point.get("expected_lift", {}).get("investment") or 0)
        for point in edit_points
        if point.get("priority") in {"P0", "P1"}
    )
    after_p0 = round(min(100.0, current + p0_lift), 1)
    after_p0_p1 = round(min(100.0, current + p0_p1_lift), 1)

    cap = score_result.get("verdict_cap") or {}
    remaining_cap_reasons = _cap_reasons_remaining(cap.get("cap_reasons", []), _fixed_issue_types(edit_points, {"P0", "P1"}))
    if remaining_cap_reasons and cap.get("applied"):
        estimated_verdict = score_result.get("verdict")
    else:
        estimated_verdict = verdict_for_score(after_p0_p1)

    return {
        "current_score": round(current, 1),
        "estimated_after_p0": after_p0,
        "estimated_after_p0_p1": after_p0_p1,
        "estimated_verdict_after_p0_p1": estimated_verdict,
        "remaining_cap_reasons_after_p0_p1": remaining_cap_reasons,
        "notes": "Formula-based estimate, not historically validated.",
    }
