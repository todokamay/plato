import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app
from config import project_path
from modules.config_system import load_factory_config
from modules.event_bus import EventBus
from modules.health_engine import system_health
from modules.history_engine import history_entries, record_history
from modules.orchestrator import OrchestratorConfig, VideoFactoryOrchestrator
from modules.queue_engine import QueueEngine
from modules.recovery import recover_all
from modules.router import copy_to_bucket


def temp_root() -> Path:
    root = project_path("data/temp") / f"factory_os_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_queue_recovery_history_and_routing():
    root = temp_root()
    try:
        source = root / "source.mp4"
        source.write_bytes(b"original")
        before = source.stat()
        queue_file = root / "queue" / "queue.json"
        watch_state = root / "watch" / "watch_state.json"

        queue = QueueEngine(queue_file)
        job = queue.enqueue(source, priority=80, source="test")
        queue.update(job["job_id"], "processing", {"started": True})
        recovered = recover_all(queue_file=queue_file, watch_state_file=watch_state)
        assert recovered["queue"]["recovered_processing_jobs"] == 1
        assert queue.stats()["counts"]["retry"] == 1

        history_log = root / "history.jsonl"
        record_history(str(source), action="qc", status="success", history_log=history_log)
        assert history_entries(str(source), history_log=history_log)[0]["status"] == "success"

        routed = copy_to_bucket(source, "archive", root=root / "routed")
        assert Path(routed["copied_path"]).exists()
        after = source.stat()
        assert before.st_size == after.st_size
        assert before.st_mtime_ns == after.st_mtime_ns
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_config_event_health_and_orchestrator():
    root = temp_root()
    try:
        config = load_factory_config("dev", {"watch": {"max_files_per_cycle": 2}})
        assert config["profile"] == "dev"
        assert config["watch"]["stable_seconds"] == 0
        assert config["watch"]["max_files_per_cycle"] == 2

        bus = EventBus(root / "events.jsonl")
        event = bus.publish("detected", {"file": "clip.mp4"}, "test")
        assert event["event_type"] == "detected"
        assert bus.recent(1)[0]["payload"]["file"] == "clip.mp4"

        health = system_health(queue_file=root / "queue.json")
        assert health["state"] in {"healthy", "warning", "critical"}

        orchestrator = VideoFactoryOrchestrator(
            OrchestratorConfig(
                queue_file=root / "queue.json",
                watch_state_file=root / "watch_state.json",
                resource_limits={"max_files_per_cycle": 1},
            )
        )
        payload = orchestrator.run_once()
        assert payload["state"] == "ready"
        assert "health" in payload
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_control_center_and_api_routes():
    client = TestClient(app)
    assert client.get("/control-center").status_code == 200
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/runs").status_code == 200
    assert client.get("/api/queue").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/history").status_code == 200


def main() -> int:
    test_queue_recovery_history_and_routing()
    test_config_event_health_and_orchestrator()
    test_control_center_and_api_routes()
    print("test_video_factory_os: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
