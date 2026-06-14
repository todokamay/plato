from config import SCORE_WEIGHTS, THRESHOLDS
from modules.verdict_resolver import verdict_from_score


VERDICT_RANK = {
    "REJECT": 0,
    "HOLD": 1,
    "HOLD / CLIP FIRST": 1.5,
    "REWORK": 2,
    "SAFE TO TEST": 3,
    "PUBLISH": 4,
    "STRONG PUBLISH": 5,
}


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def verdict_for_score(score: float) -> str:
    return verdict_from_score(score)


def formula_score(scores: dict, critical_penalty: float = 0.0) -> float:
    weighted = (
        SCORE_WEIGHTS["opening"] * scores.get("opening", 0)
        + SCORE_WEIGHTS["retention"] * scores.get("retention", 0)
        + SCORE_WEIGHTS["technical"] * scores.get("technical", 0)
        + SCORE_WEIGHTS["audio"] * scores.get("audio", 0)
        + SCORE_WEIGHTS["format"] * scores.get("format", 0)
    )
    return round(clamp(weighted - critical_penalty), 1)


def estimate_formula_lift(affected_score: str, component_lift: float) -> float:
    key = (affected_score or "").lower()
    return round(float(component_lift) * SCORE_WEIGHTS.get(key, 0.0), 1)


def _issue(issue_type: str, severity: str, description: str, recommendation: str, component_lift: float) -> dict:
    return {
        "issue_type": issue_type,
        "severity": severity,
        "description": description,
        "recommendation": recommendation,
        "component_lift": component_lift,
    }


def _technical_score(metadata: dict, visual_analysis: dict) -> tuple[float, list[dict]]:
    score = 100.0
    issues = []
    bitrate = metadata.get("video_bitrate_kbps")
    width = metadata.get("width") or 0
    height = metadata.get("height") or 0
    fps = metadata.get("fps") or 0
    sharpness = visual_analysis.get("avg_sharpness") or 0
    active_content = visual_analysis.get("active_content") or {}
    active_ratio = active_content.get("active_content_ratio")

    if bitrate is None:
        score -= 10
        issues.append(_issue("missing_bitrate", "low", "Video bitrate was not readable.", "Inspect export settings.", 6))
    elif bitrate < THRESHOLDS["very_low_video_bitrate_kbps"]:
        score -= 30
        issues.append(
            _issue(
                "very_low_bitrate",
                "high",
                f"Video bitrate is very low at {bitrate:.1f} kbps.",
                "Re-export with a much higher video bitrate.",
                22,
            )
        )
    elif bitrate < THRESHOLDS["min_video_bitrate_kbps"]:
        score -= 24
        issues.append(
            _issue(
                "low_bitrate",
                "medium",
                f"Video bitrate is low at {bitrate:.1f} kbps.",
                "Re-export with a higher video bitrate.",
                18,
            )
        )
    elif bitrate < THRESHOLDS["preferred_video_bitrate_kbps"]:
        score -= 10
        issues.append(
            _issue(
                "acceptable_but_low_bitrate",
                "low",
                f"Video bitrate is below the preferred target at {bitrate:.1f} kbps.",
                "Use a higher bitrate export before aiming for Strong Publish.",
                8,
            )
        )

    if active_ratio is not None:
        if active_ratio < 0.40:
            score -= 12
        elif active_ratio < 0.55:
            score -= 8
        elif active_ratio < 0.70:
            score -= 4

    if min(width, height) and min(width, height) < 720:
        score -= 12
        issues.append(_issue("low_resolution", "medium", "Resolution is below a practical short-form floor.", "Use a higher-resolution source or export.", 10))
    if fps and (fps < 20 or fps > 61):
        score -= 8
        issues.append(_issue("fps_outlier", "low", "Frame rate is outside the expected range.", "Check the source/export frame rate.", 6))

    if sharpness < THRESHOLDS["sharpness_bad"]:
        score -= 20
        issues.append(_issue("very_soft_video", "high", "Sampled frames are very soft.", "Use a sharper source or re-export with less compression.", 16))
    elif sharpness < THRESHOLDS["sharpness_ok"]:
        score -= 10
        issues.append(_issue("soft_video", "medium", "Sampled frames are somewhat soft.", "Sharpen source/export quality before publishing.", 8))

    return clamp(score), issues


