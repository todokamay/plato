import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules.decision_explainer import explain_decision


def main() -> int:
    accepted = explain_decision(
        {
            "filename": "accept.mp4",
            "original_adjusted_score": 50,
            "fixed_adjusted_score": 73,
            "delta_score": 23,
            "fixed_final_verdict": "SAFE TO TEST",
            "final_bucket": "fixed_safe_to_test",
            "auto_fix_attempted": True,
            "fix_accepted": True,
            "fix_acceptance_reason": "score improved",
            "duration_acceptance_reason": "duration accepted",
            "replace_status": "replaced",
        }
    )
    assert accepted["fix_attempted"] is True
    assert accepted["fix_accepted"] is True
    assert accepted["replace_performed"] is True
    assert accepted["score_lift"] == 23
    assert "score improved" in accepted["reasons"]

    rejected = explain_decision(
        {
            "filename": "reject.mp4",
            "adjusted_score": 20,
            "final_verdict": "REJECT",
            "bucket": "rejected",
            "auto_fix_attempted": True,
            "fix_accepted": False,
            "fix_rejection_reason": "new P0 regression",
        }
    )
    assert rejected["fix_attempted"] is True
    assert rejected["fix_accepted"] is False
    assert "Clip ended in a reject path." in rejected["warnings"]
    assert rejected["next_action"].startswith("Review the rejection reason")

    missing = explain_decision({"filename": "missing.mp4"})
    assert missing["reasons"] == ["No detailed reason fields were present in this result row."]

    root = project_path("data/temp") / f"decision_explainer_{uuid.uuid4().hex[:8]}"
    try:
        root.mkdir(parents=True, exist_ok=True)
        summary = root / "run_summary.json"
        summary.write_text(json.dumps({"clips": [{"filename": "accept.mp4", "fix_accepted": True, "final_bucket": "fixed_safe_to_test"}]}), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "tools/explain_clip_decision.py", str(summary), "--clip", "accept.mp4", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(completed.stdout)
        assert payload["ok"] is True
        assert payload["clip"] == "accept.mp4"
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("test_decision_explainer: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
