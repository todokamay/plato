from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from config import project_path
from modules.queue_engine import QueueEngine
from modules.videoautopipeline_detector import DEFAULT_VIDEOAUTOPIPELINE_ROOT, detect_videoautopipeline_outputs
from modules.watch_folder import WatchOptions, run_watch_cycle


DEFAULT_MANUAL_IMPORTS = project_path("data/manual_imports")


@dataclass
class WatchSource:
    name: str
    folder: Path
    recursive: bool = False
    enabled: bool = True


@dataclass
class WatchEngineOptions:
    sources: list[WatchSource] = field(default_factory=list)
    state_root: Path = project_path("data/watch_engine")
    stable_seconds: float = 5.0
    max_files_per_cycle: int = 10
    auto_enqueue: bool = True
    queue_file: Path = project_path("data/queue/queue.json")


def discover_watch_sources(videoautopipeline_root: str | Path = DEFAULT_VIDEOAUTOPIPELINE_ROOT) -> list[WatchSource]:
    sources = []
    detection = detect_videoautopipeline_outputs(videoautopipeline_root)
    recommended = detection.get("recommended_input_folder")
    if recommended:
        sources.append(WatchSource("VideoAutoPipeline", Path(recommended), recursive=True))
    if DEFAULT_MANUAL_IMPORTS.exists():
        sources.append(WatchSource("manual_imports", DEFAULT_MANUAL_IMPORTS, recursive=True))
    return sources


class WatchEngine:
    def __init__(self, options: WatchEngineOptions | None = None):
        self.options = options or WatchEngineOptions(sources=discover_watch_sources())
        self.queue = QueueEngine(self.options.queue_file)

    def cycle(self) -> dict:
        source_results = []
        enqueued = []
        for source in self.options.sources:
            if not source.enabled or not source.folder.exists():
                source_results.append({"name": source.name, "folder": str(source.folder), "status": "skipped"})
                continue
            state_file = self.options.state_root / f"{source.name}_watch_state.json"
            payload = run_watch_cycle(
                WatchOptions(
                    watch_folder=source.folder,
                    state_file=state_file,
                    dry_run=True,
                    once=True,
                    stable_seconds=self.options.stable_seconds,
                    max_files_per_cycle=self.options.max_files_per_cycle,
                )
            )
            if self.options.auto_enqueue:
                for result in payload.get("results", []):
                    if result.get("status") == "skipped":
                        job = self.queue.enqueue(result["file_path"], priority=50, source=source.name)
                        enqueued.append(job)
            source_results.append({"name": source.name, "folder": str(source.folder), "payload": payload})
        return {"sources": source_results, "enqueued": enqueued, "queue": self.queue.stats()}
