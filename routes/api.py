from __future__ import annotations

from fastapi import APIRouter, Request

from modules.health_engine import system_health
from modules.history_engine import history_entries, history_summary
from modules.job_runner import get_job, list_jobs
from modules.operator_actions import (
    operator_status,
    start_auto_qc_job,
    start_auto_qc_replace_job,
    start_batch_qc_job,
    start_detect_job,
    start_dry_run_job,
    start_production_diagnostics_job,
    start_replace_rollback_job,
    start_watch_job,
    stop_watch_job,
)
from modules.orchestrator import orchestrator_status
from modules.production_diagnostics import production_diagnostics_snapshot
from modules.queue_engine import queue_stats
from modules.report_center import report_payload


router = APIRouter(prefix="/api")


def _safe_payload(factory, fallback: dict) -> dict:
    try:
        return factory()
    except Exception as exc:
        return {**fallback, "ok": False, "error": str(exc)}


@router.get("/status")
def api_status():
    return _safe_payload(orchestrator_status, {"orchestrator_state": "degraded", "health": {}})


@router.get("/runs")
def api_runs():
    return _safe_payload(lambda: report_payload("all-time"), {"view": "all-time", "counts": {}, "runs": []})


@router.get("/queue")
def api_queue():
    return _safe_payload(queue_stats, {"total": 0, "counts": {}, "items": []})


@router.get("/health")
def api_health():
    return _safe_payload(system_health, {"state": "warning"})


@router.get("/history")
def api_history():
    return _safe_payload(lambda: {"summary": history_summary(), "entries": history_entries(limit=100)}, {"summary": {}, "entries": []})


@router.get("/production-diagnostics")
def api_production_diagnostics():
    return _safe_payload(lambda: production_diagnostics_snapshot(include_checks=False), {"ok": False, "latest_runs": {}, "recommendations": []})


async def _json_body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _folder_from_body(data: dict) -> str:
    return str(data.get("folder") or data.get("input_folder") or "").strip()


def _text_from_body(data: dict, key: str) -> str:
    return str(data.get(key) or "").strip()


@router.get("/operator/status")
def api_operator_status():
    return _safe_payload(operator_status, {"ok": False, "jobs": {}, "queue": {}})


@router.post("/operator/detect")
def api_operator_detect():
    return _safe_payload(start_detect_job, {"ok": False, "error": "Could not start detection."})


@router.post("/operator/dry-run")
def api_operator_dry_run():
    return _safe_payload(start_dry_run_job, {"ok": False, "error": "Could not start dry run."})


@router.post("/operator/export-production-diagnostics")
def api_operator_export_production_diagnostics():
    return _safe_payload(start_production_diagnostics_job, {"ok": False, "error": "Could not export production diagnostics."})


@router.post("/operator/auto-qc-once")
async def api_operator_auto_qc_once(request: Request):
    data = await _json_body(request)
    return _safe_payload(lambda: start_auto_qc_job(_folder_from_body(data)), {"ok": False, "error": "Could not start Auto QC."})


@router.post("/operator/auto-qc-replace-once")
async def api_operator_auto_qc_replace_once(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: start_auto_qc_replace_job(
            _folder_from_body(data),
            _text_from_body(data, "backup_dir"),
            replace_enabled=bool(data.get("replace_enabled")),
            replace_confirmed=bool(data.get("replace_confirmed")),
        ),
        {"ok": False, "error": "Could not start Safe Replace Auto QC."},
    )


@router.post("/operator/rollback-replace-log")
async def api_operator_rollback_replace_log(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: start_replace_rollback_job(_text_from_body(data, "log_path")),
        {"ok": False, "error": "Could not start Safe Replace rollback."},
    )


@router.post("/operator/batch-qc-once")
async def api_operator_batch_qc_once(request: Request):
    data = await _json_body(request)
    return _safe_payload(lambda: start_batch_qc_job(_folder_from_body(data)), {"ok": False, "error": "Could not start Batch QC."})


@router.post("/operator/watch/start")
async def api_operator_watch_start(request: Request):
    data = await _json_body(request)
    return _safe_payload(lambda: start_watch_job(_folder_from_body(data)), {"ok": False, "error": "Could not start watch mode."})


@router.post("/operator/watch/stop")
def api_operator_watch_stop():
    return _safe_payload(stop_watch_job, {"ok": False, "error": "Could not stop watch mode."})


@router.get("/operator/jobs")
def api_operator_jobs():
    return _safe_payload(lambda: {"ok": True, "jobs": list_jobs(limit=50)}, {"ok": False, "jobs": []})


@router.get("/operator/jobs/{job_id}")
def api_operator_job(job_id: str):
    return _safe_payload(lambda: {"ok": True, "job": get_job(job_id)}, {"ok": False, "job": None})
