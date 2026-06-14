import os
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules.videoautopipeline_detector import detect_videoautopipeline_outputs


def _touch(path: Path, size: int, mtime: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))


def main() -> int:
    root = project_path("data/temp") / f"vap_detect_{uuid.uuid4().hex[:8]}"
    try:
        _touch(root / "outputs" / "old.mp4", 10, 100)
        _touch(root / "data" / "outputs" / "nested" / "clip_a.mp4", 20, 200)
        _touch(root / "data" / "outputs" / "nested" / "clip_b.mp4", 30, 300)
        _touch(root / "renders" / "newest.mp4", 40, 400)
        (root / "exports" / "notes.txt").parent.mkdir(parents=True, exist_ok=True)
        (root / "exports" / "notes.txt").write_text("not video", encoding="utf-8")

        result = detect_videoautopipeline_outputs(root, depth_limit=4)
        assert result["found"]
        assert len(result["candidates"]) == 3
        recommended = Path(result["recommended_input_folder"])
        assert recommended.name == "nested"
        assert recommended.parent.name == "outputs"
        assert result["candidates"][0]["mp4_count"] == 2
        assert result["candidates"][0]["total_size_bytes"] == 50
        assert result["candidates"][0]["sample_filenames"][0] == "clip_b.mp4"

        shallow = detect_videoautopipeline_outputs(root, depth_limit=2)
        assert all("nested" not in candidate["folder_path"] for candidate in shallow["candidates"])
    finally:
        if root.exists():
            shutil.rmtree(root)

    print("test_videoautopipeline_detector: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
