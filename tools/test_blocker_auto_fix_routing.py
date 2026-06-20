import contextlib
import copy
import io
import json
import os
import shutil
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from tools import process_videoautopipeline_outputs as tool


def temp_root(prefix: str) -> Path:
    path = project_path("data/temp") / f"{prefix}_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_job(base: Path) -> Path:
    job = base / "job1"
    final = job / "final" / "clip.mp4"
    (job / "metadata").mkdir(parents=True)
    (job / "status").mkdir(parents=True)
    final.parent.mkdir(parents=True)
    final.write_bytes(b"original")
    (job / "metadata" / "job1.metadata.json").write_text("{}", encoding="utf-8")
    (job / "status" / "job1.status.json").write_text(json.dumps({
        "job_id": "job1",
        "status": "succeeded_waiting_for_plato",
        "send_mode": "after_plato",
        "plato_required": True,
        "plato_input_path": str(final),
    }), encoding="utf-8")
    return final


def run_with_payloads(payloads: list[dict]):
    base = temp_root("blocker_route_base")
    delivery = temp_root("blocker_route_delivery")
    request_root = temp_root("blocker_route_requests")
    fixed = temp_root("blocker_route_fixed") / "fixed.mp4"
    fixed.write_bytes(b"fixed")
    sent = []
    calls = []
    old_root = os.environ.get("PLATO_VAP_DELIVERY_ROOT")
    old_request_root = os.environ.get("PLATO_RERENDER_REQUEST_ROOT")
    old_qc = tool.run_auto_qc_fix
    old_send = tool.send_video
    try:
        final = write_job(base)
        os.environ["PLATO_VAP_DELIVERY_ROOT"] = str(delivery)
        os.environ["PLATO_RERENDER_REQUEST_ROOT"] = str(request_root)

        def fake_qc(*args, **kwargs):
            calls.append(kwargs)
            payload = copy.deepcopy(payloads[min(len(calls) - 1, len(payloads) - 1)])
            for clip in payload.get("clips", []):
                for key, value in list(clip.items()):
                    if isinstance(value, str):
                        clip[key] = value.replace("__FINAL__", str(final.resolve())).replace("__FIXED__", str(fixed.resolve()))
            return payload

        tool.run_auto_qc_fix = fake_qc
        tool.send_video = lambda path, caption: sent.append(path) or {"ok": True}
        with contextlib.redirect_stdout(io.StringIO()):
            assert tool.main([str(base), "--auto-fix", "--copy-results"]) == 0
        summary = json.loads((delivery / "delivery_summary.json").read_text(encoding="utf-8"))
        return summary["jobs"][0], calls, sent
    finally:
        tool.run_auto_qc_fix = old_qc
        tool.send_video = old_send
        if old_root is None:
            os.environ.pop("PLATO_VAP_DELIVERY_ROOT", None)
        else:
            os.environ["PLATO_VAP_DELIVERY_ROOT"] = old_root
        if old_request_root is None:
            os.environ.pop("PLATO_RERENDER_REQUEST_ROOT", None)
        else:
            os.environ["PLATO_RERENDER_REQUEST_ROOT"] = old_request_root
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(delivery, ignore_errors=True)
        shutil.rmtree(request_root, ignore_errors=True)
        shutil.rmtree(fixed.parent, ignore_errors=True)


def blocked_black_frame_payload() -> dict:
    return {"clips": [{
        "filename": "clip.mp4",
        "original_path": "__FINAL__",
        "final_bucket": "rejected",
        "original_adjusted_score": 69.2,
        "original_final_verdict": "SAFE TO TEST",
        "original_bucket": "Reject",
        "P0_before": 1,
        "top_original_issue": "Black frames create a strong retention risk.",
        "failure_reason": "safe fixes exist but bucket is not auto-fix eligible",
        "auto_fix_attempted": False,
        "auto_fix_allowed": False,
        "fix_accepted": False,
    }]}


def accepted_fixed_payload() -> dict:
    return {"clips": [{
        "filename": "clip.mp4",
        "original_path": "__FINAL__",
        "final_bucket": "fixed_safe_to_test",
        "original_adjusted_score": 69.2,
        "original_final_verdict": "SAFE TO TEST",
        "original_bucket": "Reject",
        "P0_before": 1,
        "auto_fix_attempted": True,
        "auto_fix_allowed": True,
        "fix_accepted": True,
        "fixed_path": "__FIXED__",
        "fixed_adjusted_score": 82,
        "fixed_final_verdict": "SAFE TO TEST",
        "P0_after": 0,
        "P1_after": 0,
    }]}


def failed_fixed_payload() -> dict:
    payload = accepted_fixed_payload()
    clip = payload["clips"][0]
    clip["fix_accepted"] = False
    clip["fixed_path"] = ""
    clip["final_bucket"] = "failed_fix"
    clip["failure_reason"] = "fixed version rejected"
    return payload


def test_fixed_output_becomes_approved_if_reanalysis_passes():
    row, calls, sent = run_with_payloads([blocked_black_frame_payload(), accepted_fixed_payload()])
    assert len(calls) == 2
    assert calls[1]["force_auto_fix"] is True
    assert row["blocker_route"] == "plato_fix"
    assert row["blocker_fix_attempted"] is True
    assert row["blocker_fix_accepted"] is True
    assert row["plato_status"] == "approved"
    assert row["approved_output_path"].endswith("fixed.mp4")
    assert sent == []


def test_rejected_remains_rejected_if_fix_fails():
    row, calls, sent = run_with_payloads([blocked_black_frame_payload(), failed_fixed_payload()])
    assert len(calls) == 2
    assert row["blocker_route"] == "plato_fix"
    assert row["blocker_fix_attempted"] is True
    assert row["blocker_fix_accepted"] is False
    assert row["approved_output_path"] == ""
    assert row["plato_status"] == "rejected"
    assert sent == []


def test_vap_rerender_route_does_not_attempt_plato_fix():
    payload = blocked_black_frame_payload()
    payload["clips"][0]["top_original_issue"] = "subtitle overlap in unsafe banner zone"
    row, calls, sent = run_with_payloads([payload])
    assert len(calls) == 1
    assert row["blocker_route"] == "vap_rerender"
    assert row["delivery_status"] == "needs_rerender"
    assert row["blocker_fix_attempted"] is False
    assert sent == []


def main() -> int:
    test_fixed_output_becomes_approved_if_reanalysis_passes()
    test_rejected_remains_rejected_if_fix_fails()
    test_vap_rerender_route_does_not_attempt_plato_fix()
    print("test_blocker_auto_fix_routing: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
