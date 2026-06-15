from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from config import project_path
from modules import watch_folder
from modules.auto_qc import run_auto_qc_fix
from modules.queue_engine import QueueEngine
from modules.videoautopipeline_detector import DEFAULT_VIDEOAUTOPIPELINE_ROOT, detect_videoautopipeline_outputs
from modules.watch_folder import WatchExecutor, WatchOptions


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


def _output_dir(base_output_dir: str | Path | None, cycle_id: str) -> Path | None:
    if not base_output_dir:
        return None
    return Path(base_output_dir) / cycle_id


def run_auto_qc_executor(staging_dir: Path, options: WatchOptions, cycle_id: str, ready_count: int) -> dict:
    return run_auto_qc_fix(
        staging_dir,
        auto_fix=options.auto_fix,
        copy_results=options.copy_results,
        output_dir=_output_dir(options.output_dir, cycle_id),
        limit=ready_count,
        allow_original_short=options.allow_original_short,
        short_clip_min_duration=options.short_clip_min_duration,
        force=True,
    )


def run_watch_cycle(
    options: WatchOptions,
    *,
    now_func: Callable[[], datetime] = watch_folder.utc_now,
    executor: WatchExecutor = run_auto_qc_executor,
) -> dict:
    return watch_folder.run_watch_cycle(options, now_func=now_func, executor=executor)


def run_watch(
    options: WatchOptions,
    *,
    now_func: Callable[[], datetime] = watch_folder.utc_now,
    sleep_func: Callable[[float], None] = time.sleep,
    executor: WatchExecutor = run_auto_qc_executor,
) -> list[dict]:
    return watch_folder.run_watch(options, now_func=now_func, sleep_func=sleep_func, executor=executor)


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
