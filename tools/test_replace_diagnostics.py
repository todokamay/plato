import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules.replace_diagnostics import replace_diagnostics, summary_text


def main() -> int:
    root = project_path("data/temp") / f"replace_diag_{uuid.uuid4().hex[:8]}"
    try:
        missing = replace_diagnostics(root / "logs" / "replace_log.json")
        assert missing["ok"] is True
        assert missing["status"] == "never_used"
        assert missing["rollback_available"] is False

        backup = root / "backups" / "clip.mp4"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(b"backup")
        log_path = root / "logs" / "replace_log.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            json.dumps(
                {
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "items": [
                        {"filename": "clip.mp4", "status": "replaced", "original_path": str(root / "clip.mp4"), "backup_path": str(backup)},
                        {"filename": "missing.mp4", "status": "replaced", "original_path": str(root / "missing.mp4"), "backup_path": str(root / "missing_backup.mp4")},
                        {"filename": "reject.mp4", "status": "skipped", "reason": "fixed clip was not accepted"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        summary = replace_diagnostics(log_path)
        assert summary["ok"] is True
        assert summary["total_replacements"] == 2
        assert summary["missing_backups"] == [str(root / "missing_backup.mp4")]
        assert summary["rollback_available"] is False
        assert len(summary["skipped_replacements"]) == 1
        assert "Replace Diagnostics" in summary_text(summary)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("test_replace_diagnostics: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
