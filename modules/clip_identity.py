from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path


def _modified_time_iso(path: Path) -> str:
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return modified.isoformat(timespec="seconds")


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_clip_identity(file_path: str | Path, include_sha1: bool = False) -> dict:
    path = Path(file_path).resolve()
    stat = path.stat()
    modified_time = _modified_time_iso(path)
    identity = {
        "absolute_path": str(path),
        "file_size": int(stat.st_size),
        "modified_time": modified_time,
        "sha1": _sha1(path) if include_sha1 else None,
    }
    fingerprint = identity["sha1"] or f"{identity['absolute_path']}|{identity['file_size']}|{identity['modified_time']}"
    identity["identity_key"] = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()
    return identity
