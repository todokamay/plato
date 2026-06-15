import json
import shutil
import uuid

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules.production_diagnostics import export_production_diagnostics, production_diagnostics_snapshot, sanitize_for_diagnostics


def main() -> int:
    snapshot = production_diagnostics_snapshot(include_checks=False)
    assert snapshot["ok"] is True
    assert "generated_at" in snapshot
    assert "latest_runs" in snapshot
    assert "recommendations" in snapshot
    assert ".mp4" not in json.dumps(snapshot).lower()

    redacted = sanitize_for_diagnostics({"path": r"C:\clips\clip.mp4", "db": "data/app.sqlite3", "token": "abc"})
    assert redacted["path"] == "[media path omitted]"
    assert redacted["db"] == "[database path omitted]"
    assert redacted["token"] == "[redacted]"

    root = project_path("data/temp") / f"prod_diag_{uuid.uuid4().hex[:8]}"
    try:
        result = export_production_diagnostics(root)
        assert result["ok"] is True
        assert Path(result["diagnostics_json"]).exists()
        assert Path(result["diagnostics_summary"]).exists()
        data = json.loads(Path(result["diagnostics_json"]).read_text(encoding="utf-8"))
        assert data["ok"] is True
        assert ".mp4" not in json.dumps(data).lower()
        assert ".sqlite" not in json.dumps(data).lower()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("test_production_diagnostics: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
