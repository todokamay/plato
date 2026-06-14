import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.pipeline import analyze_clip, import_clip_file
from modules.safe_subprocess import run_command
from tools.test_helpers import temp_file


if __name__ == "__main__":
    sample_path = temp_file("sample_vertical.mp4")
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
            "nullsrc=s=1080x1920:r=30,geq=lum='random(1)*255':cb='128':cr='128'",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=44100",
            "-t",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-b:v",
            "5000k",
            "-minrate",
            "5000k",
            "-maxrate",
            "5000k",
            "-bufsize",
            "10000k",
            "-c:a",
            "aac",
            "-shortest",
            str(sample_path),
        ],
        timeout=240,
    )
    if not result["ok"]:
        raise SystemExit(result["stderr"] or result["error"])
    clip = import_clip_file(sample_path)
    result = analyze_clip(clip["id"])
    print(f"Sample report: {result['report_html_path']}")
    print(f"Sample JSON: {result['report_json_path']}")
