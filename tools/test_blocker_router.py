import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.blocker_router import classify_blockers
from tools.route_delivery_blockers import build_routes


def main() -> int:
    assert classify_blockers({"top_original_issue": "Black frames create a strong retention risk."})["route"] == "plato_fix"
    assert classify_blockers({"reason": "unsafe banner zone near subtitles"})["route"] == "vap_rerender"
    assert classify_blockers({"reason": "weak content and poor hook"})["route"] in {"manual_review", "reject"}

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        summary = root / "delivery_summary.json"
        summary.write_text(json.dumps({
            "jobs": [{
                "job_id": "job1",
                "source_final_path": str(root / "clip.mp4"),
                "approved_output_path": "",
                "delivery_status": "not_sent",
                "plato_verdict": "SAFE TO TEST",
                "reason": "original has critical/P0/P1 delivery blockers",
            }]
        }), encoding="utf-8")
        qc = root / "qc_runs" / "job1" / "run_summary.json"
        qc.parent.mkdir(parents=True)
        qc.write_text(json.dumps({"clips": [{
            "filename": "clip.mp4",
            "original_path": str(root / "clip.mp4"),
            "P0_before": 1,
            "top_original_issue": "Black frames create a strong retention risk.",
        }]}), encoding="utf-8")
        result = build_routes(summary)
        assert result["routes"][0]["route"] == "plato_fix"
        completed = subprocess.run(
            [sys.executable, "tools/route_delivery_blockers.py", str(summary), "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert "plato_fix" in completed.stdout

    print("test_blocker_router: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
