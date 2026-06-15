import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules import job_runner, orchestrator, watch_folder
from modules.watch_engine import WatchSource


def make_root():
    root = project_path("data/temp") / f"orchestrator_contract_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_orchestrator_delegates_watch_cycle():
    root = make_root()
    original_watch_engine = orchestrator.WatchEngine
    original_discover = orchestrator.discover_watch_sources
    original_health = orchestrator.system_health
    original_report = orchestrator.report_payload
    original_history = orchestrator.record_history
    calls = []

    class FakeWatchEngine:
        def __init__(self, options):
            self.options = options
            calls.append({"event": "init", "options": options})

        def cycle(self):
            calls.append({"event": "cycle", "max_files": self.options.max_files_per_cycle})
            return {"sources": [{"name": "fake"}], "enqueued": [], "queue": {"total": 0}}

    try:
        (root / "watch").mkdir(parents=True, exist_ok=True)
        orchestrator.WatchEngine = FakeWatchEngine
        orchestrator.discover_watch_sources = lambda _root: [WatchSource("fake", root / "watch")]
        orchestrator.system_health = lambda queue_file=None: {"state": "ok", "checks": {}}
        orchestrator.report_payload = lambda view="all-time": {"view": view, "counts": {}}
        orchestrator.record_history = lambda *args, **kwargs: {"ok": True}

        config = orchestrator.OrchestratorConfig(
            queue_file=root / "queue.json",
            videoautopipeline_root=root,
            resource_limits={"max_files_per_cycle": 3},
            watch_enabled=True,
            dry_run=True,
        )
        result = orchestrator.VideoFactoryOrchestrator(config).run_once(dry_run=True, watch=True)

        assert calls[0]["event"] == "init"
        assert calls[0]["options"].sources[0].name == "fake"
        assert calls[0]["options"].queue_file == root / "queue.json"
        assert calls[0]["options"].max_files_per_cycle == 3
        assert calls[1] == {"event": "cycle", "max_files": 3}
        assert result["watch"]["sources"] == [{"name": "fake"}]
    finally:
        orchestrator.WatchEngine = original_watch_engine
        orchestrator.discover_watch_sources = original_discover
        orchestrator.system_health = original_health
        orchestrator.report_payload = original_report
        orchestrator.record_history = original_history
        shutil.rmtree(root, ignore_errors=True)


def test_watch_folder_has_no_auto_qc_owner_global():
    assert not hasattr(watch_folder, "run_auto_qc_fix")


def test_operator_watch_start_stop_contract_unchanged():
    definition = job_runner.ACTION_DEFINITIONS["start_watch_mode"]

    assert definition["args"][0] == "tools/watch_videoautopipeline_outputs.py"
    assert definition["requires_folder"] is True
    assert definition["cancellable"] is True
    assert definition["singleton"] is True

    root = make_root()
    try:
        result = job_runner.stop_running_watch(job_file=root / "jobs.json")
        assert result["ok"] is True
        assert result["message"] == "No running watch job."
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    test_orchestrator_delegates_watch_cycle()
    test_watch_folder_has_no_auto_qc_owner_global()
    test_operator_watch_start_stop_contract_unchanged()
    print("test_orchestrator_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
