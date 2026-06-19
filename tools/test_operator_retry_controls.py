import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app
from modules import operator_actions
from routes import api


def main() -> int:
    client = TestClient(app)
    html = client.get("/operator").text
    assert 'id="retry-full-pipeline"' in html
    assert 'id="retry-plato-only"' in html
    assert 'id="retry-delivery-only"' in html

    captured = {}
    original_process = operator_actions.start_process_videoautopipeline_outputs_job

    def fake_process(output_root=None, **kwargs):
        captured.update({"output_root": output_root, **kwargs})
        return {"ok": True, "job": {"job_id": "retry-delivery", "job_type": "process_videoautopipeline_outputs"}}

    operator_actions.start_process_videoautopipeline_outputs_job = fake_process
    try:
        result = operator_actions.start_retry_delivery_only_job({})
    finally:
        operator_actions.start_process_videoautopipeline_outputs_job = original_process
    assert result["ok"] is True
    assert captured["dry_run"] is True
    assert captured["send_telegram"] is False

    original_retry_full = api.start_retry_full_pipeline_job
    api.start_retry_full_pipeline_job = lambda data: {
        "ok": True,
        "job": {"job_id": "retry-full", "job_type": "run_full_videoautopipeline_to_plato_flow", "status": "queued"},
        "seen": data,
    }
    try:
        payload = client.post("/api/operator/retry-full-pipeline", json={"dry_run": True}).json()
    finally:
        api.start_retry_full_pipeline_job = original_retry_full
    assert payload["ok"] is True
    assert payload["job"]["job_type"] == "run_full_videoautopipeline_to_plato_flow"

    original_retry_delivery = api.start_retry_delivery_only_job
    api.start_retry_delivery_only_job = lambda data: {"ok": True, "seen": data, "job": {"job_id": "retry-delivery"}}
    try:
        payload = client.post("/api/operator/retry-delivery-only", json={}).json()
    finally:
        api.start_retry_delivery_only_job = original_retry_delivery
    assert payload["ok"] is True
    assert payload["seen"] == {}

    print("test_operator_retry_controls: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
