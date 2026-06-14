from __future__ import annotations

import shutil
from pathlib import Path

from config import project_path
from modules.portfolio_ranking import safe_filename


BUCKETS = {
    "publish_ready",
    "safe_to_test",
    "fixed_publish_ready",
    "fixed_safe_to_test",
    "rejected",
    "failed_fix",
    "hold_source",
    "debug_review",
    "archive",
}
DEFAULT_ROUTING_ROOT = project_path("data/routed")


def normalize_bucket(bucket: str | None) -> str:
    value = (bucket or "debug_review").strip()
    return value if value in BUCKETS else "debug_review"


def bucket_path(bucket: str, *, root: str | Path = DEFAULT_ROUTING_ROOT) -> Path:
    path = Path(root) / normalize_bucket(bucket)
    path.mkdir(parents=True, exist_ok=True)
    return path


def copy_to_bucket(source: str | Path, bucket: str, *, root: str | Path = DEFAULT_ROUTING_ROOT) -> dict:
    source_path = Path(source)
    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(f"Source file not found: {source_path}")
    target_dir = bucket_path(bucket, root=root)
    target = target_dir / safe_filename(source_path.name)
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        for index in range(2, 10000):
            candidate = target_dir / f"{stem}_{index}{suffix}"
            if not candidate.exists():
                target = candidate
                break
    shutil.copy2(source_path, target)
    return {"bucket": normalize_bucket(bucket), "source_path": str(source_path.resolve()), "copied_path": str(target)}


def route_auto_qc_row(row: dict, *, root: str | Path = DEFAULT_ROUTING_ROOT) -> dict:
    bucket = normalize_bucket(row.get("final_bucket"))
    path = row.get("final_output_path") or row.get("fixed_path") or row.get("original_path")
    if not path:
        return {"bucket": bucket, "source_path": "", "copied_path": ""}
    return copy_to_bucket(path, bucket, root=root)
