import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules.videoautopipeline_contract import find_waiting_jobs


def root():
    path = project_path("data/temp") / f"vap_contract_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_job(base: Path, job_id: str, status: str = "succeeded_waiting_for_plato", *, final: bool = True, after_plato: bool = True, davinci_required: bool = False, davinci_ok: bool = True):
    job = base / job_id
    (job / "status").mkdir(parents=True)
    (job / "metadata").mkdir(parents=True)
    (job / "final").mkdir(parents=True)
    final_path = job / "final" / f"{job_id}.mp4"
    if final:
        final_path.write_bytes(b"video")
    (job / "metadata" / f"{job_id}.metadata.json").write_text("{}", encoding="utf-8")
    payload = {
        "job_id": job_id,
        "status": status,
        "send_mode": "after_plato" if after_plato else "immediate",
        "plato_required": after_plato,
        "plato_input_path": str(final_path),
    }
    if davinci_required:
        payload.update({
            "davinci_mode": "required",
            "davinci_attempted": True,
            "davinci_succeeded": davinci_ok,
            "davinci_output_path": str(final_path) if davinci_ok else "",
            "davinci_error": "" if davinci_ok else "DaVinci failed",
        })
    (job / "status" / f"{job_id}.status.json").write_text(json.dumps(payload), encoding="utf-8")


def test_reader_filters_waiting_jobs():
    base = root()
    delivery = root()
    try:
        write_job(base, "ready")
        write_job(base, "davinci_ready", davinci_required=True)
        write_job(base, "davinci_failed", davinci_required=True, davinci_ok=False)
        write_job(base, "failed", status="failed")
        write_job(base, "running", status="running")
        write_job(base, "missing", final=False)
        write_job(base, "immediate", after_plato=False)
        jobs = find_waiting_jobs(base, delivery_root=delivery)
        assert [job["job_id"] for job in jobs] == ["davinci_ready", "ready"]
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


def test_reader_prefers_ranked_davinci_final_when_required():
    base = root()
    delivery = root()
    try:
        job = base / "ready"
        (job / "status").mkdir(parents=True)
        (job / "metadata").mkdir(parents=True)
        final_dir = job / "final"
        final_dir.mkdir(parents=True)
        old = final_dir / "123_clip_01_rank_03_score_8_2_with_ad_final.mp4"
        low = final_dir / "123_clip_02_rank_09_score_7_5_davinci_with_ad_final.mp4"
        best = final_dir / "123_clip_23_rank_01_score_8_7_davinci_with_ad_final.mp4"
        for path in (old, low, best):
            path.write_bytes(b"video")
        (job / "metadata" / "ready.metadata.json").write_text("{}", encoding="utf-8")
        (job / "status" / "ready.status.json").write_text(json.dumps({
            "job_id": "ready",
            "status": "succeeded_waiting_for_plato",
            "send_mode": "after_plato",
            "plato_required": True,
            "plato_input_path": str(old),
            "davinci_mode": "required",
            "davinci_attempted": True,
            "davinci_succeeded": True,
            "davinci_output_path": str(final_dir / "deleted_temp.mov"),
        }), encoding="utf-8")

        jobs = find_waiting_jobs(base, delivery_root=delivery)
        assert len(jobs) == 1
        assert jobs[0]["final_path"] == str(best.resolve())
    finally:
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(delivery, ignore_errors=True)


def test_reader_rejects_required_davinci_when_final_missing():
    base = root()
    delivery = root()
    try:
        write_job(base, "missing_final", final=False, davinci_required=True)
        assert find_waiting_jobs(base, delivery_root=delivery) == []
    finally:
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(delivery, ignore_errors=True)


def main():
    test_reader_filters_waiting_jobs()
    test_reader_ignores_delivered_jobs()
    test_reader_prefers_ranked_davinci_final_when_required()
    test_reader_rejects_required_davinci_when_final_missing()
    print("test_videoautopipeline_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
