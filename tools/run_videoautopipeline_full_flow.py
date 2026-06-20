from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.final_cleanup import cleanup_after_delivery
from modules.videoautopipeline_contract import default_delivery_root

SUMMARY_PREFIX = "FULL_PIPELINE_SUMMARY "
DAVINCI_MODES = {"required", "optional", "disabled"}
CLEANUP_MODES = {"keep_final_only", "keep_all", "dry_run"}
FACTORY_PRESETS = {"quality", "balanced", "fast", "archive"}
WHISPER_MODELS = {"small", "medium", "large-v3"}
ALLOW_SAFE_PRESETS = {"balanced", "fast"}


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
    parser.add_argument("--davinci-mode", choices=sorted(DAVINCI_MODES), default="required")
    parser.add_argument("--cleanup-mode", choices=sorted(CLEANUP_MODES), default="keep_all")
    parser.add_argument("--confirm-cleanup", action="store_true")
    parser.add_argument("--factory-preset", choices=sorted(FACTORY_PRESETS), default="quality")
    parser.add_argument("--max-candidates", type=int, default=12)
    parser.add_argument("--top-render-count", type=int, default=6)
    parser.add_argument("--stop-after-approved", type=int, default=3)
    parser.add_argument("--whisper-model", choices=sorted(WHISPER_MODELS), default="medium")
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
        "davinci": {"status": "pending", "attempted": False, "succeeded": False, "output_path": "", "error": ""},
        "plato_analysis": {"status": "pending", "score": "", "verdict": ""},
        "plato_improvement": {"status": "pending", "attempted": False, "accepted": False, "fixed_output_path": "", "reason": ""},
        "reanalysis": {"status": "pending", "score": "", "verdict": ""},
        "delivery": {"status": "pending", "sent": False, "telegram_status": "skipped", "approved_output_path": ""},
        "cleanup": {"status": "pending", "mode": "keep_all", "deleted_count": 0, "reason": ""},
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


def _failure_reason(lines: list[str], code: int) -> str:
    recent = [line.strip() for line in lines if line.strip()]
    markers = ("worker failed", "render failed", "not available", "error", "exception", "traceback", "failed:")
    for marker in markers:
        for line in reversed(recent):
            if marker in line.lower():
                return line
    return recent[-1] if recent else f"exit code {code}"


def _display_cmd(cmd: list[str]) -> str:
    return " ".join(str(part) for part in cmd)


def run_command(cmd: list[str], cwd: Path, env: dict, step_name: str, steps: dict) -> int:
    steps[step_name]["status"] = "running"
    print(f"FULL_PIPELINE_STEP {step_name} started", flush=True)
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    recent_lines: list[str] = []
    if process.stdout:
        for line in process.stdout:
            print(line, end="", flush=True)
            text = line.strip()
            if text:
                recent_lines.append(text)
                del recent_lines[:-80]
    code = process.wait()
    if code:
        steps[step_name]["status"] = "failed"
        steps[step_name]["reason"] = _failure_reason(recent_lines, code)
    else:
        steps[step_name]["status"] = "succeeded"
    print(f"FULL_PIPELINE_STEP {step_name} {steps[step_name]['status']}", flush=True)
    return code


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _latest_status(output_root: Path) -> dict:
    files = [
        path for path in output_root.glob("*/status/*.json")
        if path.parent.parent.name not in {"batches", "jobs"}
    ]
    if not files:
        return {}
    return _load_json(max(files, key=lambda path: path.stat().st_mtime))


def _existing_status_mp4(status: dict) -> str:
    candidates = [
        status.get("davinci_output_path"),
        status.get("davinci_proof_path"),
        status.get("final_output_path"),
        status.get("plato_input_path"),
    ]
    candidates.extend(status.get("final_paths") or [])
    for value in candidates:
        path = Path(value or "")
        if path.exists() and path.is_file() and path.suffix.lower() == ".mp4":
            return str(path)
    return ""


