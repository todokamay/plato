import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app
from modules.instagram_queue import load_queue
from routes import api
from tools.build_instagram_queue import build_from_delivery


def write_summary(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps({"jobs": rows}), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        summary = root / "delivery_summary.json"
        queue_file = root / "queue.json"
        approved = root / "approved" / "clip.mp4"
        duplicate = root / "approved" / "clip.mp4"
        raw = root / "Raw" / "raw.mp4"
        source_final = root / "final" / "source.mp4"
        write_summary(
            summary,
            [
                {"job_id": "ok", "approved_output_path": str(approved), "plato_verdict": "PUBLISH", "plato_score": 91},
                {"job_id": "dup", "approved_output_path": str(duplicate), "plato_verdict": "PUBLISH", "plato_score": 90},
                {"job_id": "empty", "approved_output_path": "", "plato_verdict": "PUBLISH"},
                {"job_id": "reject", "approved_output_path": str(root / "approved" / "reject.mp4"), "plato_verdict": "REJECT"},
                {"job_id": "raw", "approved_output_path": str(raw), "plato_verdict": "PUBLISH"},
                {"job_id": "source", "approved_output_path": str(source_final), "source_final_path": str(source_final), "plato_verdict": "PUBLISH"},
            ],
        )

        dry = build_from_delivery(summary, dry_run=True, queue_file=queue_file)
        assert dry["dry_run"] is True
        assert not queue_file.exists()

        result = build_from_delivery(summary, queue_file=queue_file)
        assert result["queued"] == 1
        assert result["skipped"] == 5
        assert len(load_queue(queue_file)["items"]) == 1
        reasons = " ".join(item["reason"] for item in result["reasons"])
        assert "duplicate" in reasons
        assert "empty" in reasons
        assert "not queue-eligible" in reasons
        assert "raw" in reasons
        assert "source_final_path" in reasons

    client = TestClient(app)
    html = client.get("/operator").text
    assert "Instagram Queue" in html
    assert "Build Queue" in html
    assert "No publishing in this phase" in html

    original_build = api.build_from_delivery
    api.build_from_delivery = lambda *args, **kwargs: {"queued": 1, "skipped": 0, "reasons": [], "items": [], "dry_run": False}
    try:
        payload = client.post("/api/operator/build-instagram-queue", json={}).json()
    finally:
        api.build_from_delivery = original_build
    assert payload["ok"] is True
    assert payload["queued"] == 1

    queue_payload = client.get("/api/operator/instagram-queue").json()
    assert queue_payload["ok"] is True
    assert "counts" in queue_payload

    print("test_build_instagram_queue: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
