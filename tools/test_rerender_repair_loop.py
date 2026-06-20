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
from modules.job_runner import _command_for_action
from modules.rerender_requests import build_rerender_request, get_rerender_stats, write_rerender_request
from tools.run_rerender_repair_loop import run_repair_loop


def temp_root(prefix: str) -> Path:
    path = project_path("data/temp") / f"{prefix}_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def fake_vap(root: Path) -> None:
    (root / "tools").mkdir(parents=True)
    (root / "app.py").write_text("print('fake')\n", encoding="utf-8")
    (root / "tools" / "process_rerender_request.py").write_text("print('fake')\n", encoding="utf-8")


def write_request(request_root: Path, source: Path) -> dict:
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"source")
    request = build_rerender_request(
        {"job_id": "job1", "source_final_path": str(source)},
        {"route": "vap_rerender", "blocker_type": "subtitle overlap", "reason": "subtitle overlap"},
    )
    with with_env({"PLATO_RERENDER_REQUEST_ROOT": request_root}):
        return write_rerender_request(request)["request"]


def test_no_request_and_unsafe_path_are_friendly() -> None:
    root = temp_root("repair_no_request")
    request_root = temp_root("repair_no_request_queue")
    output = temp_root("repair_no_request_output")
    try:
        fake_vap(root)
        with with_env({"PLATO_RERENDER_REQUEST_ROOT": request_root}):
            result = run_repair_loop(vap_root=root, output_root=output)
            assert result["status"] == "no_request"
            assert "No requested rerender" in result["message"]

            unsafe = run_repair_loop(vap_root=root, output_root=output, request_path=ROOT / "config.py")
            assert unsafe["status"] == "unsafe_path"
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(request_root, ignore_errors=True)
        shutil.rmtree(output, ignore_errors=True)


def test_dry_run_does_not_create_media_or_import() -> None:
    root = temp_root("repair_dry_vap")
    request_root = temp_root("repair_dry_queue")
    output = temp_root("repair_dry_output")
    try:
        fake_vap(root)
        request = write_request(request_root, output / "source.mp4")
        calls = []

        def runner(args, *, cwd, env):
            calls.append(args)
            return {"returncode": 0, "stdout": json.dumps({"ok": True, "dry_run": True}), "stderr": "", "json": {"ok": True}}

        def processor(_output):
            raise AssertionError("dry-run repair must not run Plato recheck")

        with with_env({"PLATO_RERENDER_REQUEST_ROOT": request_root}):
            result = run_repair_loop(vap_root=root, output_root=output, command_runner=runner, plato_processor=processor)
            assert result["ok"] is True
            assert result["dry_run"] is True
            assert len(calls) == 1
            assert "--dry-run" in calls[0]
            assert get_rerender_stats()["counts"]["requested"] == 1
            assert not list(output.glob("job1/rerender/*/final/*.mp4"))
            assert request["request_id"] in result["request_path"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(request_root, ignore_errors=True)
        shutil.rmtree(output, ignore_errors=True)


def test_confirmed_run_imports_result_and_rechecks_once() -> None:
    root = temp_root("repair_real_vap")
    request_root = temp_root("repair_real_queue")
    output = temp_root("repair_real_output")
    try:
        fake_vap(root)
        request = write_request(request_root, output / "source.mp4")
        processed = []

        def runner(args, *, cwd, env):
            if "--dry-run" in args:
                return {"returncode": 0, "stdout": json.dumps({"ok": True, "dry_run": True}), "stderr": "", "json": {"ok": True}}
            rendered = output / "job1" / "rerender" / request["request_id"] / "final" / "clip_rerendered.mp4"
            status = output / "job1" / "rerender" / request["request_id"] / "status" / f"{request['request_id']}.status.json"
            rendered.parent.mkdir(parents=True, exist_ok=True)
            status.parent.mkdir(parents=True, exist_ok=True)
            rendered.write_bytes(b"rendered")
            status.write_text(json.dumps({
                "request_id": request["request_id"],
                "job_id": "job1",
                "status": "completed",
                "rerendered_output_path": str(rendered),
            }), encoding="utf-8")
            return {"returncode": 0, "stdout": json.dumps({"ok": True, "status_path": str(status)}), "stderr": "", "json": {"ok": True, "status_path": str(status)}}

        def processor(process_output):
            processed.append(process_output)
            return {"returncode": 0, "stdout": "checked", "stderr": ""}

        with with_env({"PLATO_RERENDER_REQUEST_ROOT": request_root}):
            result = run_repair_loop(
                vap_root=root,
                output_root=output,
                confirm_real_rerender=True,
                command_runner=runner,
                plato_processor=processor,
            )
            assert result["ok"] is True
            assert get_rerender_stats()["counts"]["completed"] == 1
            assert processed == [output.resolve()]

            second = run_repair_loop(
                vap_root=root,
                output_root=output,
                request_path=request_root / "completed" / f"{request['request_id']}.json",
                confirm_real_rerender=True,
                command_runner=runner,
                plato_processor=processor,
            )
            assert second["status"] == "max_retry_reached"
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(request_root, ignore_errors=True)
        shutil.rmtree(output, ignore_errors=True)


def test_operator_action_api_and_ui() -> None:
    root = temp_root("repair_operator_vap")
    request_root = temp_root("repair_operator_queue")
    output = temp_root("repair_operator_output")
    try:
        fake_vap(root)
        with with_env({"PLATO_RERENDER_REQUEST_ROOT": request_root}):
            html = TestClient(app).get("/operator").text
            assert "Fix Latest Rerender Request" in html
            assert 'id="vap-confirm-real-rerender" type="checkbox"' in html

            args, _ = _command_for_action("repair_latest_rerender_request", vap_root=str(root), output_root=str(output))
            assert args[:2] == [sys.executable, "tools/run_rerender_repair_loop.py"]
            assert "--confirm-real-rerender" not in args
            confirmed_args, _ = _command_for_action(
                "repair_latest_rerender_request",
                vap_root=str(root),
                output_root=str(output),
                confirm_real_rerender=True,
            )
            assert "--confirm-real-rerender" in confirmed_args

            result = operator_actions.start_repair_latest_rerender_request_job(root, output)
            assert result["ok"] is False
            assert "No requested rerender" in result["error"]

            payload = TestClient(app).post("/api/operator/fix-latest-rerender-request", json={
                "vap_root": str(root),
                "output_root": str(output),
            }).json()
            assert payload["ok"] is False
            assert "No requested rerender" in payload["error"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(request_root, ignore_errors=True)
        shutil.rmtree(output, ignore_errors=True)


def main() -> int:
    test_no_request_and_unsafe_path_are_friendly()
    test_dry_run_does_not_create_media_or_import()
    test_confirmed_run_imports_result_and_rechecks_once()
    test_operator_action_api_and_ui()
    print("test_rerender_repair_loop: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
