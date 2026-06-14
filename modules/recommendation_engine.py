from config import SCORE_WEIGHTS, THRESHOLDS
from modules.scoring import estimate_formula_lift


ISSUE_DEFAULTS = {
    "weak_entry_point": ("opening", 18, "Cut the slow opening or add a strong first-frame hook.", "easy"),
    "opening_black": ("opening", 22, "Cut the dark opening or replace it with a visible first frame.", "easy"),
    "opening_low_visual_change": ("opening", 10, "Cut the first beat tighter or add a stronger first-frame hook.", "easy"),
    "opening_silence": ("opening", 16, "Start with immediate audio or cut to the first audible moment.", "easy"),
    "soft_first_frame": ("opening", 8, "Use a sharper first frame.", "medium"),
    "dark_first_frame": ("opening", 7, "Start on a brighter moment or grade the opening.", "medium"),
    "static_segment": ("retention", 14, "Remove or compress this static segment.", "easy"),
    "low_motion_segment": ("retention", 10, "Add a cut, zoom, caption beat, or remove the segment.", "medium"),
    "black_segment": ("retention", 18, "Remove the black section or replace it with visible action.", "easy"),
    "credits_like_static_text_card": ("retention", 10, "Shorten or remove this static text-card unless it is essential.", "easy"),
    "audio_too_quiet": ("audio", 16, "Normalize audio toward a stronger short-form loudness target.", "easy"),
    "audio_too_loud": ("audio", 12, "Lower gain and check for clipping.", "easy"),
    "no_audio": ("audio", 28, "Add music, voice, or intentional sound design.", "medium"),
    "long_silence": ("audio", 12, "Cut long silent stretches or add intentional sound.", "easy"),
    "very_low_bitrate": ("technical", 22, "Re-export with a much higher video bitrate.", "medium"),
    "low_bitrate": ("technical", 18, "Re-export with a higher video bitrate.", "medium"),
    "acceptable_but_low_bitrate": ("technical", 8, "Use a higher bitrate export before aiming for Strong Publish.", "easy"),
    "low_resolution": ("technical", 10, "Use a higher-resolution source or export.", "medium"),
    "very_soft_video": ("technical", 16, "Use a sharper source or re-export with less compression.", "medium"),
    "soft_video": ("technical", 8, "Sharpen source/export quality before publishing.", "medium"),
    "horizontal_format": ("format", 24, "Use as long-form source or reframe to vertical 9:16.", "medium"),
    "non_vertical_format": ("format", 14, "Reframe to vertical 9:16.", "medium"),
    "too_long_for_short_form": ("format", 20, "Extract a 20-45 second short-form candidate.", "medium"),
    "too_short_to_develop": ("format", 10, "Use only if hook and payoff are immediate.", "medium"),
    "active_content_too_small": ("format", 28, "Scale, crop, or redesign the composition so the main content fills the vertical frame.", "medium"),
    "active_content_weak": ("format", 18, "Increase active content size, crop tighter, or create a proper vertical composition.", "medium"),
    "active_content_acceptable_not_strong": ("format", 8, "Fill more of the frame before aiming for Strong Publish.", "easy"),
    "content_does_not_fill_vertical_frame": ("format", 18, "Reframe, crop, or scale content to fill more vertical space.", "medium"),
    "letterbox_detected": ("format", 16, "Crop or rebuild the edit for a native vertical frame.", "medium"),
    "small_center_content": ("format", 18, "Increase active content size, crop tighter, or redesign the vertical layout.", "medium"),
    "black_frames_dominate": ("retention", 30, "Do not publish until black sections are removed.", "medium"),
    "static_video_dominates": ("retention", 28, "Cut down to the active segment before testing.", "medium"),
}


def _priority(severity: str, lift: float, issue_type: str) -> str:
    p0_types = {
        "active_content_too_small",
        "black_frames_dominate",
        "static_video_dominates",
        "no_audio",
        "weak_entry_point",
    }
    p1_types = {
        "very_low_bitrate",
        "low_bitrate",
        "content_does_not_fill_vertical_frame",
        "small_center_content",
        "letterbox_detected",
        "opening_silence",
        "horizontal_format",
        "too_long_for_short_form",
    }
    if severity == "critical" or issue_type in p0_types:
        return "P0"
    if issue_type in p1_types or severity == "high" or lift >= 5:
        return "P1"
    if severity == "medium":
        return "P2"
    return "P3"


def _why(issue_type: str) -> str:
    if "opening" in issue_type or issue_type in {"weak_entry_point", "dark_first_frame", "soft_first_frame"}:
        return "The first seconds decide whether the clip earns the publishing slot."
    if "audio" in issue_type or "silence" in issue_type or issue_type == "no_audio":
        return "Weak audio lowers perceived energy and can delay engagement."
    if "active_content" in issue_type or issue_type in {"content_does_not_fill_vertical_frame", "letterbox_detected", "small_center_content"}:
        return "Small or bordered content weakens mobile impact even inside a 1080x1920 container."
    if "format" in issue_type or issue_type in {"horizontal_format", "too_long_for_short_form", "too_short_to_develop"}:
        return "Format mismatch makes the asset less fit for generic short-form distribution."
    if "bitrate" in issue_type or "resolution" in issue_type or "soft" in issue_type:
        return "Technical quality affects trust and watchability."
    return "This section may create avoidable retention loss."


