import json
import shutil
import uuid
from pathlib import Path

from config import project_path
from modules.videoautopipeline_contract import find_waiting_jobs


def root():
    path = project_path("data/temp") / f"vap_contract_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_job(base: Path, job_id: str, status: str = "succeeded_waiting_for_plato", *, final: bool = True, after_plato: bool = True):
    job = base / job_id
    (job / "status").mkdir(parents=True)
    (job / "metadata").mkdir(parents=True)
    (job / "final").mkdir(parents=True)
    final_path = job / "final" / f"{job_id}.mp4"
    if final:
        final_path.write_bytes(b"video")
    (job / "metadata" / f"{job_id}.metadata.json").write_text("{}", encoding="utf-8")
    (job / "status" / f"{job_id}.status.json").write_text(json.dumps({
        "job_id": job_id,
        "status": status,
        "send_mode": "after_plato" if after_plato else "immediate",
        "plato_required": after_plato,
        "plato_input_path": str(final_path),
    }), encoding="utf-8")


def test_reader_filters_waiting_jobs():
    base = root()
    delivery = root()
    try:
        write_job(base, "ready")
        write_job(base, "failed", status="failed")
        write_job(base, "running", status="running")
        write_job(base, "missing", final=False)
        write_job(base, "immediate", after_plato=False)
        jobs = find_waiting_jobs(base, delivery_root=delivery)
        assert [job["job_id"] for job in jobs] == ["ready"]
    finally:
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(delivery, ignore_errors=True)


def test_reader_ignores_delivered_jobs():
    base = root()
    delivery = root()
    try:
        write_job(base, "ready")
        delivered = delivery / "jobs" / "ready.json"
        delivered.parent.mkdir(parents=True)
        delivered.write_text(json.dumps({"delivery_status": "sent"}), encoding="utf-8")
        assert find_waiting_jobs(base, delivery_root=delivery) == []
    finally:
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(delivery, ignore_errors=True)


def main():
    test_reader_filters_waiting_jobs()
    test_reader_ignores_delivered_jobs()
    print("test_videoautopipeline_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
