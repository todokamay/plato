import shutil
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from tools.process_videoautopipeline_outputs import _approved_output, is_delivery_publishable


def mp4(root: Path, name: str) -> str:
    path = root / name
    path.write_bytes(b"video")
    return str(path.resolve())


def main() -> int:
    root = project_path("data/temp") / f"delivery_gate_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        original = mp4(root, "original.mp4")
        fixed = mp4(root, "fixed.mp4")

        assert is_delivery_publishable("SAFE TO TEST", 73.9, [])
        approved, reason = _approved_output({
            "original_final_verdict": "SAFE TO TEST",
            "original_adjusted_score": 73.9,
            "final_bucket": "rejected",
            "failure_reason": "safe fixes exist but bucket is not auto-fix eligible",
        }, original)
        assert approved == original
        assert reason == "original is SAFE TO TEST and no critical issues"

        approved, reason = _approved_output({
            "original_final_verdict": "SAFE TO TEST",
            "original_adjusted_score": 73.9,
            "P0_before": 1,
        }, original)
        assert approved == ""
        assert "critical/P0/P1" in reason

        approved, reason = _approved_output({"original_final_verdict": "REWORK", "original_adjusted_score": 67.0}, original)
        assert approved == ""
        assert "REWORK" in reason

        approved, reason = _approved_output({
            "fix_accepted": True,
            "fixed_path": fixed,
            "fixed_final_verdict": "SAFE TO TEST",
            "original_final_verdict": "SAFE TO TEST",
            "final_output_path": original,
        }, original)
        assert approved == fixed
        assert reason == "accepted fixed output"

        approved, _reason = _approved_output({
            "fix_accepted": True,
            "fixed_path": "",
            "fixed_final_verdict": "SAFE TO TEST",
        }, original)
        assert approved == ""

        approved, _reason = _approved_output({
            "original_final_verdict": "SAFE TO TEST",
            "original_adjusted_score": 73.9,
            "auto_fix_allowed": True,
            "final_bucket": "debug_review",
            "failure_reason": "safe fixes exist but bucket is not auto-fix eligible",
        }, original)
        assert approved == original
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("test_delivery_gate: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
