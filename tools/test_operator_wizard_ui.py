import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app


def main() -> int:
    client = TestClient(app)
    response = client.get("/operator")
    assert response.status_code == 200
    text = response.text
    assert "Operator Run Wizard" in text
    assert "Generate Videos" in text
    assert "Check &amp; Fix With Plato" in text
    assert "Send Approved To Telegram" in text
    assert "<summary>Advanced</summary>" in text
    assert "Detect VideoAutoPipeline Outputs" in text
    assert "Run Dry Run" in text
    assert "Run Auto QC Once" in text
    assert "Start Watch Mode" in text
    assert "Stop Watch Mode" in text
    assert "data\\temp\\manual_videoautopipeline_outputs" in text
    assert "/api/operator/status" in text
    print("test_operator_wizard_ui: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
