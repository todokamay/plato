import json
from fractions import Fraction
from pathlib import Path
from typing import Any

from modules.safe_subprocess import run_command


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "N/A"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _kbps(value: Any) -> float | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    return round(numeric / 1000, 1)


def _parse_fps(stream: dict) -> float | None:
    for key in ("avg_frame_rate", "r_frame_rate"):
        value = stream.get(key)
        if not value or value in ("0/0", "N/A"):
            continue
        try:
            fps = float(Fraction(value))
            if fps > 0:
                return round(fps, 3)
        except (ZeroDivisionError, ValueError):
            continue
    return None


def _safe_error(message: str, raw: dict | None = None) -> dict:
    return {
        "ok": False,
        "error": message,
        "duration": None,
        "width": None,
        "height": None,
        "fps": None,
        "video_codec": None,
        "audio_codec": None,
        "video_bitrate_kbps": None,
        "audio_bitrate_kbps": None,
        "file_size": None,
        "aspect_ratio": None,
        "has_audio": False,
        "raw": raw or {},
    }


def probe_video(file_path: str) -> dict:
    path = Path(file_path)
    if not path.exists():
        return _safe_error("File not found.")
    if not path.is_file():
        return _safe_error("Path is not a file.")

    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=30,
    )
    if not result["ok"]:
        return _safe_error(result.get("stderr") or result.get("error") or "ffprobe failed.")

    try:
        raw = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return _safe_error("ffprobe returned invalid JSON.")

    streams = raw.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video_stream:
        return _safe_error("No readable video stream found.", raw)

    fmt = raw.get("format", {})
    duration = _to_float(fmt.get("duration")) or _to_float(video_stream.get("duration")) or 0.0
    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    aspect_ratio = round(height / width, 3) if width else None
    file_size = path.stat().st_size

    video_bitrate = _kbps(video_stream.get("bit_rate")) or _kbps(fmt.get("bit_rate"))
    audio_bitrate = _kbps(audio_stream.get("bit_rate")) if audio_stream else None

    return {
        "ok": True,
        "error": None,
        "duration": round(duration, 3),
        "width": width,
        "height": height,
        "fps": _parse_fps(video_stream),
        "video_codec": video_stream.get("codec_name"),
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
        "video_bitrate_kbps": video_bitrate,
        "audio_bitrate_kbps": audio_bitrate,
        "file_size": file_size,
        "aspect_ratio": aspect_ratio,
        "has_audio": audio_stream is not None,
        "raw": raw,
    }
