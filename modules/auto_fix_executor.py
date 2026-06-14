from __future__ import annotations

import shutil
from pathlib import Path

from modules.auto_fix_planner import kept_ranges_after_cuts, merge_cut_ranges, validate_cut_ranges
from modules.safe_subprocess import run_command
from modules.video_probe import probe_video


DEFAULT_TIMEOUT = 180


def _as_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _has_strategy(fixes: list[dict], strategy: str) -> bool:
    return any(fix.get("ffmpeg_strategy") == strategy for fix in fixes)


def _target_bitrate(metadata: dict, options: dict) -> str:
    if options.get("target_video_bitrate"):
        value = str(options["target_video_bitrate"])
        return value if value.endswith("k") else f"{value}k"
    width = int(metadata.get("width") or 0)
    height = int(metadata.get("height") or 0)
    return "5000k" if max(width, height) >= 1280 else "3500k"


def _bufsize(target_bitrate: str) -> str:
    try:
        value = int(str(target_bitrate).rstrip("kK"))
    except ValueError:
        return "8000k"
    return f"{max(value * 2, value)}k"


def _audio_filter(fixes: list[dict]) -> str | None:
    if _has_strategy(fixes, "normalize_audio"):
        return "loudnorm=I=-14:TP=-1.5:LRA=11"
    if _has_strategy(fixes, "boost_audio"):
        return "volume=1.5"
    return None


def _encode_args(
    input_path: Path,
    output_path: Path,
    metadata: dict,
    fixes: list[dict],
    options: dict,
    *,
    start: float | None = None,
    duration: float | None = None,
    apply_audio_filter: bool = True,
) -> list[str]:
    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if start is not None and start > 0:
        args.extend(["-ss", f"{start:.3f}"])
    args.extend(["-i", str(input_path)])
    if duration is not None and duration > 0:
        args.extend(["-t", f"{duration:.3f}"])
    args.extend(["-map", "0:v:0"])
    has_audio = bool(metadata.get("has_audio"))
    if has_audio:
        args.extend(["-map", "0:a?"])
    target_bitrate = _target_bitrate(metadata, options)
    args.extend(
        [
            "-c:v",
            "libx264",
            "-b:v",
            target_bitrate,
            "-minrate",
            target_bitrate,
            "-maxrate",
            target_bitrate,
            "-bufsize",
            _bufsize(target_bitrate),
            "-preset",
            str(options.get("preset") or "medium"),
        ]
    )
    if has_audio:
        audio_filter = _audio_filter(fixes) if apply_audio_filter else None
        if audio_filter:
            args.extend(["-af", audio_filter])
        args.extend(["-c:a", "aac", "-b:a", "192k"])
    else:
        args.append("-an")
    args.extend(["-movflags", "+faststart", str(output_path)])
    return args


def _concat_file_line(path: Path) -> str:
    normalized = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{normalized}'"


def _run(args: list[str], timeout: int) -> dict:
    result = run_command(args, timeout=timeout)
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("stderr") or result.get("error") or "ffmpeg failed",
            "command": args,
            "stderr": result.get("stderr") or "",
        }
    return {"ok": True, "command": args, "stderr": result.get("stderr") or ""}


def _remove_segment_encode(input_path: Path, output_path: Path, metadata: dict, fixes: list[dict], cuts: list[tuple[float, float]], options: dict) -> dict:
    duration = _as_float(metadata.get("duration"), 0.0)
    keep_ranges = kept_ranges_after_cuts(cuts, duration)
    if not keep_ranges:
        return {"ok": False, "error": "all content would be removed"}

    temp_dir = output_path.parent / f".tmp_{output_path.stem}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    commands = []
    timeout = int(options.get("timeout") or DEFAULT_TIMEOUT)

    try:
        segments: list[Path] = []
        for index, (start, end) in enumerate(keep_ranges, start=1):
            segment = temp_dir / f"segment_{index:03d}.mp4"
            args = _encode_args(
                input_path,
                segment,
                metadata,
                fixes,
                options,
                start=start,
                duration=end - start,
                apply_audio_filter=False,
            )
            result = _run(args, timeout)
            commands.append(result.get("command"))
            if not result["ok"]:
                return {**result, "commands": commands}
            segments.append(segment)

        concat_list = temp_dir / "concat.txt"
        concat_list.write_text("\n".join(_concat_file_line(segment) for segment in segments), encoding="utf-8")
        args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list)]
        args.extend(["-map", "0:v:0"])
        if metadata.get("has_audio"):
            args.extend(["-map", "0:a?"])
        target_bitrate = _target_bitrate(metadata, options)
        args.extend(
            [
                "-c:v",
                "libx264",
                "-b:v",
                target_bitrate,
                "-minrate",
                target_bitrate,
                "-maxrate",
                target_bitrate,
                "-bufsize",
                _bufsize(target_bitrate),
                "-preset",
                str(options.get("preset") or "medium"),
            ]
        )
        if metadata.get("has_audio"):
            audio_filter = _audio_filter(fixes)
            if audio_filter:
                args.extend(["-af", audio_filter])
            args.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            args.append("-an")
        args.extend(["-movflags", "+faststart", str(output_path)])
        result = _run(args, timeout)
        commands.append(result.get("command"))
        return {**result, "commands": commands, "kept_ranges": keep_ranges}
    finally:
        if not options.get("keep_temp"):
            shutil.rmtree(temp_dir, ignore_errors=True)


