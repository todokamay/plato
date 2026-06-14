from __future__ import annotations

from modules.health_engine import system_health
from modules.log_center import cleanup_logs, write_log
from modules.storage_manager import cleanup_generated_files


def heartbeat() -> dict:
    health = system_health()
    write_log(f"heartbeat state={health['state']}", source="background")
    return {"task": "heartbeat", "health": health}


def maintenance() -> dict:
    removed_logs = cleanup_logs()
    removed_temp = cleanup_generated_files("data", patterns=("*.tmp",))
    write_log(f"maintenance removed_logs={len(removed_logs)} removed_temp={len(removed_temp)}", source="background")
    return {"task": "maintenance", "removed_logs": removed_logs, "removed_temp": removed_temp}
