import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.active_content import analyze_active_content
from tools.test_helpers import temp_file


def _frame(path: Path, image: np.ndarray, timestamp: float) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), image)
    return {"timestamp": timestamp, "frame_path": str(path), "ok": True}


def main() -> int:
    folder = temp_file("active_content")
    folder.mkdir(parents=True, exist_ok=True)

    full = np.full((1920, 1080, 3), 180, dtype=np.uint8)
    full_result = analyze_active_content([_frame(folder / "full.jpg", full, 0.0)])
    assert full_result["active_content_ratio"] >= 0.95, full_result
    assert full_result["pillarbox_detected"] is False
    assert full_result["small_center_content_detected"] is False

    centered = np.zeros((1920, 1080, 3), dtype=np.uint8)
    centered[710:1210, 365:715] = 220
    centered_result = analyze_active_content([_frame(folder / "centered.jpg", centered, 0.0)])
    assert centered_result["active_content_ratio"] < 0.40, centered_result
    assert centered_result["small_center_content_detected"] is True

    pillarbox = np.zeros((1920, 1080, 3), dtype=np.uint8)
    pillarbox[:, 240:840] = 170
    pillarbox_result = analyze_active_content([_frame(folder / "pillarbox.jpg", pillarbox, 0.0)])
    assert pillarbox_result["pillarbox_detected"] is True, pillarbox_result
    assert pillarbox_result["active_width_ratio"] < 0.65, pillarbox_result

    banner = np.zeros((1920, 1080, 3), dtype=np.uint8)
    banner[40:160, 190:890] = 230
    banner[720:1220, 365:715] = 210
    banner_result = analyze_active_content([_frame(folder / "banner.jpg", banner, 0.0)])
    assert banner_result["active_content_ratio"] < 0.40, banner_result
    assert banner_result["small_center_content_detected"] is True

    print("test_active_content: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
