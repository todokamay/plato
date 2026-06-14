from __future__ import annotations

from pathlib import Path


SAFE_PRIORITIES = {"P0", "P1", "P2"}
SAFE_CONFIDENCE = {"medium", "high"}
MIN_DURATION_AFTER_CUT = 8.0
MAX_SEGMENT_REMOVE_SECONDS = 5.0


def _as_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _duration(report_json: dict) -> float:
    overview = report_json.get("asset_overview") or {}
    metadata = (report_json.get("technical_quality") or {}).get("metadata") or {}
    return _as_float(overview.get("duration"), _as_float(metadata.get("duration"), 0.0))


def _video_bitrate(report_json: dict) -> float:
    metadata = (report_json.get("technical_quality") or {}).get("metadata") or {}
    return _as_float(metadata.get("video_bitrate_kbps"), 0.0)


def _has_audio(report_json: dict) -> bool:
    overview = report_json.get("asset_overview") or {}
    metadata = (report_json.get("technical_quality") or {}).get("metadata") or {}
    return bool(overview.get("has_audio", metadata.get("has_audio", False)))


def _expected_lift(point: dict) -> dict:
    lift = point.get("expected_lift")
    if isinstance(lift, dict):
        return lift
    value = point.get("expected_score_lift")
    return {"investment": _as_float(value, 0.0)}


def _fix(fix_id: str, point: dict, strategy: str, action: str | None = None) -> dict:
    return {
        "fix_id": fix_id,
        "action": action or strategy,
        "source_edit_point_id": point.get("id"),
        "source_issue_type": point.get("issue_type"),
        "start_time": point.get("start_time"),
        "end_time": point.get("end_time"),
        "confidence": point.get("confidence") or "medium",
        "priority": point.get("priority"),
        "ffmpeg_strategy": strategy,
        "expected_lift": _expected_lift(point),
        "recommended_edit": point.get("recommended_edit") or point.get("description") or "",
    }


def merge_cut_ranges(cuts: list[tuple[float, float]], duration: float, padding: float = 0.0) -> list[tuple[float, float]]:
    normalized: list[tuple[float, float]] = []
    for start, end in cuts:
        start_value = max(0.0, _as_float(start) - padding)
        end_value = min(duration, _as_float(end) + padding)
        if end_value <= start_value:
            continue
        normalized.append((start_value, end_value))
    normalized.sort(key=lambda item: item[0])

    merged: list[tuple[float, float]] = []
    for start, end in normalized:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        last_start, last_end = merged[-1]
        merged[-1] = (last_start, max(last_end, end))
    return merged


def kept_ranges_after_cuts(cuts: list[tuple[float, float]], duration: float, minimum_piece: float = 0.05) -> list[tuple[float, float]]:
    cursor = 0.0
    kept: list[tuple[float, float]] = []
    for start, end in merge_cut_ranges(cuts, duration):
        if start - cursor >= minimum_piece:
            kept.append((cursor, start))
        cursor = max(cursor, end)
    if duration - cursor >= minimum_piece:
        kept.append((cursor, duration))
    return kept


def validate_cut_ranges(cuts: list[tuple[float, float]], duration: float, min_remaining_duration: float = MIN_DURATION_AFTER_CUT) -> tuple[bool, str]:
    if duration <= 0:
        return False, "clip duration is unknown"
    for start, end in cuts:
        if start < 0 or end < 0:
            return False, "cut range cannot be negative"
        if end <= start:
            return False, "cut range end must be after start"
        if start >= duration or end > duration + 0.05:
            return False, "cut range is outside clip duration"
    remaining = sum(end - start for start, end in kept_ranges_after_cuts(cuts, duration))
    if remaining < min_remaining_duration:
        return False, f"remaining duration would be below {min_remaining_duration:.1f}s"
    return True, ""


def _priority_rank(point: dict) -> tuple[int, int, float]:
    priority_rank = {"P0": 0, "P1": 1, "P2": 2}.get(point.get("priority"), 9)
    strategy_rank = {
        "trim_start": 0,
        "trim_end": 1,
        "normalize_audio": 2,
        "boost_audio": 2,
        "re_export": 3,
        "remove_segment": 4,
    }
    strategy = point.get("ffmpeg_strategy") or ""
    lift = _as_float((point.get("expected_lift") or {}).get("investment"), 0.0)
    return priority_rank, strategy_rank.get(strategy, 9), -lift


def _clip_stem(report_json: dict) -> str:
    filename = (report_json.get("asset_overview") or {}).get("filename") or "clip"
    return Path(filename).stem


def _manual(point: dict, reason: str) -> dict:
    return {
        "source_edit_point_id": point.get("id"),
        "issue_type": point.get("issue_type"),
        "action": point.get("action"),
        "priority": point.get("priority"),
        "reason": reason,
    }


