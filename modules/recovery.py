from __future__ import annotations

from pathlib import Path

from modules.queue_engine import load_queue, save_queue
from modules.watch_folder import load_state, save_state


def recover_queue(queue_file: str | Path) -> dict:
    queue = load_queue(queue_file)
    recovered = 0
    for item in queue.get("items", []):
        if item.get("state") == "processing":
            item["state"] = "retry"
            item["last_error"] = "recovered after interrupted processing"
            recovered += 1
    save_queue(queue, queue_file)
    return {"recovered_processing_jobs": recovered, "queue_file": str(queue_file)}


def recover_watch_state(state_file: str | Path) -> dict:
    state = load_state(state_file)
    recovered = 0
    for entry in state.get("files", {}).values():
        if entry.get("status") == "processing":
            entry["status"] = "stable"
            entry["last_result"] = {"recovered": True, "reason": "interrupted processing reset to stable"}
            recovered += 1
    save_state(state_file, state)
    return {"recovered_processing_files": recovered, "state_file": str(state_file)}


def recover_all(*, queue_file: str | Path, watch_state_file: str | Path) -> dict:
    return {
        "queue": recover_queue(queue_file),
        "watch": recover_watch_state(watch_state_file),
        "runs": {"state": "ready"},
        "processing": {"state": "ready"},
    }
