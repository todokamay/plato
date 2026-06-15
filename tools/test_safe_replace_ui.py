import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app


def main() -> int:
    client = TestClient(app)

    operator = client.get("/operator")
    assert operator.status_code == 200
    text = operator.text
    assert "Safe Replace Mode" in text
    assert "Default mode is copy-only." in text
    assert "Replace mode creates backups first." in text
    assert "Only accepted fixed clips replace originals." in text
    assert "Rollback uses replace_log.json." in text
    assert "replace-enabled" in text
    assert "replace-confirmed" in text
    assert "/api/operator/auto-qc-replace-once" in text
    assert "/api/operator/rollback-replace-log" in text
    assert "Safe Replace requires both checkboxes." in text

    control = client.get("/control-center")
    assert control.status_code == 200
    assert "Safe Replace Status" in control.text
    assert "Default Auto QC remains copy-only." in control.text or "Rollback available" in control.text

    print("test_safe_replace_ui: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
