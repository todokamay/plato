import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.visual_analyzer import analyze_visual_frames
from tools.test_helpers import temp_file


def _write(path: Path, image) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), image)
    return {"timestamp": float(path.stem.split("_")[-1]), "frame_path": str(path), "ok": True}


def main() -> int:
    folder = temp_file("visual") 
    folder.mkdir(parents=True, exist_ok=True)
    black = np.zeros((120, 80, 3), dtype=np.uint8)
    checker = np.indices((120, 80)).sum(axis=0) % 2 * 255
    checker = np.dstack([checker, checker, checker]).astype(np.uint8)

    frames = [
        _write(folder / "frame_0.jpg", black),
        _write(folder / "frame_1.jpg", black),
        _write(folder / "frame_2.jpg", checker),
    ]
    result = analyze_visual_frames(frames)
    assert result["black_ratio"] > 0
    assert result["static_ratio"] > 0
    assert isinstance(result["avg_sharpness"], float)
    assert result["frames"][1]["is_static"] is True
    assert "active_content" in result
    assert "active_content_ratio" in result

    print("test_visual_analyzer: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
