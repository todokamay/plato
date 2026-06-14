import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.video_probe import probe_video
from tools.test_helpers import create_test_video, temp_file


def main() -> int:
    valid = create_test_video(temp_file("probe_valid.mp4"), duration=2, audio=True)
    no_audio = create_test_video(temp_file("probe_no_audio.mp4"), duration=2, audio=False)

    result = probe_video(str(valid))
    assert result["ok"], result
    assert result["duration"] > 0
    assert result["width"] > 0 and result["height"] > 0
    assert result["fps"] > 0
    assert result["has_audio"] is True

    silent = probe_video(str(no_audio))
    assert silent["ok"], silent
    assert silent["has_audio"] is False

    missing = probe_video(str(temp_file("missing.mp4")))
    assert missing["ok"] is False
    assert missing["error"]

    print("test_video_probe: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
