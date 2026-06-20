import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules import operator_actions
from modules.job_runner import _command_for_action, _vap_env


def main() -> int:
    root = project_path("data/temp") / f"vap_operator_{uuid.uuid4().hex[:8]}"
    vap_root = root / "VideoAutoPipeline"
    output_root = root / "output"
    input_folder = root / "input"
    input_video = input_folder / "clip.mp4"
    try:
        vap_root.mkdir(parents=True)
        output_root.mkdir(parents=True)
        input_folder.mkdir(parents=True)
        (vap_root / "app.py").write_text("print('fake')\n", encoding="utf-8")
        input_video.write_bytes(b"fake mp4")

        worker_args, _ = _command_for_action(
            "run_videoautopipeline_worker",
            input_file=str(input_video),
            output_root=str(output_root),
            vap_root=str(vap_root),
        )
        assert worker_args == [sys.executable, str(vap_root / "app.py"), "--worker", str(input_video)]

        gui_args, _ = _command_for_action("open_videoautopipeline_gui", vap_root=str(vap_root))
        assert gui_args == [sys.executable, str(vap_root / "app.py")]

        generate_one_args, _ = _command_for_action(
            "vap_generate_one_video",
            input_file=str(input_video),
            output_root=str(output_root),
            vap_root=str(vap_root),
        )
        assert generate_one_args == [sys.executable, str(vap_root / "app.py"), "--worker", str(input_video)]

        batch_args, _ = _command_for_action(
            "run_videoautopipeline_batch",
            input_folder=str(input_folder),
            output_root=str(output_root),
            vap_root=str(vap_root),
            limit=3,
        )
        assert batch_args[-2:] == ["--limit", "3"]
        assert "--output-root" in batch_args
        assert str(output_root) in batch_args

        vap_batch_args, _ = _command_for_action(
            "vap_batch_generate_folder",
            input_folder=str(input_folder),
            output_root=str(output_root),
            vap_root=str(vap_root),
            limit=3,
        )
        assert vap_batch_args == [sys.executable, str(vap_root / "app.py"), "--batch", str(input_folder), "--output-root", str(output_root), "--limit", "3"]

        dry_batch_args, _ = _command_for_action(
            "vap_batch_dry_run",
            input_folder=str(input_folder),
            output_root=str(output_root),
            vap_root=str(vap_root),
        )
        assert dry_batch_args[-2:] == ["--dry-run", "--json"]
        assert "--output-root" in dry_batch_args

        resume_args, _ = _command_for_action(
            "vap_resume_failed",
            input_file=str(input_video),
            output_root=str(output_root),
            vap_root=str(vap_root),
        )
        assert resume_args[-1] == "--resume"

        status_args, _ = _command_for_action(
            "vap_status",
            input_file=str(input_video),
            output_root=str(output_root),
            vap_root=str(vap_root),
        )
        assert status_args[-1] == "--status-only"

        request_json = root / "rerender_requests" / "requested" / "request.json"
        request_json.parent.mkdir(parents=True)
        request_json.write_text("{}", encoding="utf-8")
        rerender_args, _ = _command_for_action(
            "vap_dry_run_rerender_request",
            input_file=str(request_json),
            output_root=str(output_root),
            vap_root=str(vap_root),
        )
        assert rerender_args == [sys.executable, str(vap_root / "tools" / "process_rerender_request.py"), str(request_json), "--dry-run", "--json", "--output-root", str(output_root)]

        import_args, _ = _command_for_action("import_rerender_result", input_file=str(output_root / "job1" / "rerender" / "req" / "status" / "req.status.json"))
        assert import_args[:2] == [sys.executable, "tools/import_rerender_result.py"]

        completed_args, _ = _command_for_action("process_completed_rerenders", output_root=str(output_root))
        assert "--include-rerenders" in completed_args
        assert "--send-telegram" not in completed_args

        latest = operator_actions.start_vap_status_job(vap_root, "", output_root)
        assert latest["ok"] is True
        assert "latest_output_folder" in latest

        process_args, _ = _command_for_action("process_videoautopipeline_outputs", output_root=str(output_root))
        assert "tools/process_videoautopipeline_outputs.py" in process_args
        assert "--dry-run" in process_args
        assert "--auto-fix" in process_args
        assert "--copy-results" in process_args
        assert "--send-telegram" not in process_args

        env = _vap_env(vap_root=str(vap_root), output_root=str(output_root))
        assert env["SEND_MODE"] == "after_plato"
        assert env["VAP_SEND_MODE"] == "after_plato"
        assert env["VAP_DAVINCI_MODE"] == "required"
        assert env["VAP_REQUIRE_DAVINCI"] == "true"
        assert env["VAP_OUTPUT_DIR"] == str(output_root)

        rejected = operator_actions.start_videoautopipeline_worker_job(project_path("."), input_video, output_root)
        assert rejected["ok"] is False
        assert "Project root" in rejected["error"]

        captured = {}
        original_start_job = operator_actions.start_job

        def fake_start_job(action, **kwargs):
            captured.update({"action": action, **kwargs})
            return {"job_id": "job1", "job_type": action, "status": "queued"}

        operator_actions.start_job = fake_start_job
        try:
            result = operator_actions.start_process_videoautopipeline_outputs_job(output_root)
        finally:
            operator_actions.start_job = original_start_job
        assert result["ok"] is True
        assert captured["action"] == "process_videoautopipeline_outputs"
        assert captured["dry_run"] is True
        assert captured["send_telegram"] is False

        captured.clear()
        operator_actions.start_job = fake_start_job
        try:
            result = operator_actions.start_send_approved_to_telegram_job(output_root)
        finally:
            operator_actions.start_job = original_start_job
        assert result["ok"] is True
        assert captured["send_telegram"] is True
        assert captured["dry_run"] is False
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("test_videoautopipeline_operator_actions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
