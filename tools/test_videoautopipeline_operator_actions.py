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

        batch_args, _ = _command_for_action(
            "run_videoautopipeline_batch",
            input_folder=str(input_folder),
            output_root=str(output_root),
            vap_root=str(vap_root),
            limit=3,
        )
        assert batch_args[-2:] == ["--limit", "3"]

        process_args, _ = _command_for_action("process_videoautopipeline_outputs", output_root=str(output_root))
        assert "tools/process_videoautopipeline_outputs.py" in process_args
        assert "--dry-run" in process_args
        assert "--auto-fix" in process_args
        assert "--copy-results" in process_args
        assert "--send-telegram" not in process_args

        env = _vap_env(vap_root=str(vap_root), output_root=str(output_root))
        assert env["SEND_MODE"] == "after_plato"
        assert env["VAP_SEND_MODE"] == "after_plato"
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
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("test_videoautopipeline_operator_actions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
