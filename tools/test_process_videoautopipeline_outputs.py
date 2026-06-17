import json
import os
import shutil
import uuid
from pathlib import Path

from config import project_path
from tools import process_videoautopipeline_outputs as tool


def root():
    path = project_path("data/temp") / f"vap_process_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_job(base: Path, job_id: str = "job1") -> Path:
    job = base / job_id
    (job / "status").mkdir(parents=True)
    (job / "metadata").mkdir(parents=True)
    (job / "final").mkdir(parents=True)
    final = job / "final" / "clip.mp4"
    final.write_bytes(b"original")
    (job / "metadata" / f"{job_id}.metadata.json").write_text("{}", encoding="utf-8")
    (job / "status" / f"{job_id}.status.json").write_text(json.dumps({
        "job_id": job_id,
        "status": "succeeded_waiting_for_plato",
        "send_mode": "after_plato",
        "plato_required": True,
        "plato_input_path": str(final),
    }), encoding="utf-8")
    return final


def test_dry_run_writes_summary_and_preserves_source():
    base = root()
    delivery = root()
    try:
        final = write_job(base)
        before = final.read_bytes()
        old = os.environ.get("PLATO_VAP_DELIVERY_ROOT")
        os.environ["PLATO_VAP_DELIVERY_ROOT"] = str(delivery)
        try:
            assert tool.main([str(base), "--dry-run"]) == 0
        finally:
            if old is None:
                os.environ.pop("PLATO_VAP_DELIVERY_ROOT", None)
            else:
                os.environ["PLATO_VAP_DELIVERY_ROOT"] = old
        assert final.read_bytes() == before
        summary = json.loads((delivery / "delivery_summary.json").read_text(encoding="utf-8"))
        assert summary["count"] == 1
        assert (delivery / "delivery_summary.csv").exists()
        assert (delivery / "jobs" / "job1.json").exists()
    finally:
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(delivery, ignore_errors=True)


def main():
    test_dry_run_writes_summary_and_preserves_source()
    print("test_process_videoautopipeline_outputs: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
