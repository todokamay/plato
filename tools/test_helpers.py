import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import TEMP_DIR, ensure_data_dirs, project_path
from modules.safe_subprocess import run_command


def temp_file(name: str) -> Path:
    ensure_data_dirs()
    path = project_path(TEMP_DIR) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def create_test_video(
    path: Path,
    duration: float = 3.0,
    audio: bool = True,
    size: str = "360x640",
    color: str | None = None,
    video_bitrate: str | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if color:
        video_source = f"color=c={color}:s={size}:r=30"
    else:
        video_source = f"testsrc=size={size}:rate=30"

    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", video_source]
    if audio:
        args.extend(["-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=44100"])
    args.extend(["-t", str(duration), "-pix_fmt", "yuv420p", "-c:v", "libx264"])
    if video_bitrate:
        args.extend(["-b:v", video_bitrate, "-minrate", video_bitrate, "-maxrate", video_bitrate, "-bufsize", "10000k"])
    if audio:
        args.extend(["-c:a", "aac", "-shortest"])
    else:
        args.append("-an")
    args.append(str(path))
    result = run_command(args, timeout=60)
    assert result["ok"], result
    return path
