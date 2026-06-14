from pathlib import Path

import cv2
import numpy as np


def _default_result() -> dict:
    return {
        "active_content_ratio": None,
        "active_width_ratio": None,
        "active_height_ratio": None,
        "black_border_ratio": None,
        "pillarbox_detected": False,
        "letterbox_detected": False,
        "small_center_content_detected": False,
        "confidence": "low",
        "issues": [],
        "frame_count": 0,
    }


def _issue(issue_type: str, severity: str, description: str, recommendation: str) -> dict:
    return {
        "issue_type": issue_type,
        "severity": severity,
        "start_time": None,
        "end_time": None,
        "description": description,
        "recommendation": recommendation,
    }


def _meaningful_bbox(gray: np.ndarray) -> tuple[int, int, int, int] | None:
    height, width = gray.shape
    frame_area = height * width

    bright_mask = gray > 25
    edges = cv2.Canny(gray, 50, 130)
    edges = cv2.dilate(edges, np.ones((5, 5), dtype=np.uint8), iterations=2) > 0

    mask = np.logical_or(bright_mask, edges).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((19, 19), dtype=np.uint8), iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), dtype=np.uint8), iterations=1)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return None

    min_area = max(int(frame_area * 0.008), 120)
    components = []
    for label in range(1, count):
        x, y, w, h, area = stats[label]
        if area < min_area:
            continue
        if w < width * 0.04 and h < height * 0.04:
            continue
        components.append((int(area), int(x), int(y), int(w), int(h)))

    if not components:
        return None

    components.sort(reverse=True)
    _, x, y, w, h = components[0]
    return x, y, w, h


def _border_is_dark(gray: np.ndarray, x: int, y: int, w: int, h: int) -> tuple[bool, bool]:
    height, width = gray.shape
    strips = []
    if x > width * 0.08:
        strips.append(gray[:, :x])
    if x + w < width * 0.92:
        strips.append(gray[:, x + w :])
    side_dark = bool(strips) and all(float(np.mean(strip)) < 35 for strip in strips if strip.size)

    strips = []
    if y > height * 0.08:
        strips.append(gray[:y, :])
    if y + h < height * 0.92:
        strips.append(gray[y + h :, :])
    vertical_dark = bool(strips) and all(float(np.mean(strip)) < 35 for strip in strips if strip.size)
    return side_dark, vertical_dark


def analyze_active_content(frames: list[dict]) -> dict:
    measurements = []
    side_dark_hits = 0
    vertical_dark_hits = 0

    for frame in frames:
        frame_path = frame.get("frame_path")
        if not frame.get("ok") or not frame_path or not Path(frame_path).exists():
            continue
        image = cv2.imread(frame_path)
        if image is None:
            continue
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        bbox = _meaningful_bbox(gray)
        if bbox is None:
            continue

        x, y, w, h = bbox
        frame_height, frame_width = gray.shape
        width_ratio = w / frame_width
        height_ratio = h / frame_height
        area_ratio = (w * h) / (frame_width * frame_height)
        side_dark, vertical_dark = _border_is_dark(gray, x, y, w, h)
        side_dark_hits += int(side_dark)
        vertical_dark_hits += int(vertical_dark)
        measurements.append(
            {
                "active_content_ratio": area_ratio,
                "active_width_ratio": width_ratio,
                "active_height_ratio": height_ratio,
                "black_border_ratio": max(0.0, 1.0 - area_ratio),
            }
        )

    if not measurements:
        return _default_result()

    def median(key: str) -> float:
        return round(float(np.median([item[key] for item in measurements])), 3)

    active_content_ratio = median("active_content_ratio")
    active_width_ratio = median("active_width_ratio")
    active_height_ratio = median("active_height_ratio")
    black_border_ratio = median("black_border_ratio")
    count = len(measurements)
    confidence = "high" if count >= 5 else "medium" if count >= 2 else "low"

    pillarbox_detected = active_width_ratio < 0.65 and side_dark_hits >= max(1, count // 2)
    letterbox_detected = active_height_ratio < 0.65 and vertical_dark_hits >= max(1, count // 2)
    small_center_content_detected = active_width_ratio < 0.70 and active_height_ratio < 0.70

    issues = []
    if active_content_ratio < 0.40:
        issues.append(
            _issue(
                "active_content_too_small",
                "critical",
                "Active content fills less than 40% of the frame.",
                "Scale, crop, or redesign the composition so the main content fills the vertical frame.",
            )
        )
    elif active_content_ratio < 0.55:
        issues.append(
            _issue(
                "active_content_weak",
                "high",
                "Active content fills only part of the frame.",
                "Increase active content size, crop tighter, or create a proper vertical composition.",
            )
        )
    elif active_content_ratio < 0.70:
        issues.append(
            _issue(
                "active_content_acceptable_not_strong",
                "medium",
                "Active content area is acceptable but not strong for a vertical short.",
                "Fill more of the frame before aiming for Strong Publish.",
            )
        )

    if pillarbox_detected:
        issues.append(
            _issue(
                "content_does_not_fill_vertical_frame",
                "high" if active_content_ratio < 0.55 else "medium",
                "Black side areas indicate pillarboxed or narrow active content.",
                "Reframe, crop, or scale content to fill more vertical space.",
            )
        )
    if letterbox_detected:
        issues.append(
            _issue(
                "letterbox_detected",
                "high" if active_content_ratio < 0.55 else "medium",
                "Black top/bottom areas indicate letterboxed content.",
                "Crop or rebuild the edit for a native vertical frame.",
            )
        )
    if small_center_content_detected:
        issues.append(
            _issue(
                "small_center_content",
                "high" if active_content_ratio < 0.55 else "medium",
                "Small centered content reduces mobile impact.",
                "Increase active content size, crop tighter, or redesign the vertical layout.",
            )
        )

    return {
        "active_content_ratio": active_content_ratio,
        "active_width_ratio": active_width_ratio,
        "active_height_ratio": active_height_ratio,
        "black_border_ratio": black_border_ratio,
        "pillarbox_detected": pillarbox_detected,
        "letterbox_detected": letterbox_detected,
        "small_center_content_detected": small_center_content_detected,
        "confidence": confidence,
        "issues": issues,
        "frame_count": count,
    }
