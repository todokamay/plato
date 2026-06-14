from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from config import project_path
from modules.event_bus import EventBus
from modules.health_engine import system_health
from modules.history_engine import record_history
from modules.log_center import write_log
from modules.queue_engine import QueueEngine
from modules.recovery import recover_all
from modules.report_center import report_payload
from modules.watch_engine import WatchEngine, WatchEngineOptions, discover_watch_sources


ORCHESTRATOR_STATES = {"booting", "ready", "running", "recovering", "paused", "degraded", "failed", "stopped"}


@dataclass
class OrchestratorConfig:
    state: str = "booting"
    queue_file: Path = project_path("data/queue/queue.json")
    watch_state_file: Path = project_path("data/watch_state/watch_state.json")
    resource_limits: dict = field(default_factory=lambda: {"max_files_per_cycle": 10, "min_disk_free_ratio": 0.05})


class VideoFactoryOrchestrator:
    def __init__(self, config: OrchestratorConfig | None = None):
        self.config = config or OrchestratorConfig()
        self.state = self.config.state
        self.events = EventBus()
        self.queue = QueueEngine(self.config.queue_file)
        sources = discover_watch_sources()
        self.watch = WatchEngine(
            WatchEngineOptions(
                sources=sources,
                queue_file=self.config.queue_file,
                max_files_per_cycle=int(self.config.resource_limits.get("max_files_per_cycle", 10)),
            )
        )

    def transition(self, state: str, reason: str = "") -> dict:
        if state not in ORCHESTRATOR_STATES:
            raise ValueError(f"Unsupported orchestrator state: {state}")
        self.state = state
        payload = {"state": state, "reason": reason}
        self.events.publish("started" if state == "running" else "detected", payload, source="orchestrator")
        write_log(f"orchestrator state={state} {reason}".strip(), source="orchestrator")
        return payload

    def recover(self) -> dict:
        self.transition("recovering", "startup recovery")
        result = recover_all(queue_file=self.config.queue_file, watch_state_file=self.config.watch_state_file)
        self.transition("ready", "recovery complete")
        return result

    def health(self) -> dict:
        health = system_health(queue_file=self.config.queue_file)
        if health["state"] == "critical":
            self.state = "degraded"
        return {"orchestrator_state": self.state, "health": health}

    def run_once(self) -> dict:
        self.transition("running", "single cycle")
        watch_result = self.watch.cycle()
        health = self.health()
        report = report_payload("all-time")
        record_history("factory", action="orchestrator_cycle", status=self.state, details={"watch": watch_result, "health": health})
        self.transition("ready", "single cycle complete")
        return {"state": self.state, "watch": watch_result, "health": health, "report": report}

    def pause(self) -> dict:
        return self.transition("paused", "manual pause")

    def stop(self) -> dict:
        return self.transition("stopped", "shutdown")


def orchestrator_status() -> dict:
    orchestrator = VideoFactoryOrchestrator()
    return orchestrator.health()
