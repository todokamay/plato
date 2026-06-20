import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.instagram_queue import build_queue_item, enqueue, get_stats, list_items, mark_state


def row(path: Path, verdict: str = "PUBLISH", **extra) -> dict:
    data = {"job_id": path.stem, "approved_output_path": str(path), "plato_verdict": verdict, "plato_score": 88}
    data.update(extra)
    return data


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        queue_file = root / "queue.json"
        approved = root / "approved" / "clip.mp4"

        item, reason = build_queue_item(row(approved))
        assert item is not None, reason
        stored, created = enqueue(item, queue_file=queue_file)
        assert created is True
        assert stored["approved_output_path"] == str(approved)
        assert get_stats(queue_file)["counts"]["queued"] == 1

        duplicate, _ = build_queue_item(row(approved))
        stored, created = enqueue(duplicate, queue_file=queue_file)
        assert created is False
        assert len(list_items(queue_file)) == 1

        rejected, reason = build_queue_item(row(root / "approved" / "reject.mp4", "REJECT"))
        assert rejected is None
        assert "not queue-eligible" in reason

        empty, reason = build_queue_item({"job_id": "empty", "approved_output_path": "", "plato_verdict": "PUBLISH"})
        assert empty is None
        assert "empty" in reason

        raw, reason = build_queue_item(row(root / "Raw" / "clip.mp4"))
        assert raw is None
        assert "raw" in reason

        source_final, reason = build_queue_item(row(root / "final" / "same.mp4", source_final_path=str(root / "final" / "same.mp4")))
        assert source_final is None
        assert "source_final_path" in reason

        safe_default, _ = build_queue_item(row(root / "approved" / "safe.mp4", "SAFE TO TEST"))
        assert safe_default is None
        safe_allowed, _ = build_queue_item(row(root / "approved" / "safe.mp4", "SAFE TO TEST"), allow_safe_to_test=True)
        assert safe_allowed is not None

        marked = mark_state(stored["job_id"], "failed", error="test", queue_file=queue_file)
        assert marked["status"] == "failed"
        assert get_stats(queue_file)["counts"]["failed"] == 1

    print("test_instagram_queue: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
