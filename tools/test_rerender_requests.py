import contextlib
import io
import json
import os
import shutil
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app
from config import project_path
from modules.rerender_requests import (
    build_rerender_request,
    get_rerender_stats,
    list_rerender_requests,
    mark_request_status,
    write_rerender_request,
)
from tools.import_rerender_result import import_result
from tools import process_videoautopipeline_outputs as tool
from modules import operator_actions


def temp_root(prefix: str) -> Path:
    path = project_path("data/temp") / f"{prefix}_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_job(base: Path) -> Path:
    job = base / "job1"
    final = job / "final" / "clip.mp4"
    final.parent.mkdir(parents=True)
    (job / "metadata").mkdir(parents=True)
    (job / "status").mkdir(parents=True)
    final.write_bytes(b"video")
    (job / "metadata" / "job1.metadata.json").write_text("{}", encoding="utf-8")
    (job / "status" / "job1.status.json").write_text(json.dumps({
        "job_id": "job1",
        "status": "succeeded_waiting_for_plato",
        "send_mode": "after_plato",
        "plato_required": True,
        "plato_input_path": str(final),
        "source_video": r"C:\Users\User\Desktop\Work\LongVideos\source.mp4",
    }), encoding="utf-8")
    return final


def with_env(updates: dict):
    class Guard:
        def __enter__(self):
            self.old = {key: os.environ.get(key) for key in updates}
            os.environ.update({key: str(value) for key, value in updates.items()})
            return self

        def __exit__(self, exc_type, exc, tb):
            for key, value in self.old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    return Guard()


