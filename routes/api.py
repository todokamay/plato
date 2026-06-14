from __future__ import annotations

from fastapi import APIRouter

from modules.health_engine import system_health
from modules.history_engine import history_entries, history_summary
from modules.orchestrator import orchestrator_status
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
