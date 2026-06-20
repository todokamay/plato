from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import VIDEOAUTOPIPELINE_OUTPUT_ROOT, VIDEOAUTOPIPELINE_ROOT
from modules.rerender_requests import list_rerender_requests, rerender_root
from tools.import_rerender_result import import_result


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_result(**payload) -> dict:
    payload.setdefault("ok", False)
    return payload


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _parse_json_output(stdout: str) -> dict:
    text = str(stdout or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return {}
    return {}


def _command_result(process: subprocess.CompletedProcess) -> dict:
    return {
        "returncode": process.returncode,
        "stdout": process.stdout or "",
        "stderr": process.stderr or "",
        "json": _parse_json_output(process.stdout or ""),
    }


def run_command(args: list[str], *, cwd: Path, env: dict[str, str]) -> dict:
    completed = subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return _command_result(completed)


def default_plato_processor(output_root: Path) -> dict:
    args = [
        sys.executable,
        "tools/process_videoautopipeline_outputs.py",
        str(output_root),
        "--include-rerenders",
        "--auto-fix",
        "--copy-results",
    ]
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    completed = subprocess.run(
        args,
        cwd=str(ROOT),
        env=env,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return _command_result(completed) | {"args": args}


def _latest_requested(root: Path) -> Path | None:
    items = list_rerender_requests("requested", root)
    if not items:
        return None
    return Path(items[0]["path"]).resolve()


def _request_path(path: str | Path | None, request_root: Path) -> tuple[Path | None, dict | None]:
    selected = Path(str(path)).resolve() if path else _latest_requested(request_root)
    if selected is None:
        return None, _json_result(status="no_request", message="No requested rerender request found.")
    if not _inside(selected, request_root):
        return None, _json_result(status="unsafe_path", message="Rerender request path must be inside Plato rerender_requests.", request_path=str(selected))
    if not selected.exists() or selected.suffix.lower() != ".json":
        return None, _json_result(status="missing_request", message=f"Rerender request JSON not found: {selected}", request_path=str(selected))
    return selected, None


def _mark_attempt(path: Path) -> dict:
    request = _read_json(path)
    attempts = int(request.get("repair_attempt_count") or 0)
    if attempts >= 1:
        return _json_result(status="max_retry_reached", message="This rerender request already used its one repair retry.", request_path=str(path))
    request["repair_attempt_count"] = attempts + 1
    request["repair_attempted_at"] = utc_now()
    _write_json(path, request)
    return {"ok": True, "request": request}


def run_repair_loop(
    *,
    vap_root: str | Path | None = None,
    output_root: str | Path | None = None,
    request_path: str | Path | None = None,
    confirm_real_rerender: bool = False,
    command_runner: Callable[..., dict] = run_command,
    plato_processor: Callable[[Path], dict] = default_plato_processor,
) -> dict:
    root = Path(vap_root or VIDEOAUTOPIPELINE_ROOT).resolve()
    output = Path(output_root or VIDEOAUTOPIPELINE_OUTPUT_ROOT).resolve()
    requests_root = rerender_root().resolve()
    selected, error = _request_path(request_path, requests_root)
    if error:
        return error

    tool = root / "tools" / "process_rerender_request.py"
    if not tool.exists():
        return _json_result(status="missing_vap_tool", message=f"VideoAutoPipeline rerender tool not found: {tool}")

    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")

    dry_args = [sys.executable, str(tool), str(selected), "--dry-run", "--json", "--output-root", str(output)]
    dry_run = command_runner(dry_args, cwd=root, env=env)
    summary = {
        "ok": dry_run.get("returncode") == 0,
        "status": "planned" if dry_run.get("returncode") == 0 else "failed",
        "dry_run": True,
        "confirm_real_rerender": bool(confirm_real_rerender),
        "request_path": str(selected),
        "steps": {"vap_dry_run": dry_run},
    }
    if dry_run.get("returncode") != 0:
        summary["message"] = "VAP rerender dry-run failed."
        return summary
    if not confirm_real_rerender:
        summary["message"] = "Dry-run complete. Enable confirm real rerender to create media."
        return summary

    attempt = _mark_attempt(selected)
    if not attempt.get("ok"):
        return attempt

    real_args = [sys.executable, str(tool), str(selected), "--json", "--output-root", str(output)]
    real = command_runner(real_args, cwd=root, env=env)
    summary["steps"]["vap_rerender"] = real
    status_path = Path(str((real.get("json") or {}).get("status_path") or "")).resolve()
    if real.get("returncode") != 0:
        if str(status_path) and _inside(status_path, output):
            summary["steps"]["import_result"] = import_result(status_path)
        summary.update(ok=False, status="failed", message="VAP rerender failed.")
        return summary

    if not status_path or not _inside(status_path, output):
        summary.update(ok=False, status="failed", message="VAP rerender status path was missing or outside output root.")
        return summary

    imported = import_result(status_path)
    summary["steps"]["import_result"] = imported
    if not imported.get("ok"):
        summary.update(ok=False, status="failed", message=imported.get("reason") or "Could not import rerender result.")
        return summary

    processed = plato_processor(output)
    summary["steps"]["plato_recheck"] = processed
    summary["ok"] = processed.get("returncode", 0) == 0
    summary["status"] = "completed" if summary["ok"] else "failed"
    summary["dry_run"] = False
    summary["message"] = "Rerender repair loop completed." if summary["ok"] else "Plato rerender re-check failed."
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one safe Plato/VAP rerender repair loop.")
    parser.add_argument("--vap-root", default=str(VIDEOAUTOPIPELINE_ROOT))
    parser.add_argument("--output-root", default=str(VIDEOAUTOPIPELINE_OUTPUT_ROOT))
    parser.add_argument("--request-path", default="")
    parser.add_argument("--confirm-real-rerender", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_repair_loop(
        vap_root=args.vap_root,
        output_root=args.output_root,
        request_path=args.request_path or None,
        confirm_real_rerender=args.confirm_real_rerender,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result.get("message") or result.get("status") or result)
    return 0 if result.get("ok") or result.get("status") == "no_request" else 1


if __name__ == "__main__":
    raise SystemExit(main())
