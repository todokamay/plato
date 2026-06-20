import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.delivery_decision_explainer import explain_delivery_summary


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def delivery_summary(root: Path, row: dict) -> Path:
    path = root / "delivery_summary.json"
    write_json(path, {"jobs": [row]})
    return path


def qc_summary(root: Path, job_id: str, clip: dict) -> Path:
    path = root / "qc_runs" / job_id / "run_summary.json"
    write_json(path, {"clips": [clip]})
    return path


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        rejected_root = root / "rejected"
        publishable_root = root / "publishable"
        missing_root = root / "missing"
        source = str(rejected_root / "final.mp4")

        rejected = delivery_summary(rejected_root, {
            "job_id": "safe_blocked",
            "source_final_path": source,
            "approved_output_path": "",
            "delivery_status": "not_sent",
            "plato_score": 73.9,
            "plato_verdict": "SAFE TO TEST",
            "plato_bucket": "Reject",
            "reason": "original has critical/P0/P1 delivery blockers",
        })
        qc_summary(rejected_root, "safe_blocked", {
            "filename": "final.mp4",
            "original_path": source,
            "original_final_verdict": "SAFE TO TEST",
            "original_bucket": "Reject",
            "P0_before": 1,
            "P1_before": 1,
            "top_original_issue": "low bitrate",
            "failure_reason": "safe fixes exist but bucket is not auto-fix eligible",
            "auto_fix_allowed": False,
            "auto_fix_attempted": False,
            "fix_accepted": False,
        })
        explanation = explain_delivery_summary(rejected)
        assert explanation["decision"]["status"] == "blocked"
        assert explanation["blockers"]["p0"] == 1
        assert explanation["blockers"]["p1"] == 1
        assert "low bitrate" in explanation["blockers"]["items"]
        assert "SAFE TO TEST, but blocked" in explanation["fix_recommendation"]["suggested_next_action"]

        publishable_source = str(publishable_root / "final.mp4")
        publishable = delivery_summary(publishable_root, {
            "job_id": "approved",
            "source_final_path": publishable_source,
            "approved_output_path": publishable_source,
            "delivery_status": "approved",
            "plato_score": 88,
            "plato_verdict": "PUBLISH",
            "plato_bucket": "Publish",
        })
        qc_summary(publishable_root, "approved", {"filename": "final.mp4", "original_path": publishable_source, "P0_before": 0, "P1_before": 0})
        explanation = explain_delivery_summary(publishable)
        assert explanation["decision"]["status"] == "approved"
        assert explanation["fix_recommendation"]["suggested_next_action"] == "Approved output is ready for delivery."

        missing = delivery_summary(missing_root, {})
        explanation = explain_delivery_summary(missing)
        assert explanation["decision"]["status"] in {"pending", "blocked"}
        assert "blockers" in explanation

        completed = subprocess.run(
            [sys.executable, "tools/explain_delivery_decision.py", str(rejected)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert "low bitrate" in completed.stdout

    print("test_explain_delivery_decision: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
