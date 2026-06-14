from pathlib import Path

import cv2
import numpy as np

from config import THRESHOLDS
from modules.active_content import analyze_active_content


def _segment(start: float, end: float, issue_type: str, reason: str, confidence: str = "medium") -> dict:
    return {
        "start_time": round(float(start), 2),
        "end_time": round(float(max(end, start)), 2),
        "issue_type": issue_type,
        "reason": reason,
        "confidence": confidence,
    }


def _merge_segments(segments: list[dict], max_gap: float = 1.0) -> list[dict]:
    if not segments:
        return []
    ordered = sorted(segments, key=lambda item: item["start_time"])
    merged = [ordered[0].copy()]
    for segment in ordered[1:]:
        current = merged[-1]
        if segment["start_time"] <= current["end_time"] + max_gap and segment["issue_type"] == current["issue_type"]:
            current["end_time"] = max(current["end_time"], segment["end_time"])
        else:
            merged.append(segment.copy())
    return merged


def _issue(issue_type: str, severity: str, start: float | None, end: float | None, description: str, recommendation: str) -> dict:
    return {
        "issue_type": issue_type,
        "severity": severity,
        "start_time": start,
        "end_time": end,
        "description": description,
        "recommendation": recommendation,
    }


def analyze_visual_frames(frames: list[dict]) -> dict:
    threshold_black = THRESHOLDS["black_brightness_threshold"]
    threshold_static = THRESHOLDS["static_frame_diff_threshold"]

    analyzed: list[dict] = []
    previous_gray = None
    previous_timestamp = None
    black_segments: list[dict] = []
    static_segments: list[dict] = []
    low_motion_segments: list[dict] = []
    credits_like_segments: list[dict] = []

    for frame in frames:
        frame_path = frame.get("frame_path")
        if not frame.get("ok") or not frame_path or not Path(frame_path).exists():
            continue
        image = cv2.imread(frame_path)
        if image is None:
            continue

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(image))
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        edges = cv2.Canny(gray, 80, 160)
        edge_density = float(np.count_nonzero(edges) / edges.size * 100)

        frame_diff = None
        is_static = False
        motion_score = 0.0
        if previous_gray is not None:
            comparable = cv2.resize(gray, (previous_gray.shape[1], previous_gray.shape[0]))
            frame_diff = float(np.mean(cv2.absdiff(comparable, previous_gray)))
            is_static = frame_diff < threshold_static
            motion_score = min(100.0, round(frame_diff * 2.5, 2))

        timestamp = float(frame["timestamp"])
        start_time = previous_timestamp if previous_timestamp is not None else timestamp
        is_black = brightness < threshold_black
        low_motion = previous_gray is not None and frame_diff is not None and frame_diff < threshold_static * 2
        credits_like = bool(low_motion and edge_density > 7.0 and sharpness > THRESHOLDS["sharpness_ok"])

        if is_black:
            black_segments.append(_segment(start_time, timestamp, "black_frame", "Very dark or black frame detected."))
        if is_static:
            static_segments.append(_segment(start_time, timestamp, "static_segment", "Frame-to-frame change is very low."))
        if low_motion:
            low_motion_segments.append(_segment(start_time, timestamp, "low_motion", "Motion proxy is low."))
        if credits_like:
            credits_like_segments.append(
                _segment(
                    start_time,
                    timestamp,
                    "credits_like_static_text_card",
                    "Static high-edge frame resembles a text card or credits block.",
                    confidence="low",
                )
            )

        record = {
            **frame,
            "brightness": round(brightness, 2),
            "sharpness": round(sharpness, 2),
            "edge_density": round(edge_density, 2),
            "frame_diff": round(frame_diff, 2) if frame_diff is not None else None,
            "motion_score": motion_score,
            "is_black": is_black,
            "is_static": is_static,
            "low_motion": low_motion,
            "credits_like": credits_like,
        }
        analyzed.append(record)
        previous_gray = gray
        previous_timestamp = timestamp

    total = len(analyzed)
    black_ratio = sum(1 for item in analyzed if item["is_black"]) / total if total else 0.0
    static_ratio = sum(1 for item in analyzed if item["is_static"]) / max(total - 1, 1) if total else 0.0
    avg_sharpness = sum(item["sharpness"] for item in analyzed) / total if total else 0.0
    avg_brightness = sum(item["brightness"] for item in analyzed) / total if total else 0.0

    black_segments = _merge_segments(black_segments)
    static_segments = _merge_segments(static_segments)
    low_motion_segments = _merge_segments(low_motion_segments)
    credits_like_segments = _merge_segments(credits_like_segments)

    issues = []
    if black_ratio >= 0.25:
        issues.append(
            _issue(
                "black_frames",
                "high",
                None,
                None,
                "Large share of sampled frames are near black.",
                "Remove dark sections or replace them with visible action.",
            )
        )
    if static_ratio >= 0.35:
        issues.append(
            _issue(
                "static_video",
                "high",
                None,
                None,
                "The clip contains many low-change frames.",
                "Cut static parts or add a faster edit before publishing.",
            )
        )
    for segment in static_segments:
        if segment["end_time"] - segment["start_time"] >= 1.5:
            issues.append(
                _issue(
                    "static_segment",
                    "medium",
                    segment["start_time"],
                    segment["end_time"],
                    "Static segment may cause a retention drop.",
                    "Remove or compress this segment.",
                )
            )
    for segment in credits_like_segments:
        if segment["end_time"] - segment["start_time"] >= 1.0:
            issues.append(
                _issue(
                    "credits_like_static_text_card",
                    "medium",
                    segment["start_time"],
                    segment["end_time"],
                    "A static text-card or credits-like segment was detected with low confidence.",
                    "Keep only if it directly sells the hook; otherwise remove or shorten it.",
                )
            )

    active_content = analyze_active_content(frames)

    return {
        "frames": analyzed,
        "black_ratio": round(black_ratio, 3),
        "static_ratio": round(static_ratio, 3),
        "avg_sharpness": round(avg_sharpness, 2),
        "avg_brightness": round(avg_brightness, 2),
        "active_content": active_content,
        "active_content_ratio": active_content.get("active_content_ratio"),
        "active_width_ratio": active_content.get("active_width_ratio"),
        "active_height_ratio": active_content.get("active_height_ratio"),
        "black_border_ratio": active_content.get("black_border_ratio"),
        "low_motion_segments": low_motion_segments,
        "black_segments": black_segments,
        "static_segments": static_segments,
        "credits_like_segments": credits_like_segments,
        "issues": issues + active_content.get("issues", []),
    }
