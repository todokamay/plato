import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app


def main() -> int:
    client = TestClient(app)
    for route in ["/api/status", "/api/health", "/api/queue", "/api/history"]:
        response = client.get(route)
        assert response.status_code == 200, route
        assert response.headers["content-type"].startswith("application/json"), route
        assert isinstance(response.json(), dict), route
    print("test_api_fresh_state: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
