import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app


def main() -> int:
    client = TestClient(app)

    control = client.get("/control-center")
    assert control.status_code == 200
    text = control.text
    assert "Production Diagnostics" in text
    assert "Latest Auto QC Run" in text
    assert "Latest Batch QC Run" in text
    assert "py tools\\export_production_diagnostics.py" in text
    assert "/api/production-diagnostics" in text

    operator = client.get("/operator")
    assert operator.status_code == 200
    text = operator.text
    assert "Export Production Diagnostics" in text
    assert "No video files or SQLite databases are included." in text
    assert "/api/operator/export-production-diagnostics" in text

    print("test_production_diagnostics_ui: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
