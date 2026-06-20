import json
import contextlib
import io
import os
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from tools import process_videoautopipeline_outputs as tool


def root():
    path = project_path("data/temp") / f"vap_process_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_job(base: Path, job_id: str = "job1") -> Path:
    job = base / job_id
    (job / "status").mkdir(parents=True)
    (job / "metadata").mkdir(parents=True)
    (job / "final").mkdir(parents=True)
    final = job / "final" / "clip.mp4"
    final.write_bytes(b"original")
    (job / "metadata" / f"{job_id}.metadata.json").write_text("{}", encoding="utf-8")
    (job / "status" / f"{job_id}.status.json").write_text(json.dumps({
        "job_id": job_id,
        "status": "succeeded_waiting_for_plato",
        "send_mode": "after_plato",
        "plato_required": True,
        "plato_input_path": str(final),
    }), encoding="utf-8")
    return final


def test_dry_run_writes_summary_and_preserves_source():
    base = root()
    delivery = root()
    try:
        final = write_job(base)
        before = final.read_bytes()
        old = os.environ.get("PLATO_VAP_DELIVERY_ROOT")
        os.environ["PLATO_VAP_DELIVERY_ROOT"] = str(delivery)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                assert tool.main([str(base), "--dry-run"]) == 0
        finally:
            if old is None:
                os.environ.pop("PLATO_VAP_DELIVERY_ROOT", None)
            else:
                os.environ["PLATO_VAP_DELIVERY_ROOT"] = old
        assert final.read_bytes() == before
        summary = json.loads((delivery / "delivery_summary.json").read_text(encoding="utf-8"))
        assert summary["count"] == 1
        assert (delivery / "delivery_summary.csv").exists()
        assert (delivery / "jobs" / "job1.json").exists()
    finally:
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(delivery, ignore_errors=True)


def run_with_payload(payload: dict, *, send_telegram: bool = False, send_result: dict | None = None):
    base = root()
    delivery = root()
    sent = []
    old_root = os.environ.get("PLATO_VAP_DELIVERY_ROOT")
    old_qc = tool.run_auto_qc_fix
    old_send = tool.send_video
    try:
        final = write_job(base)
        os.environ["PLATO_VAP_DELIVERY_ROOT"] = str(delivery)
        tool.run_auto_qc_fix = lambda *args, **kwargs: payload
        tool.send_video = lambda path, caption: sent.append(path) or (send_result or {"ok": True, "skipped": False, "reason": ""})
        args = [str(base), "--auto-fix", "--copy-results"]
        if send_telegram:
            args.append("--send-telegram")
        with contextlib.redirect_stdout(io.StringIO()):
            assert tool.main(args) == 0
        summary = json.loads((delivery / "delivery_summary.json").read_text(encoding="utf-8"))
        return summary["jobs"][0], sent, final
    finally:
        tool.run_auto_qc_fix = old_qc
        tool.send_video = old_send
        if old_root is None:
            os.environ.pop("PLATO_VAP_DELIVERY_ROOT", None)
        else:
            os.environ["PLATO_VAP_DELIVERY_ROOT"] = old_root
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(delivery, ignore_errors=True)


def test_accepted_fixed_output_selected_for_telegram():
    fixed = root() / "fixed.mp4"
    try:
        fixed.write_bytes(b"fixed")
        row, sent, _final = run_with_payload({
            "clips": [{
                "filename": "clip.mp4",
                "final_bucket": "fixed_safe_to_test",
                "fix_accepted": True,
                "fixed_path": str(fixed),
                "auto_fix_attempted": True,
                "original_adjusted_score": 40,
                "original_final_verdict": "REJECT",
                "fixed_adjusted_score": 80,
                "fixed_final_verdict": "SAFE TO TEST",
            }]
        }, send_telegram=True)
        assert row["approved_output_path"] == str(fixed)
        assert sent == [str(fixed)]
        assert row["telegram_status"] == "sent"
    finally:
        shutil.rmtree(fixed.parent, ignore_errors=True)


