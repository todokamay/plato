import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app


def wait_for_job(client: TestClient, job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/api/operator/jobs/{job_id}").json()
        job = payload.get("job") or {}
        if job.get("status") in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.1)
    raise AssertionError(f"diagnostics export job did not finish: {job_id}")


def main() -> int:
    client = TestClient(app)
    response = client.get("/api/production-diagnostics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["ok"] is True
    for key in ["generated_at", "latest_runs", "replace", "queue", "jobs", "health", "watch_state", "recommendations"]:
        assert key in payload

    export = client.post("/api/operator/export-production-diagnostics")
    assert export.status_code == 200
    assert export.json()["ok"] is True
    assert export.json()["job"]["job_type"] == "export_production_diagnostics"
    finished = wait_for_job(client, export.json()["job"]["job_id"])
    assert finished["status"] == "completed"

    print("test_production_diagnostics_api: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
