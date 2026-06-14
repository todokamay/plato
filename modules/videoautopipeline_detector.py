from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


DEFAULT_VIDEOAUTOPIPELINE_ROOT = Path(r"C:\Users\User\Desktop\Work\VideoAutoPipeline")
CANDIDATE_RELATIVE_FOLDERS = [
    Path("outputs"),
    Path("data") / "outputs",
    Path("renders"),
    Path("exports"),
    Path("videos"),
    Path("."),
]
SUPPORTED_OUTPUT_EXTENSIONS = {".mp4"}


def _mtime_iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


def _relative_depth(root: Path, path: Path) -> int:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return 999999
    if str(relative) == ".":
        return 0
    return len(relative.parts)


def _iter_dirs_within_depth(start: Path, root: Path, depth_limit: int) -> list[Path]:
    if not start.exists() or not start.is_dir():
        return []
    output: list[Path] = []
    stack = [start]
    seen: set[Path] = set()
    while stack:
        current = stack.pop()
        try:
            resolved = current.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if _relative_depth(root, current) > depth_limit:
            continue
        output.append(current)
        try:
            children = sorted([child for child in current.iterdir() if child.is_dir()], key=lambda item: str(item).lower())
        except OSError:
            continue
        for child in reversed(children):
            if _relative_depth(root, child) <= depth_limit:
                stack.append(child)
    return output


def _mp4_files(folder: Path) -> list[Path]:
    try:
        files = [path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_OUTPUT_EXTENSIONS]
    except OSError:
        return []
    return sorted(files, key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)


def _candidate_priority(root: Path, folder: Path) -> int:
    try:
        relative = folder.resolve().relative_to(root.resolve())
    except ValueError:
        return len(CANDIDATE_RELATIVE_FOLDERS)
    for index, candidate in enumerate(CANDIDATE_RELATIVE_FOLDERS):
        if relative == candidate or (candidate != Path(".") and candidate in relative.parents):
            return index
    return len(CANDIDATE_RELATIVE_FOLDERS)


def _candidate_payload(root: Path, folder: Path, files: list[Path], sample_limit: int) -> dict:
    stats = []
    for path in files:
        try:
            stats.append((path, path.stat()))
        except OSError:
            continue
    newest = max((stat.st_mtime for _, stat in stats), default=None)
    total_size = sum(stat.st_size for _, stat in stats)
    return {
        "folder_path": str(folder.resolve()),
        "mp4_count": len(stats),
        "newest_modification_time": _mtime_iso(newest),
        "newest_modification_timestamp": newest,
        "total_size_bytes": total_size,
        "sample_filenames": [path.name for path, _ in stats[:sample_limit]],
        "candidate_priority": _candidate_priority(root, folder),
        "depth": _relative_depth(root, folder),
    }


def _score(candidate: dict) -> tuple[int, float, int, int]:
    return (
        int(candidate.get("mp4_count") or 0),
        float(candidate.get("newest_modification_timestamp") or 0.0),
        -int(candidate.get("candidate_priority") or 0),
        -int(candidate.get("depth") or 0),
    )


def detect_videoautopipeline_outputs(
    root: str | Path = DEFAULT_VIDEOAUTOPIPELINE_ROOT,
    *,
    depth_limit: int = 4,
    sample_limit: int = 5,
) -> dict:
    root_path = Path(root)
    if not root_path.exists() or not root_path.is_dir():
        return {
            "root": str(root_path),
            "found": False,
            "recommended_input_folder": "",
            "candidates": [],
            "message": f"VideoAutoPipeline root not found: {root_path}",
        }

    start_dirs = []
    for relative in CANDIDATE_RELATIVE_FOLDERS:
        candidate = root_path / relative
        if candidate.exists() and candidate.is_dir():
            start_dirs.append(candidate)
    if root_path not in start_dirs:
        start_dirs.append(root_path)

    folders: dict[str, Path] = {}
    for start in start_dirs:
        for folder in _iter_dirs_within_depth(start, root_path, depth_limit):
            folders[str(folder.resolve()).lower()] = folder

    candidates = []
    for folder in folders.values():
        files = _mp4_files(folder)
        if not files:
            continue
        candidates.append(_candidate_payload(root_path, folder, files, sample_limit))

    candidates.sort(key=_score, reverse=True)
    recommended = candidates[0]["folder_path"] if candidates else ""
    return {
        "root": str(root_path.resolve()),
        "found": bool(candidates),
        "recommended_input_folder": recommended,
        "candidates": candidates,
        "message": "found candidate output folders" if candidates else "No MP4 output folders found under VideoAutoPipeline root.",
    }
