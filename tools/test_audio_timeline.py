import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.audio_analyzer import analyze_audio
from modules.safe_subprocess import run_command
from modules.video_probe import probe_video
from tools.test_helpers import temp_file


def _silent_video(path: Path) -> Path:
    result = run_command(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=360x640:rate=30",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=mono:sample_rate=44100",
            "-t",
            "2.5",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        timeout=60,
    )
    assert result["ok"], result
    return path


def main() -> int:
    no_audio = analyze_audio("missing.mp4", False, duration=2.0)
    assert no_audio["has_audio"] is False
    assert no_audio["audio_energy_timeline"] == []

    video = _silent_video(temp_file("audio_timeline_silent.mp4"))
    metadata = probe_video(str(video))
    result = analyze_audio(str(video), metadata["has_audio"], metadata["duration"])
    assert result["opening_silence"] is True
    assert result["silence_segments"], result
    assert result["audio_drop_segments"], result
    assert result["audio_energy_timeline"], result
    assert any(item["silent"] for item in result["audio_energy_timeline"])

    print("test_audio_timeline: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