def test_original_can_send_only_if_publishable():
    row, sent, final = run_with_payload({
        "clips": [{
            "filename": "clip.mp4",
            "final_bucket": "publish_ready",
            "fix_accepted": False,
            "auto_fix_allowed": False,
            "original_adjusted_score": 90,
            "original_final_verdict": "PUBLISH",
        }]
    }, send_telegram=True)
    assert row["approved_output_path"] == str(final.resolve())
    assert sent == [str(final.resolve())]


def test_rejected_or_empty_approved_path_is_not_sent():
    row, sent, _final = run_with_payload({
        "clips": [{
            "filename": "clip.mp4",
            "final_bucket": "rejected",
            "fix_accepted": False,
            "auto_fix_allowed": False,
            "failure_reason": "not publishable",
        }]
    }, send_telegram=True)
    assert row["approved_output_path"] == ""
    assert sent == []

    row, sent, _final = run_with_payload({
        "clips": [{
            "filename": "clip.mp4",
            "final_bucket": "fixed_safe_to_test",
            "fix_accepted": True,
            "fixed_path": "",
            "auto_fix_attempted": True,
        }]
    }, send_telegram=True)
    assert row["approved_output_path"] == ""
    assert sent == []


def test_missing_telegram_env_skips_cleanly():
    fixed = root() / "fixed.mp4"
    try:
        fixed.write_bytes(b"fixed")
        row, sent, _final = run_with_payload({
            "clips": [{
                "filename": "clip.mp4",
                "final_bucket": "fixed_safe_to_test",
                "fix_accepted": True,
                "fixed_path": str(fixed),
                "auto_fix_attempted": True,
            }]
        }, send_telegram=True, send_result={"ok": False, "skipped": True, "reason": "missing PLATO_TELEGRAM_BOT_TOKEN or PLATO_TELEGRAM_CHAT_ID"})
        assert sent == [str(fixed)]
        assert row["telegram_status"] == "skipped_missing_env"
        assert row["sent"] is False
    finally:
        shutil.rmtree(fixed.parent, ignore_errors=True)


def test_delivery_qc_targets_selected_final_when_folder_has_multiple_mp4s():
    base = root()
    delivery = root()
    old_root = os.environ.get("PLATO_VAP_DELIVERY_ROOT")
    old_qc = tool.run_auto_qc_fix
    try:
        final = write_job(base)
        decoy = final.parent / "aaa_decoy.mp4"
        decoy.write_bytes(b"decoy")
        calls = []
        os.environ["PLATO_VAP_DELIVERY_ROOT"] = str(delivery)

        def fake_qc(*args, **kwargs):
            calls.append((args, kwargs))
            assert Path(kwargs["target_file"]).resolve() == final.resolve()
            return {"clips": [{
                "filename": final.name,
                "original_path": str(final.resolve()),
                "final_bucket": "publish_ready",
                "fix_accepted": False,
                "auto_fix_allowed": False,
                "original_adjusted_score": 90,
                "original_final_verdict": "PUBLISH",
            }]}

        tool.run_auto_qc_fix = fake_qc
        with contextlib.redirect_stdout(io.StringIO()):
            assert tool.main([str(base), "--auto-fix", "--copy-results"]) == 0
        summary = json.loads((delivery / "delivery_summary.json").read_text(encoding="utf-8"))
        assert calls
        assert summary["jobs"][0]["approved_output_path"] == str(final.resolve())
        assert summary["jobs"][0]["plato_status"] == "approved"
    finally:
        tool.run_auto_qc_fix = old_qc
        if old_root is None:
            os.environ.pop("PLATO_VAP_DELIVERY_ROOT", None)
        else:
            os.environ["PLATO_VAP_DELIVERY_ROOT"] = old_root
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(delivery, ignore_errors=True)


def main():
    test_dry_run_writes_summary_and_preserves_source()
    test_accepted_fixed_output_selected_for_telegram()
    test_original_can_send_only_if_publishable()
    test_rejected_or_empty_approved_path_is_not_sent()
    test_missing_telegram_env_skips_cleanly()
    test_delivery_qc_targets_selected_final_when_folder_has_multiple_mp4s()
    print("test_process_videoautopipeline_outputs: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