def _audio_score(audio_analysis: dict) -> float:
    if not audio_analysis.get("has_audio"):
        return 45.0
    score = 100.0
    mean_volume = audio_analysis.get("mean_volume_db")
    silence_ratio = audio_analysis.get("silence_ratio")

    if mean_volume is None:
        score -= 12
    elif mean_volume < -25:
        score -= min(28, abs(mean_volume + 25) * 2 + 12)
    elif mean_volume > -10:
        score -= min(24, abs(mean_volume + 10) * 2 + 10)

    if audio_analysis.get("opening_silence"):
        score -= 20
    if silence_ratio is not None and silence_ratio > 0.25:
        score -= min(22, silence_ratio * 45)
    return clamp(score)


def _format_score(metadata: dict, visual_analysis: dict) -> tuple[float, list[dict]]:
    score = 100.0
    issues = []
    aspect = metadata.get("aspect_ratio")
    duration = metadata.get("duration") or 0
    active_content = visual_analysis.get("active_content") or {}
    active_ratio = active_content.get("active_content_ratio")

    if aspect is None:
        score -= 15
        issues.append(_issue("unknown_aspect_ratio", "medium", "Aspect ratio was not readable.", "Inspect the source file.", 8))
    else:
        diff = abs(aspect - THRESHOLDS["vertical_aspect_target"])
        if aspect < 1.0:
            score -= 35
            issues.append(_issue("horizontal_format", "high", "The clip is horizontal, not vertical short-form.", "Use as long-form source or reframe to vertical 9:16.", 24))
        elif diff > 0.4:
            score -= 20
            issues.append(_issue("non_vertical_format", "medium", "The frame shape is not a clean vertical short.", "Reframe to vertical 9:16.", 14))
        elif diff > 0.15:
            score -= 8
            issues.append(_issue("imperfect_vertical_format", "low", "The frame shape is slightly off the vertical target.", "Export as a clean 9:16 vertical frame.", 6))

    if active_ratio is not None:
        if active_ratio < 0.40:
            score -= 30
            issues.append(
                _issue(
                    "active_content_too_small",
                    "critical",
                    "Active content fills less than 40% of the frame.",
                    "Scale, crop, or redesign the composition so the main content fills the vertical frame.",
                    28,
                )
            )
        elif active_ratio < 0.55:
            score -= 15
            issues.append(
                _issue(
                    "active_content_weak",
                    "high",
                    "Active content fills only part of the frame.",
                    "Increase active content size, crop tighter, or create a proper vertical composition.",
                    18,
                )
            )
        elif active_ratio < 0.70:
            score -= 5
            issues.append(
                _issue(
                    "active_content_acceptable_not_strong",
                    "medium",
                    "Active content area is acceptable but not strong.",
                    "Fill more of the frame before aiming for Strong Publish.",
                    8,
                )
            )

    if duration > THRESHOLDS["max_short_duration"]:
        score -= 25
        issues.append(_issue("too_long_for_short_form", "high", "Duration is above the short-form target.", "Extract a 20-45 second short-form candidate.", 20))
    elif duration > THRESHOLDS["ideal_max_duration"]:
        score -= 8
        issues.append(_issue("slightly_long", "low", "Duration is slightly above the ideal target.", "Tighten the edit if retention weakens.", 6))
    elif duration and duration < 8:
        score -= 15
        issues.append(_issue("too_short_to_develop", "medium", "The clip may be too short to develop payoff.", "Use only if hook and payoff are immediate.", 10))
    elif duration and duration < THRESHOLDS["ideal_min_duration"]:
        score -= 6
        issues.append(_issue("short_but_possible", "low", "The clip is shorter than the ideal range.", "Confirm the payoff lands quickly.", 4))

    return clamp(score), issues


