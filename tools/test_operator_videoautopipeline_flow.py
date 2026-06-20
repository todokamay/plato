import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app
import routes.api as api


def main() -> int:
    external_app = Path(r"C:\Users\User\Desktop\Work\VideoAutoPipeline\app.py")
    before_mtime = external_app.stat().st_mtime if external_app.exists() else None
    client = TestClient(app)

    original = api.start_videoautopipeline_worker_job
    api.start_videoautopipeline_worker_job = lambda *args, **kwargs: {
        "ok": True,
        "job": {"job_id": "api-job", "job_type": "run_videoautopipeline_worker", "status": "queued"},
    }
    try:
        payload = client.post("/api/operator/videoautopipeline-worker", json={"input_video": "C:\\clips\\a.mp4"}).json()
    finally:
        api.start_videoautopipeline_worker_job = original
    assert payload["ok"] is True
    assert payload["job"]["job_type"] == "run_videoautopipeline_worker"

    html = client.get("/operator").text
    assert "Video Generation" in html
    assert "VideoAutoPipeline Tools" in html
    assert "Plato Quality Gate" in html
    assert "Open VideoAutoPipeline GUI" in html
    assert "Generate From LongVideos" in html
    assert "Process Waiting For Plato" in html
    assert "VideoAutoPipeline &rarr; Plato Flow" in html
    assert "Run VideoAutoPipeline Worker" in html
    assert "Run VideoAutoPipeline Batch" in html
    assert "Process VideoAutoPipeline Outputs With Plato" in html
    assert "Run Full Flow" in html
    assert "Telegram happens only after Plato approval" in html
    assert "Dry-run is default" in html
    assert "id=\"vap-dry-run\" type=\"checkbox\" checked" in html
    assert "id=\"vap-send-telegram\" type=\"checkbox\"" in html
    assert "id=\"vap-send-telegram\" type=\"checkbox\" checked" not in html

    after_mtime = external_app.stat().st_mtime if external_app.exists() else None
    assert before_mtime == after_mtime

    print("test_operator_videoautopipeline_flow: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
