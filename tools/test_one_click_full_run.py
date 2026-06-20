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
        assert "Run Settings" in html
        assert "Video Generation" in html
        assert "VideoAutoPipeline Tools" in html
        assert "Plato Quality Gate" in html
        assert html.index('id="vap-root-input"') > advanced_at
        assert html.index('id="vap-input-video"') < advanced_at
        assert html.index('id="vap-limit-input"') < advanced_at
        assert 'id="vap-dry-run" type="checkbox" checked' in html
        assert 'id="vap-send-telegram" type="checkbox"' in html
        assert 'id="vap-send-telegram" type="checkbox" checked' not in html
        assert "Step 2: DaVinci enhancement" in html
        assert "Step 4: Plato improvement" in html

        args, _display = _command_for_action(
            "run_full_videoautopipeline_to_plato_flow",
            input_file=str(input_video),
            output_root=str(output_root),
            vap_root=str(vap_root),
        )
        assert args[1] == "tools/run_videoautopipeline_full_flow.py"
        assert "--dry-run" in args
        assert "--davinci-mode" in args
        assert "--send-telegram" not in args

        env = _vap_env(vap_root=str(vap_root), output_root=str(output_root))
        assert env["SEND_MODE"] == "after_plato"
        assert env["VAP_SEND_MODE"] == "after_plato"
        assert env["VAP_DAVINCI_MODE"] == "required"
        assert env["VAP_REQUIRE_DAVINCI"] == "true"

        dry_calls = []
        original_run_command = run_videoautopipeline_full_flow.run_command
        original_ollama_available = run_videoautopipeline_full_flow.ollama_available

        def fake_dry_run_command(cmd, cwd, env, step_name, steps):
            dry_calls.append((step_name, cmd))
            steps[step_name]["status"] = "succeeded"
            return 0

        run_videoautopipeline_full_flow.run_command = fake_dry_run_command
        run_videoautopipeline_full_flow.ollama_available = lambda: True
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_videoautopipeline_full_flow.main([
                "--vap-root",
                str(vap_root),
                "--output-root",
                str(output_root),
                "--input-folder",
                str(input_folder),
                "--limit",
                "1",
                "--dry-run",
            ])
        run_videoautopipeline_full_flow.run_command = original_run_command
        run_videoautopipeline_full_flow.ollama_available = original_ollama_available
        summary = _summary_from(out.getvalue())
        assert code == 0
        assert len(dry_calls) == 1
        assert dry_calls[0][0] == "video_generation"
        assert "--dry-run" in dry_calls[0][1]
        assert "--json" in dry_calls[0][1]
        assert "--output-root" in dry_calls[0][1]
        assert summary["steps"]["video_generation"]["status"] == "planned"
        assert summary["steps"]["video_generation"]["media_processed"] is False
        assert "no media processed" in out.getvalue()

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
        captured_env = []
        original_run_command = run_videoautopipeline_full_flow.run_command
        original_ollama_available = run_videoautopipeline_full_flow.ollama_available

        def fake_run_command(cmd, cwd, env, step_name, steps):
            captured.append(cmd)
            captured_env.append(dict(env))
            steps[step_name]["status"] = "succeeded"
            if step_name == "video_generation":
                final = output_root / "job1" / "final" / "clip.mp4"
                final.parent.mkdir(parents=True, exist_ok=True)
                final.write_bytes(b"video")
                status_dir = output_root / "job1" / "status"
                status_dir.mkdir(parents=True, exist_ok=True)
                (status_dir / "job1.status.json").write_text(json.dumps({
                    "status": "succeeded_waiting_for_plato",
                    "davinci_mode": "required",
                    "davinci_attempted": True,
                    "davinci_succeeded": True,
                    "davinci_output_path": str(final),
                    "davinci_error": "",
                }), encoding="utf-8")
            if step_name == "plato_analysis":
                delivery = Path(env["PLATO_VAP_DELIVERY_ROOT"])
                delivery.mkdir(parents=True, exist_ok=True)
                (delivery / "delivery_summary.json").write_text(json.dumps({
                    "jobs": [{
                        "plato_status": "approved",
                        "plato_score": 80,
                        "plato_verdict": "SAFE TO TEST",
                        "improvement_status": "accepted",
                        "improvement_attempted": True,
                        "improvement_accepted": True,
                        "fixed_output_path": str(output_root / "fixed.mp4"),
                        "reanalysis_status": "succeeded",
                        "reanalysis_score": 85,
                        "reanalysis_verdict": "SAFE TO TEST",
                        "delivery_status": "approved",
                        "telegram_status": "skipped",
                        "sent": False,
                        "approved_output_path": str(output_root / "fixed.mp4"),
                    }]
                }), encoding="utf-8")
            return 0

        run_videoautopipeline_full_flow.run_command = fake_run_command
        run_videoautopipeline_full_flow.ollama_available = lambda: False
        old_delivery = os.environ.get("PLATO_VAP_DELIVERY_ROOT")
        os.environ["PLATO_VAP_DELIVERY_ROOT"] = str(root / "delivery")
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
            run_videoautopipeline_full_flow.ollama_available = original_ollama_available
            if old_delivery is None:
                os.environ.pop("PLATO_VAP_DELIVERY_ROOT", None)
            else:
                os.environ["PLATO_VAP_DELIVERY_ROOT"] = old_delivery
        assert code == 0
        assert "--resume" in captured[0]
        assert "--force" in captured[0]
        assert captured_env[0]["VAP_ENABLE_LLM"] == "0"
        assert captured_env[0]["VAP_ENABLE_VISION"] == "0"
        assert captured_env[0]["VAP_DAVINCI_MODE"] == "required"
        assert captured_env[0]["VAP_REQUIRE_DAVINCI"] == "true"

        old_output = root / "old_output"

        def fake_old_success(cmd, cwd, env, step_name, steps):
            steps[step_name]["status"] = "succeeded"
            if step_name == "video_generation":
                final = old_output / "old" / "final" / "clip.mp4"
                final.parent.mkdir(parents=True, exist_ok=True)
                final.write_bytes(b"video")
                status_dir = old_output / "old" / "status"
                status_dir.mkdir(parents=True, exist_ok=True)
                (status_dir / "old.status.json").write_text(json.dumps({
                    "status": "succeeded_waiting_for_plato",
                    "send_mode": "after_plato",
                    "plato_required": True,
                    "plato_input_path": str(final),
                }), encoding="utf-8")
            return 0

        run_videoautopipeline_full_flow.run_command = fake_old_success
        run_videoautopipeline_full_flow.ollama_available = lambda: True
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_videoautopipeline_full_flow.main([
                "--vap-root",
                str(vap_root),
                "--output-root",
                str(old_output),
                "--input-folder",
                str(input_folder),
            ])
        run_videoautopipeline_full_flow.run_command = original_run_command
        run_videoautopipeline_full_flow.ollama_available = original_ollama_available
        summary = _summary_from(out.getvalue())
        assert code == 1
        assert summary["failed_step"] == "davinci"
        assert summary["steps"]["video_generation"]["status"] == "succeeded"
        assert "DaVinci proof missing" in summary["steps"]["davinci"]["error"]

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

        failure_steps = run_videoautopipeline_full_flow.steps_payload()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_videoautopipeline_full_flow.run_command(
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "print('\\u2713'); print('Worker failed: DaVinci Resolve is not available. Open DaVinci Resolve and try again.'); raise SystemExit(1)",
                ],
                root,
                os.environ.copy(),
                "video_generation",
                failure_steps,
            )
        assert code == 1
        assert "DaVinci Resolve is not available" in failure_steps["video_generation"]["reason"]
        assert "Worker failed: DaVinci Resolve is not available" in out.getvalue()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("test_one_click_full_run: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
