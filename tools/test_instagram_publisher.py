import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.instagram_publisher import get_next_queue_item, publish_one_dry_run, validate_publish_item
from modules.instagram_queue import load_queue, save_queue


def write_queue(path: Path, items: list[dict]) -> None:
    save_queue({"version": 1, "items": items}, path)


def item(path: Path, **extra) -> dict:
    data = {
        "job_id": path.stem or "job",
        "approved_output_path": str(path),
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
    data.update(extra)
    return data


def main() -> int:
    source = (ROOT / "modules" / "instagram_publisher.py").read_text(encoding="utf-8").lower()
    assert "selenium" not in source

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        queue_file = root / "queue.json"
        mp4 = root / "approved" / "clip.mp4"
        mp4.parent.mkdir()
        mp4.write_bytes(b"fake mp4")

        write_queue(queue_file, [item(mp4)])
        result = publish_one_dry_run(queue_file)
        assert result["ok"] is True
        assert result["published"] is False
        assert result["status"] == "posted_dry_run"
        stored = load_queue(queue_file)["items"][0]
        assert stored["status"] == "posted_dry_run"
        assert stored["attempts"] == 1
        assert stored["posted_at"]
        assert stored["error"] == ""
        assert (root / "posted.json").exists()

        assert publish_one_dry_run(queue_file)["ok"] is True
        assert publish_one_dry_run(queue_file)["status"] == "no_item"

        write_queue(queue_file, [item(mp4, approved_output_path="")])
        failed = publish_one_dry_run(queue_file)
        assert failed["ok"] is False
        assert "empty" in failed["reason"]
        assert load_queue(queue_file)["items"][0]["status"] == "failed"
        assert load_queue(queue_file)["items"][0]["attempts"] == 1

        missing = root / "approved" / "missing.mp4"
        write_queue(queue_file, [item(missing)])
        failed = publish_one_dry_run(queue_file)
        assert failed["ok"] is False
        assert "missing" in failed["reason"]

        write_queue(queue_file, [item(mp4, verdict="REJECT")])
        failed = publish_one_dry_run(queue_file)
        assert failed["ok"] is False
        assert "not publishable" in failed["reason"]

        raw = root / "Raw" / "clip.mp4"
        raw.parent.mkdir(exist_ok=True)
        raw.write_bytes(b"fake mp4")
        write_queue(queue_file, [item(raw)])
        failed = publish_one_dry_run(queue_file)
        assert failed["ok"] is False
        assert "raw/source/intermediate" in failed["reason"]

        assert validate_publish_item(item(mp4, caption="x" * 2201))[0] is False
        assert get_next_queue_item({"items": [item(mp4, status="posted_dry_run"), item(mp4, job_id="next")]})["job_id"] == "next"

    print("test_instagram_publisher: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
