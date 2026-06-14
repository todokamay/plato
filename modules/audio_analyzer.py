import os
import re
from pathlib import Path

from modules.safe_subprocess import run_command


def _parse_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _parse_silences(text: str, duration: float | None) -> list[dict]:
    starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9.]+)", text)]
    ends = [(float(end), float(length)) for end, length in re.findall(r"silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)", text)]
    segments = []
    for index, start in enumerate(starts):
        if index < len(ends):
            end, length = ends[index]
        else:
            end = float(duration or start)
            length = max(0.0, end - start)
        segments.append({"start_time": round(start, 2), "end_time": round(end, 2), "duration": round(length, 2)})
    return segments


def _overlap_seconds(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def _build_audio_energy_timeline(duration: float | None, mean_volume: float | None, silence_segments: list[dict], window_size: float = 1.0) -> list[dict]:
    if not duration or duration <= 0:
        return []
    timeline = []
    cursor = 0.0
    baseline = mean_volume if mean_volume is not None else -22.0
    while cursor < duration:
        end = min(duration, cursor + window_size)
        overlap = sum(_overlap_seconds(cursor, end, segment["start_time"], segment["end_time"]) for segment in silence_segments)
        silent = overlap >= (end - cursor) * 0.5
        timeline.append(
            {
                "start_time": round(cursor, 2),
                "end_time": round(end, 2),
                "energy_db": -45.0 if silent else round(float(baseline), 1),
                "silent": silent,
            }
        )
        cursor += window_size
    return timeline


def _audio_drop_segments(silence_segments: list[dict]) -> list[dict]:
    drops = []
    for segment in silence_segments:
        if segment["duration"] >= 1.0:
            drops.append(
                {
                    "start_time": segment["start_time"],
                    "end_time": segment["end_time"],
                    "duration": segment["duration"],
                    "reason": "silence_or_low_energy",
                }
            )
    return drops


def analyze_audio(file_path: str, has_audio: bool, duration: float | None = None) -> dict:
    if not has_audio:
        return {
            "has_audio": False,
            "mean_volume_db": None,
            "max_volume_db": None,
            "silence_ratio": None,
            "opening_silence": True,
            "silence_segments": [],
            "audio_drop_segments": [],
            "audio_energy_timeline": [],
            "audio_issues": [
                {
                    "issue_type": "no_audio",
                    "severity": "high",
                    "description": "No audio stream was detected.",
                    "recommendation": "Add music, voice, or intentional sound design before publishing.",
                }
            ],
        }

    path = str(Path(file_path))
    volume_result = run_command(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "volumedetect", "-f", "null", os.devnull],
        timeout=60,
    )
    volume_text = f"{volume_result.get('stdout', '')}\n{volume_result.get('stderr', '')}"
    mean_volume = _parse_float(r"mean_volume:\s*(-?[0-9.]+)\s*dB", volume_text)
    max_volume = _parse_float(r"max_volume:\s*(-?[0-9.]+)\s*dB", volume_text)

    silence_result = run_command(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "silencedetect=noise=-35dB:d=0.4", "-f", "null", os.devnull],
        timeout=60,
    )
    silence_text = f"{silence_result.get('stdout', '')}\n{silence_result.get('stderr', '')}"
    silence_segments = _parse_silences(silence_text, duration)
    total_silence = sum(item["duration"] for item in silence_segments)
    silence_ratio = round(total_silence / duration, 3) if duration and duration > 0 else None
    audio_drop_segments = _audio_drop_segments(silence_segments)
    audio_energy_timeline = _build_audio_energy_timeline(duration, mean_volume, silence_segments)

    opening_result = run_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-t",
            "2",
            "-i",
            path,
            "-af",
            "silencedetect=noise=-35dB:d=0.4",
            "-f",
            "null",
            os.devnull,
        ],
        timeout=30,
    )
    opening_text = f"{opening_result.get('stdout', '')}\n{opening_result.get('stderr', '')}"
    opening_segments = _parse_silences(opening_text, 2.0)
    opening_silence = any(
        segment["start_time"] <= 0.3 and min(segment["end_time"], 2.0) - segment["start_time"] >= 1.2
        for segment in opening_segments
    )

    issues = []
    if mean_volume is None:
        issues.append(
            {
                "issue_type": "audio_unreadable",
                "severity": "medium",
                "description": "Audio stream exists but ffmpeg could not derive a reliable volume metric.",
                "recommendation": "Re-export audio or inspect the source file.",
            }
        )
    elif mean_volume < -25:
        issues.append(
            {
                "issue_type": "audio_too_quiet",
                "severity": "medium",
                "description": f"Mean audio volume is low at {mean_volume:.1f} dB.",
                "recommendation": "Normalize audio toward a stronger short-form loudness target.",
            }
        )
    elif mean_volume > -10:
        issues.append(
            {
                "issue_type": "audio_too_loud",
                "severity": "medium",
                "description": f"Mean audio volume is very high at {mean_volume:.1f} dB.",
                "recommendation": "Lower gain and check for clipping before publishing.",
            }
        )

    if opening_silence:
        issues.append(
            {
                "issue_type": "opening_silence",
                "severity": "high",
                "description": "The first two seconds are mostly silent.",
                "recommendation": "Start audio immediately or cut to the first audible moment.",
            }
        )
    if silence_ratio is not None and silence_ratio > 0.25:
        issues.append(
            {
                "issue_type": "long_silence",
                "severity": "medium",
                "description": f"Silence covers about {silence_ratio * 100:.0f}% of the clip.",
                "recommendation": "Cut long silent stretches or add intentional sound.",
            }
        )
    for segment in audio_drop_segments:
        if segment["start_time"] > 2.0:
            issues.append(
                {
                    "issue_type": "silence_segment",
                    "severity": "medium" if segment["duration"] < 3 else "high",
                    "start_time": segment["start_time"],
                    "end_time": segment["end_time"],
                    "description": f"Audio drops to silence or low energy for {segment['duration']:.1f}s.",
                    "recommendation": "Cut the silent gap, add intentional sound, or tighten the edit.",
                }
            )
    if max_volume is not None and max_volume > -0.5:
        issues.append(
            {
                "issue_type": "possible_clipping",
                "severity": "medium",
                "description": f"Max volume reaches {max_volume:.1f} dB and may clip.",
                "recommendation": "Lower gain and check limiter/export settings.",
            }
        )

    return {
        "has_audio": True,
        "mean_volume_db": mean_volume,
        "max_volume_db": max_volume,
        "silence_ratio": silence_ratio,
        "opening_silence": opening_silence,
        "silence_segments": silence_segments,
        "audio_drop_segments": audio_drop_segments,
        "audio_energy_timeline": audio_energy_timeline,
        "audio_issues": issues,
    }
