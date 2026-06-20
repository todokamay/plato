import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app
from modules.operator_actions import FULL_FLOW_ACTION, control_room_status


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def main() -> int:
    client = TestClient(app)
    response = client.get("/api/operator/control-room-status")
    assert response.status_code == 200
    assert response.json()["ok"] is True

    html = client.get("/operator").text
    assert "Control Room" in html
    assert "Current Run" in html
    assert "Final Decision" in html
    assert "Final Output" in html
    assert "Blockers" in html
    assert "Fix Recommendation" in html
    assert "Blocker Route" in html
    assert "Fix Result" in html
    assert "Job History" in html
    assert "Retry Full Pipeline" in html
    assert "Retry Plato Only" in html
    assert "Retry Delivery Only" in html
    assert "No approved output yet" in html

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        missing = root / "missing_jobs.json"
        fresh = control_room_status(missing, root / "missing_delivery.json")
        assert fresh["ok"] is True
        assert fresh["status_bar"]["current_job"] == "none"
        assert fresh["final_output"]["message"] == "No approved output yet"

        summary = {
            "overall_status": "failed",
            "failed_step": "davinci",
            "steps": {
                "video_generation": {"status": "succeeded", "reason": ""},
                "davinci": {"status": "failed", "error": "DaVinci unavailable"},
            },
        }
        job_file = root / "jobs.json"
        write_json(
            job_file,
            {
                "version": 1,
                "jobs": [
                    {
                        "job_id": "job1",
                        "job_type": FULL_FLOW_ACTION,
                        "status": "failed",
                        "created_at": "2026-06-19T00:00:00+00:00",
                        "started_at": "2026-06-19T00:00:01+00:00",
                        "finished_at": "2026-06-19T00:00:03+00:00",
                        "args": ["py", "tools/run_videoautopipeline_full_flow.py", "--input-folder", r"C:\Videos"],
                        "stdout_tail": "FULL_PIPELINE_SUMMARY " + json.dumps(summary),
                        "stderr_tail": "",
                        "exit_code": 1,
                        "result_summary": {"last_line": "failed"},
                    }
                ],
            },
        )
        delivery_path = root / "delivery_summary.json"
        write_json(
            delivery_path,
            {
                "dry_run": True,
                "jobs": [
                    {
                        "job_id": "job1",
                        "approved_output_path": "",
                        "source_final_path": r"C:\out\clip.mp4",
                        "plato_score": 73.9,
                        "plato_verdict": "SAFE TO TEST",
                        "plato_bucket": "Reject",
                        "delivery_status": "not_sent",
                        "telegram_status": "skipped",
                        "reason": "waiting for approval",
                        "blocker_route": "plato_fix",
                        "blocker_fix_attempted": True,
                        "blocker_fix_accepted": False,
                        "blocker_next_action": "manual review required",
                    }
                ],
            },
        )
        write_json(
            root / "qc_runs" / "job1" / "run_summary.json",
            {
                "clips": [
                    {
                        "filename": "clip.mp4",
                        "original_path": r"C:\out\clip.mp4",
                        "P0_before": 1,
                        "P1_before": 1,
                        "top_original_issue": "subtitle overlap",
                    }
                ]
            },
        )
        status = control_room_status(job_file, delivery_path)
        assert status["current_run"]["failed_step"] == "davinci"
        assert "DaVinci unavailable" in status["current_run"]["reason"]
        assert status["current_run"]["input_path"] == r"C:\Videos"
        assert status["final_output"]["message"] == "No approved output yet"
        assert status["final_output"]["reason"] == "waiting for approval"
        assert status["final_output"]["explanation"]["blockers"]["p0"] == 1
        assert status["final_output"]["explanation"]["blockers"]["p1"] == 1
        assert "subtitle overlap" in status["final_output"]["explanation"]["blockers"]["items"]
        assert status["final_output"]["blocker_route"] == "plato_fix"
        assert status["final_output"]["blocker_fix_attempted"] is True
        assert status["final_output"]["blocker_next_action"] == "manual review required"
        assert status["job_history"][0]["return_code"] == 1

    print("test_operator_control_room: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
