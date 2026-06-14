import sys

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.audio_analyzer import analyze_audio
from modules.video_probe import probe_video
from tools.test_helpers import create_test_video, temp_file


def main() -> int:
    no_audio = analyze_audio("does-not-matter.mp4", False)
    assert no_audio["has_audio"] is False
    assert no_audio["audio_issues"][0]["issue_type"] == "no_audio"

    video = create_test_video(temp_file("audio.mp4"), duration=2, audio=True)
    metadata = probe_video(str(video))
    result = analyze_audio(str(video), metadata["has_audio"], metadata["duration"])
    assert result["has_audio"] is True
    assert result["mean_volume_db"] is not None
    assert "opening_silence" in result
    assert "audio_energy_timeline" in result
    assert "audio_drop_segments" in result
    assert isinstance(result["audio_issues"], list)

    print("test_audio_analyzer: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
