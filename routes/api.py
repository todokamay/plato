from __future__ import annotations

from fastapi import APIRouter

from modules.health_engine import system_health
from modules.history_engine import history_entries, history_summary
from modules.orchestrator import orchestrator_status
from modules.queue_engine import queue_stats
from modules.report_center import report_payload


router = APIRouter(prefix="/api")


@router.get("/status")
def api_status():
    return orchestrator_status()


@router.get("/runs")
def api_runs():
    return report_payload("all-time")


@router.get("/queue")
def api_queue():
    return queue_stats()


@router.get("/health")
def api_health():
    return system_health()


@router.get("/history")
def api_history():
    return {"summary": history_summary(), "entries": history_entries(limit=100)}
