from pathlib import Path

import cv2
import numpy as np

from config import FRAMES_DIR, ensure_data_dirs, project_path
from modules.safe_subprocess import run_command


def planned_timestamps(duration: float) -> list[float]:
    duration = max(float(duration or 0), 0.0)
    candidates = [0.0, 0.5, 1.0, 2.0, 3.0, 5.0]
    timestamps: list[float] = []
    for item in candidates:
        if item <= duration + 0.05:
            timestamps.append(round(item, 2))

    current = 10.0
    while current <= duration + 0.05:
        timestamps.append(round(current, 2))
        current += 5.0

    if not timestamps:
        timestamps.append(0.0)
    return sorted(dict.fromkeys(timestamps))


def sample_frames(file_path: str, clip_id: str, duration: float) -> list[dict]:
    ensure_data_dirs()
    output_dir = project_path(FRAMES_DIR) / clip_id
    output_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    for index, timestamp in enumerate(planned_timestamps(duration)):
        output_path = output_dir / f"frame_{index:04d}_{int(timestamp * 1000):06d}.jpg"
        result = run_command(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(Path(file_path)),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(output_path),
            ],
            timeout=30,
        )
        if result["ok"] and output_path.exists() and output_path.stat().st_size > 0:
            frames.append(
                {
                    "timestamp": timestamp,
                    "frame_path": str(output_path),
                    "ok": True,
                    "error": None,
                }
            )
        else:
            frames.append(
                {
                    "timestamp": timestamp,
                    "frame_path": str(output_path),
                    "ok": False,
                    "error": result.get("stderr") or result.get("error") or "Frame extraction failed.",
                }
            )
    return frames


def create_contact_sheet(frames: list[dict]) -> str:
    readable = [frame for frame in frames if frame.get("ok") and Path(frame.get("frame_path", "")).exists()]
    if not readable:
        return ""

    images = []
    for frame in readable:
        image = cv2.imread(frame["frame_path"])
        if image is None:
            continue
        thumb = cv2.resize(image, (220, 124), interpolation=cv2.INTER_AREA)
        cv2.putText(
            thumb,
            f"{frame['timestamp']:.1f}s",
            (8, 116),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        images.append(thumb)

    if not images:
        return ""

    cols = min(4, len(images))
    rows = int(np.ceil(len(images) / cols))
    sheet = np.zeros((rows * 124, cols * 220, 3), dtype=np.uint8)
    for idx, image in enumerate(images):
        row = idx // cols
        col = idx % cols
        sheet[row * 124 : (row + 1) * 124, col * 220 : (col + 1) * 220] = image

    first_path = Path(readable[0]["frame_path"])
    output_path = first_path.parent / "contact_sheet.jpg"
    cv2.imwrite(str(output_path), sheet)
    return str(output_path)
