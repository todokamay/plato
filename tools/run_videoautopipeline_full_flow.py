from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PREFIX = "FULL_PIPELINE_SUMMARY "


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run VideoAutoPipeline, then process its outputs through Plato.")
    parser.add_argument("--vap-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--input-video", default="")
    parser.add_argument("--input-folder", default="")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--auto-fix", action="store_true")
    parser.add_argument("--copy-results", action="store_true")
    parser.add_argument("--send-telegram", action="store_true")
    return parser.parse_args(argv)


def ollama_available() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=1):
            return True
    except OSError:
        return False


def steps_payload() -> dict:
    return {
        "video_generation": {"status": "pending", "reason": ""},
        "plato_qc": {"status": "pending", "reason": ""},
        "auto_fix": {"status": "pending", "reason": ""},
        "delivery": {"status": "pending", "reason": ""},
    }


def finish(code: int, steps: dict, failed_step: str = "") -> int:
    payload = {
        "overall_status": "succeeded" if code == 0 else "failed",
        "failed_step": failed_step,
        "steps": steps,
    }
    print()
    print(SUMMARY_PREFIX + json.dumps(payload, separators=(",", ":"), ensure_ascii=True), flush=True)
    return code


def run_command(cmd: list[str], cwd: Path, env: dict, step_name: str, steps: dict) -> int:
    steps[step_name]["status"] = "running"
    print(f"FULL_PIPELINE_STEP {step_name} started", flush=True)
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        shell=False,
    )
    while True:
        try:
            code = process.wait(timeout=30)
            break
        except subprocess.TimeoutExpired:
            print(f"FULL_PIPELINE_STEP {step_name} still running", flush=True)
    if code:
        steps[step_name]["status"] = "failed"
        steps[step_name]["reason"] = f"exit code {code}"
    else:
        steps[step_name]["status"] = "succeeded"
    print(f"FULL_PIPELINE_STEP {step_name} {steps[step_name]['status']}", flush=True)
    return code


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    steps = steps_payload()
    vap_root = Path(args.vap_root)
    vap_app = vap_root / "app.py"
    if not vap_app.exists():
        steps["video_generation"] = {"status": "failed", "reason": f"app.py not found: {vap_app}"}
        return finish(2, steps, "video_generation")
    if not args.input_video and not args.input_folder:
        steps["video_generation"] = {"status": "failed", "reason": "input video or folder is required"}
        return finish(2, steps, "video_generation")

    env = os.environ.copy()
    env.update({
        "PYTHONUNBUFFERED": "1",
        "SEND_MODE": "after_plato",
        "VAP_SEND_MODE": "after_plato",
        "VAP_OUTPUT_DIR": str(Path(args.output_root)),
        "VIDEOAUTOPIPELINE_ROOT": str(vap_root),
        "VIDEOAUTOPIPELINE_OUTPUT_ROOT": str(Path(args.output_root)),
    })
    if not ollama_available():
        env.setdefault("VAP_ENABLE_LLM", "0")
        env.setdefault("VAP_ENABLE_VISION", "0")
        print("FULL_PIPELINE_STEP video_generation Ollama unavailable; VAP LLM/vision disabled", flush=True)

    vap_cmd = [sys.executable, "-u", str(vap_app), "--worker", args.input_video] if args.input_video else [sys.executable, "-u", str(vap_app), "--batch", args.input_folder]
    if args.input_folder and args.limit:
        vap_cmd.extend(["--limit", str(args.limit)])
    vap_cmd.append("--resume")
    code = run_command(vap_cmd, vap_root, env, "video_generation", steps)
    if code:
        return finish(code, steps, "video_generation")

    plato_cmd = [sys.executable, "-u", str(ROOT / "tools" / "process_videoautopipeline_outputs.py"), str(Path(args.output_root))]
    if args.auto_fix:
        plato_cmd.append("--auto-fix")
    if args.copy_results:
        plato_cmd.append("--copy-results")
    if args.dry_run:
        plato_cmd.append("--dry-run")
    if args.send_telegram:
        plato_cmd.append("--send-telegram")
    code = run_command(plato_cmd, ROOT, env, "plato_qc", steps)
    if code:
        steps["auto_fix"] = {"status": "skipped", "reason": "stopped after Plato QC failure"}
        steps["delivery"] = {"status": "skipped", "reason": "stopped after Plato QC failure"}
        return finish(code, steps, "plato_qc")
    steps["auto_fix"]["status"] = "succeeded" if args.auto_fix else "skipped"
    steps["delivery"]["status"] = "dry_run" if args.dry_run else "requested" if args.send_telegram else "skipped"
    steps["delivery"]["reason"] = "dry run" if args.dry_run else ""
    return finish(0, steps)


if __name__ == "__main__":
    raise SystemExit(main())
