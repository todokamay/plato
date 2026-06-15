import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules import operator_actions


def main() -> int:
    root = project_path("data/temp") / f"operator_replace_{uuid.uuid4().hex[:8]}"
    source = root / "input"
    backup = root / "backups"
    log_path = root / "logs" / "replace_log.json"
    original_start_job = operator_actions.start_job
    calls = []

    def fake_start_job(action, **kwargs):
        calls.append({"action": action, "kwargs": kwargs})
        return {"job_id": f"job_{len(calls)}", "job_type": action, "status": "queued", "args": kwargs}

    try:
        source.mkdir(parents=True, exist_ok=True)
        (source / "clip.mp4").write_bytes(b"video")
        operator_actions.start_job = fake_start_job

        unconfirmed = operator_actions.start_auto_qc_replace_job(
            source,
            backup,
            replace_enabled=True,
            replace_confirmed=False,
        )
        assert unconfirmed["ok"] is False
        assert not calls

        unsafe = operator_actions.start_auto_qc_replace_job(
            project_path(".").resolve(),
            backup,
            replace_enabled=True,
            replace_confirmed=True,
        )
        assert unsafe["ok"] is False
        assert "safe input folder" in unsafe["error"]
        assert not calls

        started = operator_actions.start_auto_qc_replace_job(
            source,
            backup,
            replace_enabled=True,
            replace_confirmed=True,
        )
        assert started["ok"] is True
        assert calls[-1]["action"] == "auto_qc_replace_once"
        assert calls[-1]["kwargs"]["folder"] == str(source.resolve())
        assert calls[-1]["kwargs"]["backup_dir"] == str(backup.resolve())

        missing_log = operator_actions.start_replace_rollback_job(root / "missing" / "replace_log.json")
        assert missing_log["ok"] is False
        assert "not found" in missing_log["error"]

        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps({"items": []}), encoding="utf-8")
        rollback = operator_actions.start_replace_rollback_job(log_path)
        assert rollback["ok"] is True
        assert calls[-1]["action"] == "rollback_replace_log"
        assert calls[-1]["kwargs"]["log_path"] == str(log_path.resolve())
    finally:
        operator_actions.start_job = original_start_job
        shutil.rmtree(root, ignore_errors=True)

    print("test_operator_replace_actions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
