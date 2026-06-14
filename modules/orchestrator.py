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
from modules.videoautopipeline_detector import DEFAULT_VIDEOAUTOPIPELINE_ROOT, detect_videoautopipeline_outputs


ORCHESTRATOR_STATES = {"booting", "ready", "running", "recovering", "paused", "degraded", "failed", "stopped"}
START_COMMAND = (
    r"py tools\run_orchestrator.py --detect-videoautopipeline-outputs --watch "
    r"--auto-fix --copy-results --allow-original-short --short-clip-min-duration 5"
)


@dataclass
class OrchestratorConfig:
    state: str = "booting"
    queue_file: Path = project_path("data/queue/queue.json")
    watch_state_file: Path = project_path("data/watch_state/watch_state.json")
    resource_limits: dict = field(default_factory=lambda: {"max_files_per_cycle": 10, "min_disk_free_ratio": 0.05})
    detect_videoautopipeline_outputs: bool = False
    videoautopipeline_root: Path = DEFAULT_VIDEOAUTOPIPELINE_ROOT
    watch_enabled: bool = True
    dry_run: bool = False
    auto_fix: bool = False
    copy_results: bool = False
    allow_original_short: bool = False
    short_clip_min_duration: float = 5.0


class VideoFactoryOrchestrator:
    def __init__(self, config: OrchestratorConfig | None = None):
        self.config = config or OrchestratorConfig()
        self.state = self.config.state
        self.events = EventBus()
        self.queue = QueueEngine(self.config.queue_file)
        self.detection = self._detect_outputs() if self.config.detect_videoautopipeline_outputs else None
        sources = discover_watch_sources(self.config.videoautopipeline_root) if self.config.watch_enabled else []
        self.watch = WatchEngine(
            WatchEngineOptions(
                sources=sources,
                queue_file=self.config.queue_file,
                max_files_per_cycle=int(self.config.resource_limits.get("max_files_per_cycle", 10)),
            )
        )

    def _detect_outputs(self) -> dict:
        return detect_videoautopipeline_outputs(self.config.videoautopipeline_root)

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
        return {
            "orchestrator_state": self.state,
            "health": health,
            "detection": self.detection,
            "operator_guidance": {
                "status_command": r"py tools\run_orchestrator.py --status-only",
                "dry_run_command": r"py tools\run_orchestrator.py --once --dry-run",
                "continuous_command": START_COMMAND,
            },
        }

    def run_once(self, *, dry_run: bool | None = None, watch: bool | None = None) -> dict:
        dry_run = self.config.dry_run if dry_run is None else dry_run
        watch_enabled = self.config.watch_enabled if watch is None else watch
        self.transition("running", "single dry-run cycle" if dry_run else "single cycle")
        if watch_enabled:
            watch_result = self.watch.cycle()
            if not watch_result.get("sources"):
                watch_result["operator_message"] = "No watch sources found yet. Run detector or pass a manual watch folder."
                watch_result["suggested_command"] = START_COMMAND
        else:
            watch_result = {
                "sources": [],
                "enqueued": [],
                "queue": self.queue.stats(),
                "operator_message": "Watch scan disabled for this run.",
                "suggested_command": r"py tools\run_orchestrator.py --once --dry-run --watch",
            }
        health = self.health()
        report = report_payload("all-time")
        record_history(
            "factory",
            action="orchestrator_dry_run" if dry_run else "orchestrator_cycle",
            status=self.state,
            details={"watch": watch_result, "health": health, "dry_run": dry_run},
        )
        self.transition("ready", "single cycle complete")
        return {"state": self.state, "dry_run": dry_run, "watch": watch_result, "health": health, "report": report}

    def pause(self) -> dict:
        return self.transition("paused", "manual pause")

    def stop(self) -> dict:
        return self.transition("stopped", "shutdown")


def orchestrator_status() -> dict:
    orchestrator = VideoFactoryOrchestrator()
    return orchestrator.health()