def _normalize_issue(source: dict, fallback_type: str | None = None) -> dict:
    issue_type = source.get("issue_type") or fallback_type or "unknown_issue"
    affected, component_lift, fallback_recommendation, difficulty = ISSUE_DEFAULTS.get(
        issue_type,
        ("retention", 8, source.get("recommendation") or "Review and tighten this section.", "medium"),
    )
    if "component_lift" in source:
        component_lift = source["component_lift"]
    lift = estimate_formula_lift(affected, component_lift)
    severity = source.get("severity") or "medium"
    recommendation = source.get("recommendation") or fallback_recommendation
    return {
        "priority": _priority(severity, lift, issue_type),
        "issue_type": issue_type,
        "severity": severity,
        "start_time": source.get("start_time"),
        "end_time": source.get("end_time"),
        "description": source.get("description") or source.get("reason") or issue_type.replace("_", " ").title(),
        "why_it_matters": _why(issue_type),
        "recommendation": recommendation,
        "expected_score_lift": lift,
        "expected_lift_note": "Estimated formula lift, not a historical prediction.",
        "affected_score": affected,
        "difficulty": source.get("difficulty") or difficulty,
    }


def _dedupe(issues: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for issue in issues:
        key = (
            issue.get("issue_type"),
            round(float(issue["start_time"]), 1) if issue.get("start_time") is not None else None,
            round(float(issue["end_time"]), 1) if issue.get("end_time") is not None else None,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(issue)
    return unique


def _component_label(component: str) -> str:
    labels = {
        "opening": "Opening / entry point",
        "retention": "Retention timeline",
        "technical": "Technical quality",
        "audio": "Audio quality",
        "format": "Short-form format fit",
    }
    return labels.get(component, component.title())


def build_recommendations(clip: dict, analyses: dict, score_result: dict) -> dict:
    issues = []

    for item in analyses.get("opening", {}).get("opening_issues", []):
        issues.append(_normalize_issue(item))
    for item in analyses.get("retention", {}).get("drawdown_segments", []):
        issues.append(_normalize_issue(item))
    for item in analyses.get("audio", {}).get("audio_issues", []):
        issues.append(_normalize_issue(item))
    for item in analyses.get("visual", {}).get("issues", []):
        issues.append(_normalize_issue(item))
    for item in score_result.get("technical_issues", []):
        issues.append(_normalize_issue(item))
    for item in score_result.get("format_issues", []):
        issues.append(_normalize_issue(item))
    for item in score_result.get("critical_issues", []):
        issues.append(_normalize_issue(item))

    metadata = analyses.get("metadata", {})
    aspect = metadata.get("aspect_ratio")
    duration = metadata.get("duration") or 0
    if aspect is not None and aspect < 1.0:
        issues.append(
            _normalize_issue(
                {
                    "issue_type": "horizontal_format",
                    "severity": "high",
                    "description": "The clip is horizontal, not vertical short-form.",
                    "recommendation": "Use this as a source asset, then crop or reframe a vertical 9:16 clip.",
                }
            )
        )
    if duration > THRESHOLDS["max_short_duration"]:
        issues.append(
            _normalize_issue(
                {
                    "issue_type": "too_long_for_short_form",
                    "severity": "high",
                    "start_time": THRESHOLDS["max_short_duration"],
                    "end_time": duration,
                    "description": "The clip is longer than the v0.1 short-form target.",
                    "recommendation": "Extract a focused 20-45 second candidate before publishing.",
                }
            )
        )

    weak_points = _dedupe(issues)
    weak_points.sort(
        key=lambda item: (
            {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(item["priority"], 4),
            -float(item.get("expected_score_lift") or 0),
        )
    )

    scores = score_result.get("scores", {})
    components = ["opening", "retention", "technical", "audio", "format"]
    bottleneck_key = min(components, key=lambda key: scores.get(key, 0)) if scores else "opening"
    main_bottleneck = {
        "component": bottleneck_key,
        "label": _component_label(bottleneck_key),
        "score": scores.get(bottleneck_key),
        "description": f"{_component_label(bottleneck_key)} is the lowest weighted component.",
        "formula_weight": SCORE_WEIGHTS.get(bottleneck_key),
    }

    best_fix = weak_points[0] if weak_points else {
        "priority": "P3",
        "issue_type": "no_major_weak_point",
        "severity": "low",
        "description": "No major deterministic weak point was found.",
        "why_it_matters": "The MVP can only judge deterministic proxies.",
        "recommendation": "Review creative context manually before spending a publishing slot.",
        "expected_score_lift": 0.0,
        "affected_score": "risk",
        "difficulty": "manual",
    }
    total_lift = sum(float(item.get("expected_score_lift") or 0) for item in weak_points[:3])
    expected_after = min(100.0, float(score_result.get("investment_score") or 0) + total_lift)

    return {
        "weak_points": weak_points,
        "improvement_plan": weak_points[:5],
        "main_bottleneck": main_bottleneck,
        "best_fix": best_fix,
        "expected_score_after_fixes": round(expected_after, 1),
        "expected_score_note": "Formula-based estimate after the top fixes; not historically validated.",
    }
