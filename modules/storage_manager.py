from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import project_path


DEFAULT_ARCHIVE_ROOT = project_path("data/archive")


def directory_size(path: str | Path) -> int:
    root = Path(path)
    if not root.exists():
        return 0
    return sum(item.stat().st_size for item in root.rglob("*") if item.is_file())


def archive_copy(source: str | Path, *, archive_root: str | Path = DEFAULT_ARCHIVE_ROOT) -> dict:
    source_path = Path(source)
    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(f"Source file not found: {source_path}")
    target_dir = Path(archive_root) / datetime.now(timezone.utc).strftime("%Y%m%d")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source_path.name
    if target.exists():
        target = target_dir / f"{source_path.stem}_{datetime.now(timezone.utc).strftime('%H%M%S')}{source_path.suffix}"
    shutil.copy2(source_path, target)
    return {"source_path": str(source_path.resolve()), "archive_path": str(target)}


def cleanup_generated_files(root: str | Path, *, retention_days: int = 30, patterns: tuple[str, ...] = ("*.tmp",)) -> list[str]:
    base = Path(root)
    if not base.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = []
    for pattern in patterns:
        for path in base.rglob(pattern):
            if not path.is_file():
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified < cutoff:
                path.unlink(missing_ok=True)
                removed.append(str(path))
    return removed