def _severity_counts(issues: list[dict]) -> dict:
    return {
        "critical": sum(1 for issue in issues if issue.get("severity") == "critical"),
        "high": sum(1 for issue in issues if issue.get("severity") == "high"),
        "medium": sum(1 for issue in issues if issue.get("severity") == "medium"),
    }


def _requirement(label: str, passed: bool, detail: str) -> dict:
    return {"label": label, "passed": bool(passed), "detail": detail}


def _cap_message(max_verdict: str, reasons: list[str]) -> str:
    return f"Verdict capped to {max_verdict} because " + " and ".join(reasons) + "."


def apply_verdict_caps(raw_verdict: str, investment_score: float, scores: dict, issues: list[dict], metrics: dict) -> dict:
    verdict = raw_verdict
    reasons = []
    cap_messages = []

    def cap_to(max_verdict: str, reason: str) -> None:
        nonlocal verdict
        reasons.append(reason)
        if VERDICT_RANK.get(verdict, 0) > VERDICT_RANK[max_verdict]:
            verdict = max_verdict

    bitrate = metrics.get("video_bitrate_kbps")
    active_ratio = metrics.get("active_content_ratio")
    duration = metrics.get("duration") or 0
    aspect = metrics.get("aspect_ratio")
    black_ratio = metrics.get("black_ratio") or 0
    static_ratio = metrics.get("static_ratio") or 0
    opening_static = metrics.get("opening_static")
    opening_black = metrics.get("opening_black")
    opening_first_half_static = metrics.get("opening_first_half_static")

    counts = _severity_counts(issues)
    issue_types = {issue.get("issue_type") for issue in issues}

    preferred_bitrate = THRESHOLDS["preferred_video_bitrate_kbps"]
    minimum_bitrate = THRESHOLDS["min_video_bitrate_kbps"]
    strong_requirements = [
        _requirement("Raw score at least 90", investment_score >= 90, f"Raw score is {investment_score}."),
        _requirement("No critical issues", counts["critical"] == 0, f"{counts['critical']} critical issue(s)."),
        _requirement("No high severity issues", counts["high"] == 0, f"{counts['high']} high issue(s)."),
        _requirement("No more than one medium issue", counts["medium"] <= 1, f"{counts['medium']} medium issue(s)."),
        _requirement("Preferred bitrate", bitrate is not None and bitrate >= preferred_bitrate, f"Bitrate is {bitrate if bitrate is not None else '-'} kbps."),
        _requirement("Opening score at least 85", scores.get("opening", 0) >= 85, f"Opening score is {scores.get('opening', 0)}."),
        _requirement("Retention score at least 85", scores.get("retention", 0) >= 85, f"Retention score is {scores.get('retention', 0)}."),
        _requirement("Format score at least 85", scores.get("format", 0) >= 85, f"Format score is {scores.get('format', 0)}."),
        _requirement("Active content fills at least 70%", active_ratio is None or active_ratio >= 0.70, f"Active content ratio is {active_ratio if active_ratio is not None else 'not available'}."),
        _requirement("Low black/static ratios", black_ratio < 0.20 and static_ratio < 0.45, f"Black ratio {black_ratio}, static ratio {static_ratio}."),
    ]

    if "black_frames_dominate" in issue_types or "static_video_dominates" in issue_types or "no_readable_video" in issue_types:
        cap_to("REJECT", "a critical unreadable, black, or static-video issue is present")
    if duration > THRESHOLDS["max_short_duration"] and aspect is not None and aspect < 1.0:
        cap_to("HOLD / CLIP FIRST", "the asset is long horizontal source footage")
    elif duration > THRESHOLDS["max_short_duration"]:
        cap_to("HOLD", "duration is above the short-form target")
    elif aspect is not None and aspect < 1.0:
        cap_to("HOLD / CLIP FIRST", "the asset is horizontal source footage")

    if active_ratio is not None:
        if active_ratio < 0.40:
            cap_to("REWORK", f"active content fills only {active_ratio * 100:.0f}% of the frame")
        elif active_ratio < 0.55:
            cap_to("REWORK", f"active content fills only {active_ratio * 100:.0f}% of the frame")
        elif active_ratio < 0.70:
            cap_to("PUBLISH", f"active content fills {active_ratio * 100:.0f}% of the frame")

    if bitrate is not None:
        if bitrate < THRESHOLDS["very_low_video_bitrate_kbps"]:
            cap_to("REWORK", f"video bitrate is very low at {bitrate:.0f} kbps")
        elif bitrate < minimum_bitrate:
            cap_to("SAFE TO TEST", f"video bitrate is low at {bitrate:.0f} kbps")
        elif bitrate < preferred_bitrate:
            cap_to("PUBLISH", f"video bitrate is below the preferred {preferred_bitrate} kbps target")

    if opening_static:
        cap_to("REWORK", "the first two seconds are static or low motion")
    elif opening_first_half_static:
        cap_to("PUBLISH", "the first half-second has low visual change")
    if opening_black:
        cap_to("REWORK", "the opening is black or too dark")
    if scores.get("opening", 0) < 60:
        cap_to("REWORK", f"opening score is {scores.get('opening', 0)}")
    elif scores.get("opening", 0) < 70:
        cap_to("SAFE TO TEST", f"opening score is {scores.get('opening', 0)}")
    if scores.get("retention", 0) < 70:
        cap_to("SAFE TO TEST", f"retention score is {scores.get('retention', 0)}")

    if counts["high"] > 0:
        cap_to("SAFE TO TEST", f"{counts['high']} high severity issue(s) are present")
    if counts["medium"] > 1 and verdict == "STRONG PUBLISH":
        cap_to("PUBLISH", f"{counts['medium']} medium severity issues are present")

    strong_blocks = [item for item in strong_requirements if not item["passed"]]
    if verdict == "STRONG PUBLISH" and strong_blocks:
        cap_to("PUBLISH", "Strong Publish requirements are not fully met")

    unique_reasons = []
    for reason in reasons:
        if reason not in unique_reasons:
            unique_reasons.append(reason)
    if verdict != raw_verdict and unique_reasons:
        cap_messages.append(_cap_message(verdict, unique_reasons[:3]))

    return {
        "final_verdict": verdict,
        "applied": verdict != raw_verdict,
        "raw_verdict": raw_verdict,
        "raw_score": investment_score,
        "cap_reasons": unique_reasons,
        "cap_messages": cap_messages,
        "strong_publish_requirements": strong_requirements,
        "strong_publish_blockers": strong_blocks,
    }


