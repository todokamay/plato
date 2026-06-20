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
    assert "Run Settings" in text
    assert "Input video path" in text
    assert "Input folder path" in text
    assert "Video Generation" in text
    assert "Generate From LongVideos" in text
    assert "Generate One Video" in text
    assert "Batch Generate Folder" in text
    assert "VideoAutoPipeline Tools" in text
    assert "Open VideoAutoPipeline GUI" in text
    assert "Dry-run Batch" in text
    assert "Resume Failed Job" in text
    assert "Show Latest Pipeline Status" in text
    assert "Show Worker Status" not in text
    assert "Show Latest Output Folder" in text
    assert "Plato Quality Gate" in text
    assert "Check &amp; Fix With Plato" in text
    assert "Process Waiting For Plato" in text
    assert "Send Approved To Telegram" in text
    assert "DaVinci enhancement" in text
    assert "Plato improvement" in text
    assert "DaVinci mode" in text
    assert "SEND_MODE" in text
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
