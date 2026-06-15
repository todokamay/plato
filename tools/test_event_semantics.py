import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules.event_bus import EVENT_TYPES, EventBus
from modules.orchestrator import (
    OrchestratorConfig,
    VideoFactoryOrchestrator,
    lifecycle_event_type,
)


NEW_EVENT_TYPES = {
    "completed",
    "success",
    "state_changed",
    "paused",
    "stopped",
    "recovered",
}

LEGACY_EVENT_TYPES = {
    "detected",
    "started",
    "fixed",
    "accepted",
    "rejected",
    "rerouted",
    "failed",
}


def temp_root() -> Path:
    root = project_path("data/temp") / f"event_semantics_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_event_bus_accepts_new_types():
    bus = EventBus(temp_root() / "events.jsonl")
    try:
        for event_type in NEW_EVENT_TYPES | LEGACY_EVENT_TYPES:
            assert event_type in EVENT_TYPES
            event = bus.publish(event_type, {"probe": True}, source="test")
            assert event["event_type"] == event_type
    finally:
        shutil.rmtree(bus.log_path.parent, ignore_errors=True)


def test_lifecycle_event_mapping():
    assert lifecycle_event_type("booting") == "state_changed"
    assert lifecycle_event_type("ready") == "state_changed"
    assert lifecycle_event_type("running") == "started"
    assert lifecycle_event_type("paused") == "paused"
    assert lifecycle_event_type("stopped") == "stopped"
    assert lifecycle_event_type("failed") == "failed"
    assert lifecycle_event_type("recovering") == "state_changed"
    assert lifecycle_event_type("ready", "single cycle complete") == "completed"
    assert lifecycle_event_type("ready", "recovery complete") == "recovered"


def test_orchestrator_publishes_semantic_events():
    root = temp_root()
    try:
        orchestrator = VideoFactoryOrchestrator(
            OrchestratorConfig(
                queue_file=root / "queue.json",
                watch_state_file=root / "watch_state.json",
                watch_enabled=False,
                resource_limits={"max_files_per_cycle": 1},
            )
        )
        orchestrator.events.log_path = root / "events.jsonl"

        orchestrator.transition("running", "test run")
        orchestrator.transition("paused", "manual pause")
        orchestrator.transition("stopped", "shutdown")
        orchestrator.transition("recovering", "startup recovery")
        orchestrator.transition("ready", "recovery complete")
        orchestrator.transition("running", "single dry-run cycle")
        orchestrator.transition("ready", "single cycle complete")

        events = orchestrator.events.recent(20)
        types = [event["event_type"] for event in events]
        assert "started" in types
        assert "paused" in types
        assert "stopped" in types
        assert "state_changed" in types
        assert "recovered" in types
        assert "completed" in types
        assert "detected" not in types

        for event in events:
            payload = event.get("payload") or {}
            assert "lifecycle_state" in payload
            assert payload.get("state") == payload.get("lifecycle_state")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    test_event_bus_accepts_new_types()
    test_lifecycle_event_mapping()
    test_orchestrator_publishes_semantic_events()
    print("test_event_semantics: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