def _collect_issues(
    visual_analysis: dict,
    audio_analysis: dict,
    opening_analysis: dict,
    retention_analysis: dict,
    technical_issues: list[dict],
    format_issues: list[dict],
    critical_issues: list[dict],
) -> list[dict]:
    issues = []
    issues.extend(opening_analysis.get("opening_issues", []))
    issues.extend(retention_analysis.get("drawdown_segments", []))
    issues.extend(audio_analysis.get("audio_issues", []))
    issues.extend(visual_analysis.get("issues", []))
    issues.extend(technical_issues)
    issues.extend(format_issues)
    issues.extend(critical_issues)
    return issues


def score_clip(
    metadata: dict,
    visual_analysis: dict,
    audio_analysis: dict,
    opening_analysis: dict,
    retention_analysis: dict,
) -> dict:
    critical_issues = []
    technical_issues = []
    format_issues = []

    if not metadata.get("ok", True):
        scores = {
            "opening": 0.0,
            "retention": 0.0,
            "technical": 0.0,
            "audio": 0.0,
            "format": 0.0,
            "risk": 0.0,
        }
        critical = {
            "issue_type": "no_readable_video",
            "severity": "critical",
            "description": metadata.get("error") or "No readable video stream.",
        }
        return {
            "investment_score": 0.0,
            "raw_investment_score": 0.0,
            "verdict": "REJECT",
            "raw_verdict": "REJECT",
            "verdict_cap": {
                "applied": False,
                "raw_verdict": "REJECT",
                "final_verdict": "REJECT",
                "raw_score": 0.0,
                "cap_reasons": ["No readable video stream."],
                "cap_messages": [],
                "strong_publish_requirements": [],
                "strong_publish_blockers": [],
            },
            "scores": scores,
            "penalties": {"critical_penalty": 100.0},
            "critical_issues": [critical],
            "technical_issues": technical_issues,
            "format_issues": format_issues,
            "all_issues": [critical],
        }

    technical_score, technical_issues = _technical_score(metadata, visual_analysis)
    format_score, format_issues = _format_score(metadata, visual_analysis)
    audio_score = _audio_score(audio_analysis)

    opening_score = clamp(opening_analysis.get("opening_score", 0))
    retention_score = clamp(retention_analysis.get("retention_score", 0))
    critical_penalty = 0.0

    black_ratio = visual_analysis.get("black_ratio") or 0
    static_ratio = visual_analysis.get("static_ratio") or 0
    active_content = visual_analysis.get("active_content") or {}

    if black_ratio >= 0.65:
        critical_penalty += 45
        critical_issues.append(
            {
                "issue_type": "black_frames_dominate",
                "severity": "critical",
                "description": "Most sampled frames are near black.",
                "recommendation": "Do not publish until black sections are removed.",
            }
        )
    if static_ratio >= 0.85:
        critical_penalty += 35
        critical_issues.append(
            {
                "issue_type": "static_video_dominates",
                "severity": "critical",
                "description": "Static frames dominate the sampled timeline.",
                "recommendation": "Cut down to the active segment before testing.",
            }
        )

    scores = {
        "opening": round(opening_score, 1),
        "retention": round(retention_score, 1),
        "technical": round(technical_score, 1),
        "audio": round(audio_score, 1),
        "format": round(format_score, 1),
        "risk": round(clamp(100 - critical_penalty), 1),
    }
    investment = formula_score(scores, critical_penalty)
    raw_verdict = verdict_for_score(investment)

    all_issues = _collect_issues(
        visual_analysis,
        audio_analysis,
        opening_analysis,
        retention_analysis,
        technical_issues,
        format_issues,
        critical_issues,
    )
    metrics = {
        "video_bitrate_kbps": metadata.get("video_bitrate_kbps"),
        "duration": metadata.get("duration"),
        "aspect_ratio": metadata.get("aspect_ratio"),
        "black_ratio": black_ratio,
        "static_ratio": static_ratio,
        "active_content_ratio": active_content.get("active_content_ratio"),
        "opening_static": opening_analysis.get("opening_static"),
        "opening_black": opening_analysis.get("opening_black"),
        "opening_first_half_static": opening_analysis.get("opening_first_half_static"),
    }
    cap_result = apply_verdict_caps(raw_verdict, investment, scores, all_issues, metrics)

    return {
        "investment_score": investment,
        "raw_investment_score": investment,
        "verdict": cap_result["final_verdict"],
        "raw_verdict": raw_verdict,
        "verdict_cap": cap_result,
        "strong_publish_requirements": cap_result["strong_publish_requirements"],
        "scores": scores,
        "penalties": {"critical_penalty": round(critical_penalty, 1)},
        "critical_issues": critical_issues,
        "technical_issues": technical_issues,
        "format_issues": format_issues,
        "all_issues": all_issues,
    }