def apply_auto_fix_plan(input_path: str | Path, fix_plan: dict, output_path: str | Path, options: dict | None = None) -> dict:
    options = options or {}
    source = Path(input_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    if not source.exists() or not source.is_file():
        return {"ok": False, "error": f"input file not found: {source}"}
    if source.resolve() == output.resolve():
        return {"ok": False, "error": "output path must differ from input path"}

    fixes = fix_plan.get("fixes") or []
    if not fix_plan.get("can_auto_fix") or not fixes:
        return {"ok": False, "error": fix_plan.get("reason") or "no auto-fixable actions"}

    before_stat = source.stat()
    metadata = probe_video(str(source))
    if not metadata.get("ok"):
        return {"ok": False, "error": metadata.get("error") or "input ffprobe failed"}

    trim_start = max(
        [_as_float(fix.get("end_time"), 0.0) for fix in fixes if fix.get("ffmpeg_strategy") == "trim_start"],
        default=0.0,
    )
    trim_end_values = [
        _as_float(fix.get("start_time"), 0.0)
        for fix in fixes
        if fix.get("ffmpeg_strategy") == "trim_end" and fix.get("start_time") is not None
    ]
    duration = _as_float(metadata.get("duration"), 0.0)
    trim_end = min(trim_end_values, default=duration)
    segment_cuts = [
        (_as_float(fix.get("start_time"), 0.0), _as_float(fix.get("end_time"), 0.0))
        for fix in fixes
        if fix.get("ffmpeg_strategy") == "remove_segment"
    ]
    cuts: list[tuple[float, float]] = []
    if trim_start > 0:
        cuts.append((0.0, trim_start))
    if trim_end > 0 and trim_end < duration:
        cuts.append((trim_end, duration))
    cuts.extend(segment_cuts)

    if cuts:
        ok, reason = validate_cut_ranges(merge_cut_ranges(cuts, duration), duration, _as_float(options.get("min_duration_after_cut"), 8.0))
        if not ok:
            return {"ok": False, "error": reason}

    timeout = int(options.get("timeout") or DEFAULT_TIMEOUT)
    if segment_cuts:
        result = _remove_segment_encode(source, output, metadata, fixes, cuts, options)
    else:
        start = trim_start if trim_start > 0 else None
        kept_duration = None
        if trim_end > 0 and trim_end < duration:
            kept_duration = trim_end - trim_start
        args = _encode_args(source, output, metadata, fixes, options, start=start, duration=kept_duration)
        result = _run(args, timeout)
        result["commands"] = [args]

    after_stat = source.stat()
    input_unchanged = before_stat.st_size == after_stat.st_size and before_stat.st_mtime_ns == after_stat.st_mtime_ns
    if not result.get("ok"):
        return {**result, "input_unchanged": input_unchanged}
    if not output.exists() or output.stat().st_size <= 0:
        return {"ok": False, "error": "ffmpeg did not create a non-empty output", "input_unchanged": input_unchanged}

    fixed_probe = probe_video(str(output))
    if not fixed_probe.get("ok"):
        return {
            "ok": False,
            "error": fixed_probe.get("error") or "fixed output is unreadable",
            "input_unchanged": input_unchanged,
            "output_path": str(output),
            "commands": result.get("commands") or [],
        }
    return {
        "ok": True,
        "output_path": str(output),
        "input_unchanged": input_unchanged,
        "applied_fix_count": len(fixes),
        "strategies": [fix.get("ffmpeg_strategy") for fix in fixes],
        "metadata_before": metadata,
        "metadata_after": fixed_probe,
        "commands": result.get("commands") or [],
        "kept_ranges": result.get("kept_ranges", []),
    }
