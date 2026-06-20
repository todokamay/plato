from __future__ import annotations

import json
import re
from pathlib import Path

from config import project_path


READY_STATUSES = {"succeeded", "succeeded_waiting_for_plato"}


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def default_delivery_root() -> Path:
    return project_path("data/videoautopipeline_delivery")


def _already_delivered(delivery_root: Path, job_id: str) -> bool:
    data = _load_json(delivery_root / "jobs" / f"{job_id}.json")
    return str(data.get("delivery_status") or "").lower() in {"sent", "delivered"}


def _final_rank_key(path: Path) -> tuple:
    stem = path.stem.lower()
    rank_match = re.search(r"_rank_(\d+)", stem)
    score_match = re.search(r"_score_([0-9]+(?:_[0-9]+)?)", stem)
    rank = int(rank_match.group(1)) if rank_match else 999999
    score = -float(score_match.group(1).replace("_", ".")) if score_match else 0.0
    return rank, score, path.name.lower()


def _preferred_final(job_dir: Path, status: dict) -> Path | None:
    finals = [path for path in (job_dir / "final").glob("*.mp4") if path.is_file()]
    davinci_required = str(status.get("davinci_mode") or "").lower() == "required"
    if davinci_required:
        davinci_finals = [path for path in finals if "_davinci" in path.stem.lower()]
        if davinci_finals:
            return sorted(davinci_finals, key=_final_rank_key)[0]
    candidates = []
    plato_input = status.get("plato_input_path")
    if plato_input:
        candidates.append(Path(plato_input))
    candidates.extend(sorted(finals, key=_final_rank_key))
    return next((path for path in candidates if path.exists() and path.is_file() and path.suffix.lower() == ".mp4"), None)


def find_waiting_jobs(output_root: str | Path, *, delivery_root: str | Path | None = None, limit: int | None = None) -> list[dict]:
    root = Path(output_root)
    if not root.exists():
        return []
    delivery = Path(delivery_root) if delivery_root else default_delivery_root()
    jobs = []
    for job_dir in sorted(path for path in root.iterdir() if path.is_dir() and path.name not in {"batches", "jobs"}):
        job_id = job_dir.name
        if _already_delivered(delivery, job_id):
            continue
        status_files = sorted((job_dir / "status").glob("*.json"))
        metadata_files = sorted((job_dir / "metadata").glob("*.json"))
        status_path = status_files[0] if status_files else None
        metadata_path = metadata_files[0] if metadata_files else None
        status = _load_json(status_path) if status_path else {}
        if status.get("status") not in READY_STATUSES:
            continue
        if not (status.get("send_mode") == "after_plato" or status.get("plato_required") is True):
            continue
        if str(status.get("delivery_status") or "").lower() in {"sent", "delivered"}:
            continue
        final_path = _preferred_final(job_dir, status)
        if not final_path:
            continue
        if str(status.get("davinci_mode") or "").lower() == "required" and not status.get("davinci_succeeded"):
            continue
        jobs.append({
            "job_id": job_id,
            "final_path": str(final_path.resolve()),
            "metadata_path": str(metadata_path.resolve()) if metadata_path else "",
            "status_path": str(status_path.resolve()) if status_path else "",
            "status": status,
        })
        if limit and len(jobs) >= limit:
            break
    return jobs