def apply_davinci_step(steps: dict, status: dict, mode: str) -> bool:
    output = _existing_status_mp4(status)
    succeeded = bool(status.get("davinci_succeeded")) and bool(output)
    attempted = bool(status.get("davinci_attempted"))
    error = status.get("davinci_error") or ""
    if mode == "required" and not succeeded and not error:
        if not status:
            error = "No VideoAutoPipeline status.json found after generation."
        elif not attempted:
            error = "Required DaVinci proof missing; the VideoAutoPipeline job may have reused an older success."
        else:
            error = "Durable DaVinci final MP4 missing."
    steps["davinci"].update({
        "status": "succeeded" if succeeded else "failed" if mode == "required" else "skipped" if mode == "disabled" else "optional_failed",
        "attempted": attempted,
        "succeeded": succeeded,
        "output_path": output if succeeded else "",
        "error": "" if succeeded else error,
    })
    return mode != "required" or succeeded


def apply_delivery_summary(steps: dict, payload: dict) -> None:
    row = (payload.get("jobs") or [{}])[0]
    steps["plato_analysis"].update({
        "status": row.get("plato_status") or "skipped",
        "score": row.get("plato_score", ""),
        "verdict": row.get("plato_verdict", ""),
    })
    steps["plato_improvement"].update({
        "status": row.get("improvement_status") or "skipped",
        "attempted": bool(row.get("improvement_attempted")),
        "accepted": bool(row.get("improvement_accepted")),
        "fixed_output_path": row.get("fixed_output_path", ""),
        "reason": row.get("improvement_reason") or row.get("reason", ""),
    })
    steps["reanalysis"].update({
        "status": row.get("reanalysis_status") or "skipped",
        "score": row.get("reanalysis_score", ""),
        "verdict": row.get("reanalysis_verdict", ""),
    })
    steps["delivery"].update({
        "status": row.get("delivery_status") or "not_sent",
        "sent": bool(row.get("sent")),
        "telegram_status": row.get("telegram_status") or "skipped",
        "approved_output_path": row.get("approved_output_path", ""),
    })


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
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "SEND_MODE": "after_plato",
        "VAP_SEND_MODE": "after_plato",
        "VAP_DAVINCI_MODE": args.davinci_mode,
        "VAP_REQUIRE_DAVINCI": "true" if args.davinci_mode == "required" else "false",
        "FACTORY_PRESET": args.factory_preset,
        "VAP_MAX_CANDIDATES": str(max(0, args.max_candidates or 0)),
        "VAP_TOP_RENDER_COUNT": str(max(0, args.top_render_count or 0)),
        "VAP_STOP_AFTER_APPROVED": str(max(0, args.stop_after_approved or 0)),
        "VAP_WHISPER_MODEL": args.whisper_model,
        "VAP_ALLOW_SAFE_TO_TEST": "true" if args.factory_preset in ALLOW_SAFE_PRESETS else "false",
        "ALLOW_SAFE_TO_TEST": "true" if args.factory_preset in ALLOW_SAFE_PRESETS else "false",
        "CLEANUP_MODE": args.cleanup_mode,
        "VAP_OUTPUT_DIR": str(Path(args.output_root)),
        "VIDEOAUTOPIPELINE_ROOT": str(vap_root),
        "VIDEOAUTOPIPELINE_OUTPUT_ROOT": str(Path(args.output_root)),
    })
    if not ollama_available():
        env.setdefault("VAP_ENABLE_LLM", "0")
        env.setdefault("VAP_ENABLE_VISION", "0")
        print("FULL_PIPELINE_STEP video_generation Ollama unavailable; VAP LLM/vision disabled", flush=True)

    plato_cmd = [sys.executable, "-u", str(ROOT / "tools" / "process_videoautopipeline_outputs.py"), str(Path(args.output_root))]
    if args.stop_after_approved:
        plato_cmd.extend(["--stop-after-approved", str(max(0, args.stop_after_approved))])
    if args.auto_fix:
        plato_cmd.append("--auto-fix")
    if args.copy_results:
        plato_cmd.append("--copy-results")
    if args.dry_run:
        plato_cmd.append("--dry-run")
    if args.send_telegram:
        plato_cmd.append("--send-telegram")

    if args.input_video:
        vap_cmd = [sys.executable, "-u", str(vap_app), "--worker", args.input_video]
    else:
        vap_cmd = [sys.executable, "-u", str(vap_app), "--batch", args.input_folder, "--output-root", str(Path(args.output_root))]
    if args.input_folder and args.limit:
        vap_cmd.extend(["--limit", str(args.limit)])

    if args.dry_run:
        mode = "video" if args.input_video else "folder"
        planned_vap = list(vap_cmd)
        if args.input_folder:
            planned_vap.extend(["--dry-run", "--json"])
            code = run_command(planned_vap, vap_root, env, "video_generation", steps)
            if code:
                return finish(code, steps, "video_generation")
        else:
            print("FULL_PIPELINE_STEP video_generation single-video dry-run is plan-only", flush=True)
        steps["video_generation"].update({
            "status": "planned",
            "reason": "dry run: no media processed",
            "planned_input": args.input_video or args.input_folder,
            "mode": mode,
            "limit": args.limit or "",
            "planned_vap_command": _display_cmd(planned_vap),
            "planned_plato_command": _display_cmd(plato_cmd),
            "factory_preset": args.factory_preset,
            "top_render_count": max(0, args.top_render_count or 0),
            "stop_after_approved": max(0, args.stop_after_approved or 0),
            "media_processed": False,
        })
        steps["davinci"].update({"status": "skipped", "error": "dry run"})
        steps["plato_analysis"].update({"status": "planned", "verdict": "dry run"})
        steps["plato_improvement"].update({"status": "skipped", "reason": "dry run"})
        steps["reanalysis"].update({"status": "skipped", "verdict": "dry run"})
        steps["delivery"].update({"status": "skipped", "telegram_status": "dry_run"})
        steps["cleanup"].update({"status": "skipped", "mode": args.cleanup_mode, "reason": "dry run"})
        print("FULL_PIPELINE_DRY_RUN no media processed", flush=True)
        return finish(0, steps)

    vap_cmd.append("--resume")
    if args.davinci_mode == "required":
        vap_cmd.append("--force")
    code = run_command(vap_cmd, vap_root, env, "video_generation", steps)
    if code:
        return finish(code, steps, "video_generation")
    status = _latest_status(Path(args.output_root))
    if not apply_davinci_step(steps, status, args.davinci_mode):
        steps["plato_analysis"]["status"] = "skipped"
        steps["plato_improvement"]["status"] = "skipped"
        steps["reanalysis"]["status"] = "skipped"
        steps["delivery"]["status"] = "skipped"
        return finish(1, steps, "davinci")

    code = run_command(plato_cmd, ROOT, env, "plato_analysis", steps)
    if code:
        steps["plato_improvement"]["status"] = "skipped"
        steps["reanalysis"]["status"] = "skipped"
        steps["delivery"]["status"] = "skipped"
        return finish(code, steps, "plato_analysis")
    delivery_root = Path(env.get("PLATO_VAP_DELIVERY_ROOT") or default_delivery_root())
    delivery_summary_path = delivery_root / "delivery_summary.json"
    delivery_payload = _load_json(delivery_summary_path)
    apply_delivery_summary(steps, delivery_payload)
    if not args.dry_run and not any(row.get("approved_output_path") for row in delivery_payload.get("jobs", [])):
        steps["delivery"]["status"] = "not_sent"
        return finish(1, steps, "delivery")
    cleanup_mode = "dry_run" if args.dry_run and args.cleanup_mode == "keep_final_only" else args.cleanup_mode
    steps["cleanup"]["mode"] = cleanup_mode
    if cleanup_mode == "keep_all":
        steps["cleanup"].update({"status": "skipped", "reason": "keep_all"})
    else:
        cleanup = cleanup_after_delivery(
            delivery_summary_path,
            mode=cleanup_mode,
            confirm=args.confirm_cleanup,
        )
        steps["cleanup"].update({
            "status": "succeeded" if cleanup.get("ok") else "failed",
            "deleted_count": len(cleanup.get("deleted") or []),
            "reason": "; ".join(cleanup.get("errors") or cleanup.get("skipped") or []),
        })
        if cleanup_mode == "keep_final_only" and not cleanup.get("ok"):
            return finish(1, steps, "cleanup")
    return finish(0, steps)


if __name__ == "__main__":
    raise SystemExit(main())
