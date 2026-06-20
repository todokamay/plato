import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app


def main() -> int:
    html = TestClient(app).get("/operator").text
    assert "Keep only final approved video after successful delivery" in html
    assert 'id="vap-keep-final-only" type="checkbox"' in html
    assert 'id="vap-keep-final-only" type="checkbox" checked' not in html
    assert 'id="vap-cleanup-dry-run" type="checkbox" checked' in html
    assert 'id="vap-confirm-cleanup" type="checkbox"' in html
    assert 'id="vap-confirm-cleanup" type="checkbox" checked' not in html
    assert "Cleanup danger zone" in html
    assert 'id="vap-allow-source-delete" type="checkbox"' in html
    assert html.index("<summary>Advanced</summary>") < html.index('id="vap-keep-final-only"')
    assert html.index("<summary>Advanced</summary>") < html.index('id="vap-confirm-cleanup"')
    assert html.index("<summary>Advanced</summary>") < html.index('id="vap-allow-source-delete"')
    print("test_keep_final_only_ui: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
