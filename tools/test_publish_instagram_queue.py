import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app
from modules.instagram_queue import load_queue, save_queue
from routes import api


def write_queue(path: Path, mp4: Path) -> None:
    save_queue(
        {
            "version": 1,
            "items": [
                {
                    "job_id": "cli",
                    "approved_output_path": str(mp4),
                    "caption": "caption",
                    "hashtags": [],
                    "score": 91,
                    "verdict": "PUBLISH",
                    "created_at": "",
                    "scheduled_at": "",
                    "status": "queued",
                    "attempts": 0,
                    "error": "",
                }
            ],
        },
        path,
    )


def run_cli(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "tools/publish_instagram_queue.py", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        queue_file = root / "queue.json"
        mp4 = root / "approved.mp4"
        mp4.write_bytes(b"fake mp4")
        write_queue(queue_file, mp4)

        peek = run_cli("--queue", str(queue_file), "--peek", "--json")
        assert peek.returncode == 0
        assert json.loads(peek.stdout)["item"]["job_id"] == "cli"
        assert load_queue(queue_file)["items"][0]["status"] == "queued"

        refused = run_cli("--queue", str(queue_file), "--json")
        assert refused.returncode == 1
        assert "not implemented" in json.loads(refused.stdout)["reason"]
        assert load_queue(queue_file)["items"][0]["status"] == "queued"

        dry = run_cli("--queue", str(queue_file), "--dry-run", "--json")
        assert dry.returncode == 0
        payload = json.loads(dry.stdout)
        assert payload["status"] == "posted_dry_run"
        assert load_queue(queue_file)["items"][0]["status"] == "posted_dry_run"

    client = TestClient(app)
    html = client.get("/operator").text
    assert "Publish Next Dry Run" in html
    assert "Peek Next Queue Item" in html
    assert "posted_dry_run" in html or "Posted dry-run" in html

    original_publish = api.publish_one_dry_run
    api.publish_one_dry_run = lambda **kwargs: {"ok": True, "dry_run": True, "published": False, "status": "posted_dry_run", "reason": "dry-run publish simulated"}
    try:
        result = client.post("/api/operator/instagram-publish-next-dry-run", json={}).json()
    finally:
        api.publish_one_dry_run = original_publish
    assert result["ok"] is True
    assert result["published"] is False
    assert result["status"] == "posted_dry_run"

    original_next = api.get_next_queue_item
    api.get_next_queue_item = lambda queue: {"job_id": "peek", "approved_output_path": "x.mp4"}
    try:
        result = client.get("/api/operator/instagram-queue-next").json()
    finally:
        api.get_next_queue_item = original_next
    assert result["ok"] is True
    assert result["item"]["job_id"] == "peek"

    print("test_publish_instagram_queue: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
