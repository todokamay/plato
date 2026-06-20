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
from modules.job_runner import _command_for_action, _vap_env
from tools import process_videoautopipeline_outputs as process_tool
from tools import run_videoautopipeline_full_flow


def temp_root() -> Path:
    root = project_path("data/temp") / f"quality_first_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_waiting_job(base: Path, job_id: str) -> Path:
    final = base / job_id / "final" / "clip.mp4"
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(b"video")
    metadata = base / job_id / "metadata" / f"{job_id}.metadata.json"
    status = base / job_id / "status" / f"{job_id}.status.json"
    metadata.parent.mkdir(parents=True, exist_ok=True)
    status.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text("{}", encoding="utf-8")
    status.write_text(json.dumps({
        "job_id": job_id,
        "status": "succeeded_waiting_for_plato",
        "send_mode": "after_plato",
        "plato_required": True,
        "plato_input_path": str(final),
    }), encoding="utf-8")
    return final


def test_ui_and_full_flow_env():
    root = temp_root()
    try:
        vap_root = root / "VideoAutoPipeline"
        output_root = root / "output"
        input_folder = root / "input"
        vap_root.mkdir()
        output_root.mkdir()
        input_folder.mkdir()
        (vap_root / "app.py").write_text("print('fake')\n", encoding="utf-8")

        html = TestClient(app).get("/operator").text
        assert "Factory Preset" in html
        assert 'id="vap-factory-preset"' in html
        assert 'id="vap-top-render-count"' in html
        assert "Will render up to 6 candidates, stop after 3 approved." in html

        args, _ = _command_for_action(
            "run_full_videoautopipeline_to_plato_flow",
            input_folder=str(input_folder),
            output_root=str(output_root),
            vap_root=str(vap_root),
            factory_preset="fast",
            max_candidates=3,
            top_render_count=2,
            stop_after_approved=1,
            whisper_model="small",
        )
        assert "--factory-preset" in args and args[args.index("--factory-preset") + 1] == "fast"
        assert "--top-render-count" in args and args[args.index("--top-render-count") + 1] == "2"
        assert "--stop-after-approved" in args and args[args.index("--stop-after-approved") + 1] == "1"

        env = _vap_env(
            vap_root=str(vap_root),
            output_root=str(output_root),
            factory_preset="fast",
            max_candidates=3,
            top_render_count=2,
            stop_after_approved=1,
            whisper_model="small",
        )
        assert env["FACTORY_PRESET"] == "fast"
        assert env["VAP_MAX_CANDIDATES"] == "3"
        assert env["VAP_TOP_RENDER_COUNT"] == "2"
        assert env["VAP_STOP_AFTER_APPROVED"] == "1"
        assert env["VAP_WHISPER_MODEL"] == "small"

        captured = []
        old_run = run_videoautopipeline_full_flow.run_command
        old_ollama = run_videoautopipeline_full_flow.ollama_available

        def fake_run(cmd, cwd, env, step_name, steps):
            captured.append((step_name, cmd, dict(env)))
            steps[step_name]["status"] = "succeeded"
            if step_name == "video_generation":
                final = output_root / "job1" / "final" / "clip_davinci_final.mp4"
                final.parent.mkdir(parents=True, exist_ok=True)
                final.write_bytes(b"video")
                status = output_root / "job1" / "status" / "job1.status.json"
                status.parent.mkdir(parents=True, exist_ok=True)
                status.write_text(json.dumps({
                    "davinci_attempted": True,
                    "davinci_succeeded": True,
                    "davinci_output_path": str(final),
                }), encoding="utf-8")
            if step_name == "plato_analysis":
                delivery = Path(env["PLATO_VAP_DELIVERY_ROOT"])
                delivery.mkdir(parents=True, exist_ok=True)
                approved = output_root / "approved.mp4"
                approved.write_bytes(b"approved")
                (delivery / "delivery_summary.json").write_text(json.dumps({"jobs": [{
                    "plato_status": "approved",
                    "plato_score": 91,
                    "plato_verdict": "PUBLISH",
                    "delivery_status": "approved",
                    "telegram_status": "skipped",
                    "approved_output_path": str(approved),
                }]}), encoding="utf-8")
            return 0

        run_videoautopipeline_full_flow.run_command = fake_run
        run_videoautopipeline_full_flow.ollama_available = lambda: True
        old_delivery = os.environ.get("PLATO_VAP_DELIVERY_ROOT")
        os.environ["PLATO_VAP_DELIVERY_ROOT"] = str(root / "delivery")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                code = run_videoautopipeline_full_flow.main([
                    "--vap-root", str(vap_root),
                    "--output-root", str(output_root),
                    "--input-folder", str(input_folder),
                    "--factory-preset", "fast",
                    "--max-candidates", "3",
                    "--top-render-count", "2",
                    "--stop-after-approved", "1",
                    "--whisper-model", "small",
                ])
        finally:
            run_videoautopipeline_full_flow.run_command = old_run
            run_videoautopipeline_full_flow.ollama_available = old_ollama
            if old_delivery is None:
                os.environ.pop("PLATO_VAP_DELIVERY_ROOT", None)
            else:
                os.environ["PLATO_VAP_DELIVERY_ROOT"] = old_delivery
        assert code == 0
        assert captured[0][2]["FACTORY_PRESET"] == "fast"
        assert captured[0][2]["VAP_TOP_RENDER_COUNT"] == "2"
        assert "--stop-after-approved" in captured[1][1]

    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_stop_after_approved_skips_remaining_outputs():
    root = temp_root()
    delivery = root / "delivery"
    old_delivery = os.environ.get("PLATO_VAP_DELIVERY_ROOT")
    old_qc = process_tool.run_auto_qc_fix
    try:
        base = root / "output"
        write_waiting_job(base, "job1")
        write_waiting_job(base, "job2")
        os.environ["PLATO_VAP_DELIVERY_ROOT"] = str(delivery)
        process_tool.run_auto_qc_fix = lambda *args, **kwargs: {"clips": [{
            "filename": "clip.mp4",
            "final_bucket": "publish_ready",
            "fix_accepted": False,
            "original_adjusted_score": 90,
            "original_final_verdict": "PUBLISH",
        }]}
        with contextlib.redirect_stdout(io.StringIO()):
            assert process_tool.main([str(base), "--auto-fix", "--copy-results", "--stop-after-approved", "1"]) == 0
        summary = json.loads((delivery / "delivery_summary.json").read_text(encoding="utf-8"))
        assert summary["approved_count"] == 1
        assert summary["jobs"][1]["delivery_status"] == "skipped_after_approved_limit"
        assert summary["jobs"][1]["approved_output_path"] == ""
    finally:
        process_tool.run_auto_qc_fix = old_qc
        if old_delivery is None:
            os.environ.pop("PLATO_VAP_DELIVERY_ROOT", None)
        else:
            os.environ["PLATO_VAP_DELIVERY_ROOT"] = old_delivery
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    test_ui_and_full_flow_env()
    test_stop_after_approved_skips_remaining_outputs()
    print("test_quality_first_performance: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