def create_auto_fix_plan(report_json: dict, options: dict | None = None) -> dict:
    options = options or {}
    max_fixes = int(options.get("max_fixes_per_clip") or 3)
    min_duration = _as_float(options.get("min_duration_after_cut"), MIN_DURATION_AFTER_CUT)
    duration = _duration(report_json)
    edit_points = report_json.get("edit_points") or []
    fixes: list[dict] = []
    manual_only: list[dict] = []
    blocked_reasons: list[str] = []
    proposed_cuts: list[tuple[float, float]] = []

    for point in edit_points:
        priority = point.get("priority")
        if priority not in SAFE_PRIORITIES:
            continue
        action = point.get("action") or ""
        issue_type = point.get("issue_type") or ""
        confidence = point.get("confidence") or "medium"
        start = _as_float(point.get("start_time"), 0.0)
        end = _as_float(point.get("end_time"), 0.0)
        segment_duration = max(0.0, end - start)

        fix_id = f"fix_{len(fixes) + 1:03d}"

        if action == "re_export" or issue_type in {"low_bitrate", "very_low_bitrate", "low_sharpness"}:
            if issue_type in {"low_bitrate", "very_low_bitrate"} and _video_bitrate(report_json) >= 5000:
                manual_only.append(_manual(point, "bitrate is already above conservative re-export target"))
                continue
            fixes.append(_fix(fix_id, point, "re_export"))
            continue

        if action == "normalize_audio" or issue_type in {"audio_too_quiet", "possible_clipping"}:
            if not _has_audio(report_json):
                manual_only.append(_manual(point, "no source audio is available to normalize"))
                continue
            fixes.append(_fix(fix_id, point, "normalize_audio"))
            continue

        if action == "boost_audio" or issue_type == "opening_silence":
            if not _has_audio(report_json):
                manual_only.append(_manual(point, "no source audio is available to boost"))
                continue
            fixes.append(_fix(fix_id, point, "boost_audio"))
            continue

        if action in {"cut", "cut_or_replace_first_frame"} and start <= 0.05 and 0 < end <= 2.0 and confidence in SAFE_CONFIDENCE:
            cut = (0.0, end)
            ok, reason = validate_cut_ranges(proposed_cuts + [cut], duration, min_duration)
            if ok:
                proposed_cuts.append(cut)
                fixes.append(_fix(fix_id, point, "trim_start"))
            else:
                blocked_reasons.append(f"{issue_type}: {reason}")
            continue

        if action == "shorten_ending" or issue_type in {"static_ending", "credits_like_segment"}:
            if start > 0 and duration > 0 and start >= duration - 10.0:
                cut = (start, duration)
                ok, reason = validate_cut_ranges(proposed_cuts + [cut], duration, min_duration)
                if ok:
                    proposed_cuts.append(cut)
                    fixes.append(_fix(fix_id, point, "trim_end"))
                else:
                    blocked_reasons.append(f"{issue_type}: {reason}")
                continue
            manual_only.append(_manual(point, "ending trim did not target the end of the clip"))
            continue

        if action in {"remove_segment", "compress"} and issue_type in {
            "dead_time_segment",
            "static_segment",
            "black_segment",
            "repeated_frame_segment",
            "low_motion_segment",
            "silence_segment",
        }:
            if confidence != "high" and priority != "P0":
                manual_only.append(_manual(point, "segment removal requires high confidence unless it is P0"))
                continue
            if not (0 < segment_duration <= MAX_SEGMENT_REMOVE_SECONDS):
                manual_only.append(_manual(point, "segment is too long or has no usable time range"))
                continue
            cut = (start, end)
            ok, reason = validate_cut_ranges(proposed_cuts + [cut], duration, min_duration)
            if ok:
                proposed_cuts.append(cut)
                fixes.append(_fix(fix_id, point, "remove_segment", action="remove_segment"))
            else:
                blocked_reasons.append(f"{issue_type}: {reason}")
            continue

        manual_only.append(_manual(point, "not auto-fixable in v0.2.2"))

    fixes.sort(key=_priority_rank)
    selected = fixes[:max_fixes]
    if len(fixes) > max_fixes:
        blocked_reasons.append(f"limited to {max_fixes} fixes from {len(fixes)} safe candidates")

    return {
        "clip_name": _clip_stem(report_json),
        "can_auto_fix": bool(selected),
        "reason": "safe deterministic fixes selected" if selected else "no safe deterministic fixes selected",
        "fixes": selected,
        "manual_only": manual_only,
        "blocked_reasons": blocked_reasons,
        "duration": duration,
        "max_fixes_per_clip": max_fixes,
    }