def test_request_module_and_dedupe() -> None:
    root = temp_root("rerender_requests")
    try:
        route = {"route": "vap_rerender", "blocker_type": "unsafe banner zone", "reason": "unsafe banner zone"}
        request = build_rerender_request({
            "job_id": "job1",
            "source_final_path": r"C:\out\clip.mp4",
            "plato_score": 72,
            "plato_verdict": "SAFE TO TEST",
            "plato_bucket": "Reject",
        }, route)
        assert request["requested_changes"] == ["move_banner_to_safe_zone", "rerender_ad_banner"]
        assert build_rerender_request({"job_id": "job1", "source_final_path": r"C:\out\clip.mp4"}, {"route": "plato_fix"}) == {}

        first = write_rerender_request(request, root)
        duplicate = {**request, "request_id": "rerender_duplicate_job1"}
        second = write_rerender_request(duplicate, root)
        assert first["created"] is True
        assert second["created"] is False
        assert second["path"] == first["path"]
        assert len(list_rerender_requests("requested", root)) == 1

        subtitle = build_rerender_request({
            "job_id": "job2",
            "source_final_path": r"C:\out\clip2.mp4",
        }, {"route": "vap_rerender", "blocker_type": "subtitle overlap", "reason": "subtitle overlap"})
        assert subtitle["requested_changes"] == ["rerender_subtitles", "adjust_subtitle_position"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_stats_api_ui_and_process_integration() -> None:
    base = temp_root("rerender_base")
    delivery = temp_root("rerender_delivery")
    request_root = temp_root("rerender_queue")
    old_qc = tool.run_auto_qc_fix
    try:
        final = write_job(base)
        with with_env({"PLATO_VAP_DELIVERY_ROOT": delivery, "PLATO_RERENDER_REQUEST_ROOT": request_root}):
            assert get_rerender_stats()["total"] == 0
            client = TestClient(app)
            api = client.get("/api/operator/rerender-requests")
            assert api.status_code == 200
            assert api.json()["ok"] is True
            html = client.get("/operator").text
            assert "Rerender Requests" in html
            assert "Dry-run Latest Rerender Request" in html
            assert "Import Rerender Result" in html
            assert "Process Completed Rerenders With Plato" in html

            def fake_qc(*args, **kwargs):
                return {"clips": [{
                    "filename": final.name,
                    "original_path": str(final.resolve()),
                    "final_bucket": "rejected",
                    "original_adjusted_score": 70,
                    "original_final_verdict": "SAFE TO TEST",
                    "original_bucket": "Reject",
                    "P0_before": 1,
                    "top_original_issue": "subtitle overlap in unsafe banner zone",
                    "failure_reason": "layout blocker",
                    "auto_fix_attempted": False,
                    "auto_fix_allowed": False,
                    "fix_accepted": False,
                }]}

            tool.run_auto_qc_fix = fake_qc
            with contextlib.redirect_stdout(io.StringIO()):
                assert tool.main([str(base), "--auto-fix", "--copy-results"]) == 0
            summary = json.loads((delivery / "delivery_summary.json").read_text(encoding="utf-8"))
            row = summary["jobs"][0]
            assert row["blocker_route"] == "vap_rerender"
            assert row["rerender_request_status"] == "requested"
            assert Path(row["rerender_request_path"]).exists()
            request = json.loads(Path(row["rerender_request_path"]).read_text(encoding="utf-8"))
            assert request["job_id"] == "job1"
            assert request["requested_changes"] == ["move_banner_to_safe_zone", "rerender_ad_banner"]
            assert get_rerender_stats()["counts"]["requested"] == 1
    finally:
        tool.run_auto_qc_fix = old_qc
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(delivery, ignore_errors=True)
        shutil.rmtree(request_root, ignore_errors=True)


def test_import_completed_and_failed_results() -> None:
    request_root = temp_root("rerender_import_queue")
    vap_output = temp_root("rerender_import_output")
    try:
        with with_env({"PLATO_RERENDER_REQUEST_ROOT": request_root}):
            source = vap_output / "source.mp4"
            source.write_bytes(b"source")
            request = build_rerender_request({
                "job_id": "job1",
                "source_final_path": str(source),
            }, {"route": "vap_rerender", "blocker_type": "subtitle overlap", "reason": "subtitle overlap"})
            write_rerender_request(request)

            rendered = vap_output / "job1" / "rerender" / request["request_id"] / "final" / "clip_rerendered.mp4"
            rendered.parent.mkdir(parents=True)
            rendered.write_bytes(b"rendered")
            status = vap_output / "status.json"
            status.write_text(json.dumps({
                "request_id": request["request_id"],
                "job_id": "job1",
                "status": "completed",
                "rerendered_output_path": str(rendered),
            }), encoding="utf-8")
            result = import_result(status)
            assert result["ok"] is True
            assert get_rerender_stats()["counts"]["completed"] == 1

            source2 = vap_output / "source2.mp4"
            source2.write_bytes(b"source2")
            failed_request = {**request, "request_id": "rerender_failed_job1", "source_final_path": str(source2), "blocker_type": "bad crop"}
            write_rerender_request(failed_request)
            failed_status = vap_output / "failed.status.json"
            failed_status.write_text(json.dumps({
                "request_id": failed_request["request_id"],
                "job_id": "job1",
                "status": "failed",
                "error": "unsupported_requested_change",
            }), encoding="utf-8")
            result = import_result(failed_status)
            assert result["ok"] is True
            assert get_rerender_stats()["counts"]["failed"] == 1
    finally:
        shutil.rmtree(request_root, ignore_errors=True)
        shutil.rmtree(vap_output, ignore_errors=True)


def test_process_completed_rerender_uses_rerendered_output_and_rejects_unsafe_paths() -> None:
    request_root = temp_root("rerender_process_queue")
    vap_output = temp_root("rerender_process_output")
    delivery = temp_root("rerender_process_delivery")
    old_qc = tool.run_auto_qc_fix
    try:
        with with_env({"PLATO_RERENDER_REQUEST_ROOT": request_root, "PLATO_VAP_DELIVERY_ROOT": delivery}):
            source = vap_output / "source.mp4"
            source.write_bytes(b"source")
            rendered = vap_output / "job1" / "rerender" / "rerender_job1" / "final" / "clip_rerendered.mp4"
            rendered.parent.mkdir(parents=True)
            rendered.write_bytes(b"rendered")
            request = build_rerender_request({
                "job_id": "job1",
                "source_final_path": str(source),
            }, {"route": "vap_rerender", "blocker_type": "subtitle overlap", "reason": "subtitle overlap"})
            request["request_id"] = "rerender_job1"
            write_rerender_request(request)
            mark_request_status(request["request_id"], "completed", updates={"rerendered_output_path": str(rendered)})

            calls = []

            def fake_qc(*args, **kwargs):
                calls.append(kwargs)
                assert Path(kwargs["target_file"]).resolve() == rendered.resolve()
                return {"clips": [{
                    "filename": rendered.name,
                    "original_path": str(rendered.resolve()),
                    "final_bucket": "publish_ready",
                    "original_adjusted_score": 90,
                    "original_final_verdict": "PUBLISH",
                    "original_bucket": "Publish",
                    "fix_accepted": False,
                }]}

            tool.run_auto_qc_fix = fake_qc
            with contextlib.redirect_stdout(io.StringIO()):
                assert tool.main([str(vap_output), "--include-rerenders", "--auto-fix", "--copy-results"]) == 0
            assert calls
            summary = json.loads((delivery / "delivery_summary.json").read_text(encoding="utf-8"))
            assert summary["jobs"][0]["approved_output_path"] == str(rendered.resolve())

            vap_root = temp_root("fake_vap_root")
            (vap_root / "app.py").write_text("print('fake')\n", encoding="utf-8")
            unsafe = operator_actions.start_vap_dry_run_rerender_request_job(vap_root, ROOT / "config.py", vap_output)
            assert unsafe["ok"] is False
            assert "rerender_requests" in unsafe["error"]
    finally:
        tool.run_auto_qc_fix = old_qc
        shutil.rmtree(request_root, ignore_errors=True)
        shutil.rmtree(vap_output, ignore_errors=True)
        shutil.rmtree(delivery, ignore_errors=True)
        if "vap_root" in locals():
            shutil.rmtree(vap_root, ignore_errors=True)


def main() -> int:
    test_request_module_and_dedupe()
    test_stats_api_ui_and_process_integration()
    test_import_completed_and_failed_results()
    test_process_completed_rerender_uses_rerendered_output_and_rejects_unsafe_paths()
    print("test_rerender_requests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
