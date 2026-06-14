import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app
from config import project_path


def assert_json(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    return response.json()


def wait_for_job(client: TestClient, job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = assert_json(client.get(f"/api/operator/jobs/{job_id}"))
        job = payload.get("job") or {}
        if job.get("status") in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.1)
    raise AssertionError(f"operator job did not finish: {job_id}")


def main() -> int:
    client = TestClient(app)

    status = assert_json(client.get("/api/operator/status"))
    assert "jobs" in status
    assert "queue" in status

    detect = assert_json(client.post("/api/operator/detect"))
    assert detect["ok"] is True
    assert "job" in detect
    wait_for_job(client, detect["job"]["job_id"])

    dry = assert_json(client.post("/api/operator/dry-run"))
    assert dry["ok"] is True
    assert "job" in dry
    wait_for_job(client, dry["job"]["job_id"])

    project_root_rejected = assert_json(client.post("/api/operator/auto-qc-once", json={"folder": str(project_path(".").resolve())}))
    assert project_root_rejected["ok"] is False
    assert "safe input folder" in project_root_rejected["error"]

    stop = assert_json(client.post("/api/operator/watch/stop"))
    assert stop["ok"] is True

    jobs = assert_json(client.get("/api/operator/jobs"))
    assert isinstance(jobs.get("jobs"), list)
    if jobs["jobs"]:
        detail = assert_json(client.get(f"/api/operator/jobs/{jobs['jobs'][0]['job_id']}"))
        assert "job" in detail

    print("test_operator_api: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
