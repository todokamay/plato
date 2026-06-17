import contextlib
import io
import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app import app
from config import project_path
from modules import operator_actions
from modules.job_runner import _command_for_action, _vap_env
import routes.api as api
from tools import run_videoautopipeline_full_flow


def _summary_from(text: str) -> dict:
    line = next(item for item in text.splitlines() if item.startswith(run_videoautopipeline_full_flow.SUMMARY_PREFIX))
    return json.loads(line.replace(run_videoautopipeline_full_flow.SUMMARY_PREFIX, ""))


def main() -> int:
    root = project_path("data/temp") / f"one_click_{uuid.uuid4().hex[:8]}"
    vap_root = root / "VideoAutoPipeline"
    output_root = root / "output"
    input_folder = root / "input"
    input_video = input_folder / "clip.mp4"
    try:
        vap_root.mkdir(parents=True)
        output_root.mkdir()
        input_folder.mkdir()
        (vap_root / "app.py").write_text("print('fake')\n", encoding="utf-8")
        input_video.write_bytes(b"fake")

        client = TestClient(app)
        html = client.get("/operator").text
        advanced_at = html.index("<summary>Advanced</summary>")
        assert "Run Full Pipeline" in html
        assert advanced_at < html.index('id="simple-generate-videos"')
        assert advanced_at < html.index('id="simple-check-fix"')
        assert advanced_at < html.index('id="simple-send-telegram"')
        assert 'id="simple-vap-dry-run" type="checkbox" checked' in html
        assert 'id="simple-vap-send-telegram" type="checkbox"' in html
        assert 'id="simple-vap-send-telegram" type="checkbox" checked' not in html

        args, _display = _command_for_action(
            "run_full_videoautopipeline_to_plato_flow",
            input_file=str(input_video),
            output_root=str(output_root),
            vap_root=str(vap_root),
        )
        assert args[1] == "tools/run_videoautopipeline_full_flow.py"
        assert "--dry-run" in args
        assert "--send-telegram" not in args

        env = _vap_env(vap_root=str(vap_root), output_root=str(output_root))
        assert env["SEND_MODE"] == "after_plato"
        assert env["VAP_SEND_MODE"] == "after_plato"

        rejected = operator_actions.start_full_videoautopipeline_flow_job(
            vap_root,
            output_root,
            input_folder=project_path("."),
        )
        assert rejected["ok"] is False
        assert "safe input folder" in rejected["error"]

        original = api.start_full_videoautopipeline_flow_job
        api.start_full_videoautopipeline_flow_job = lambda *args, **kwargs: {
            "ok": True,
            "job": {"job_id": "one-click", "job_type": "run_full_videoautopipeline_to_plato_flow", "status": "queued"},
        }
        try:
            payload = client.post("/api/operator/full-pipeline-run", json={"input_video": str(input_video)}).json()
        finally:
            api.start_full_videoautopipeline_flow_job = original
        assert payload["ok"] is True
        assert payload["job"]["job_type"] == "run_full_videoautopipeline_to_plato_flow"

        captured = []
        original_run_command = run_videoautopipeline_full_flow.run_command

        def fake_run_command(cmd, cwd, env, step_name, steps):
            captured.append(cmd)
            steps[step_name]["status"] = "succeeded"
            return 0

        run_videoautopipeline_full_flow.run_command = fake_run_command
        try:
            code = run_videoautopipeline_full_flow.main([
                "--vap-root",
                str(vap_root),
                "--output-root",
                str(output_root),
                "--input-folder",
                str(input_folder),
                "--limit",
                "3",
            ])
        finally:
            run_videoautopipeline_full_flow.run_command = original_run_command
        assert code == 0
        assert captured[0][-1] == "--resume"

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_videoautopipeline_full_flow.main([
                "--vap-root",
                str(root / "missing_vap"),
                "--output-root",
                str(output_root),
                "--input-folder",
                str(input_folder),
            ])
        summary = _summary_from(out.getvalue())
        assert code == 2
        assert summary["overall_status"] == "failed"
        assert summary["failed_step"] == "video_generation"
        assert summary["steps"]["video_generation"]["status"] == "failed"
        assert summary["steps"]["video_generation"]["reason"]
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("test_one_click_full_run: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
