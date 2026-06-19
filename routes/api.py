from __future__ import annotations

from fastapi import APIRouter, Request

from modules.health_engine import system_health
from modules.history_engine import history_entries, history_summary
from modules.job_runner import get_job, list_jobs
from modules.operator_actions import (
    control_room_status,
    operator_status,
    start_auto_qc_job,
    start_auto_qc_replace_job,
    start_batch_qc_job,
    start_detect_job,
    start_dry_run_job,
    start_production_diagnostics_job,
    start_replace_rollback_job,
    start_full_videoautopipeline_flow_job,
    start_open_videoautopipeline_gui_job,
    start_process_videoautopipeline_outputs_job,
    start_process_waiting_for_plato_job,
    start_retry_delivery_only_job,
    start_retry_full_pipeline_job,
    start_retry_plato_only_job,
    start_send_approved_to_telegram_job,
    start_vap_batch_dry_run_job,
    start_vap_delivery_process_job,
    start_vap_delivery_scan_job,
    start_vap_delivery_send_job,
    start_vap_generate_longvideos_job,
    start_vap_generate_one_video_job,
    start_vap_batch_generate_folder_job,
    start_vap_resume_failed_job,
    start_vap_status_job,
    start_videoautopipeline_batch_job,
    start_videoautopipeline_worker_job,
    start_watch_job,
    stop_watch_job,
    vap_show_output_root,
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


def _bool_from_body(data: dict, key: str, default: bool = False) -> bool:
    if key not in data:
        return default
    return bool(data.get(key))


@router.get("/operator/status")
def api_operator_status():
    return _safe_payload(operator_status, {"ok": False, "jobs": {}, "queue": {}})


@router.get("/operator/control-room-status")
def api_operator_control_room_status():
    return _safe_payload(control_room_status, {"ok": False, "status_bar": {}, "current_run": {}, "final_output": {}, "job_history": []})


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


@router.post("/operator/vap-delivery/scan")
async def api_operator_vap_delivery_scan(request: Request):
    data = await _json_body(request)
    return _safe_payload(lambda: start_vap_delivery_scan_job(_folder_from_body(data)), {"ok": False, "error": "Could not scan VideoAutoPipeline jobs."})


@router.post("/operator/vap-delivery/process")
async def api_operator_vap_delivery_process(request: Request):
    data = await _json_body(request)
    return _safe_payload(lambda: start_vap_delivery_process_job(_folder_from_body(data)), {"ok": False, "error": "Could not process VideoAutoPipeline jobs."})


@router.post("/operator/vap-delivery/send")
async def api_operator_vap_delivery_send(request: Request):
    data = await _json_body(request)
    return _safe_payload(lambda: start_vap_delivery_send_job(_folder_from_body(data)), {"ok": False, "error": "Could not process/send VideoAutoPipeline jobs."})


@router.post("/operator/videoautopipeline-worker")
async def api_operator_videoautopipeline_worker(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: start_videoautopipeline_worker_job(
            _text_from_body(data, "vap_root"),
            _text_from_body(data, "input_video"),
            _text_from_body(data, "output_root"),
        ),
        {"ok": False, "error": "Could not start VideoAutoPipeline worker."},
    )


@router.post("/operator/open-videoautopipeline-gui")
async def api_operator_open_videoautopipeline_gui(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: start_open_videoautopipeline_gui_job(_text_from_body(data, "vap_root")),
        {"ok": False, "error": "Could not open VideoAutoPipeline GUI."},
    )


@router.post("/operator/vap-generate-longvideos")
async def api_operator_vap_generate_longvideos(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: start_vap_generate_longvideos_job(_text_from_body(data, "vap_root"), _text_from_body(data, "output_root"), data.get("limit")),
        {"ok": False, "error": "Could not generate from LongVideos."},
    )


@router.post("/operator/vap-generate-one-video")
async def api_operator_vap_generate_one_video(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: start_vap_generate_one_video_job(_text_from_body(data, "vap_root"), _text_from_body(data, "input_video"), _text_from_body(data, "output_root")),
        {"ok": False, "error": "Could not generate one video."},
    )


@router.post("/operator/vap-batch-generate-folder")
async def api_operator_vap_batch_generate_folder(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: start_vap_batch_generate_folder_job(_text_from_body(data, "vap_root"), _text_from_body(data, "input_folder"), _text_from_body(data, "output_root"), data.get("limit")),
        {"ok": False, "error": "Could not batch generate folder."},
    )


@router.post("/operator/vap-batch-dry-run")
async def api_operator_vap_batch_dry_run(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: start_vap_batch_dry_run_job(_text_from_body(data, "vap_root"), _text_from_body(data, "input_folder"), _text_from_body(data, "output_root"), data.get("limit")),
        {"ok": False, "error": "Could not dry-run batch."},
    )


@router.post("/operator/vap-resume-failed")
async def api_operator_vap_resume_failed(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: start_vap_resume_failed_job(
            _text_from_body(data, "vap_root"),
            _text_from_body(data, "output_root"),
            input_video=_text_from_body(data, "input_video"),
            input_folder=_text_from_body(data, "input_folder"),
            limit=data.get("limit"),
        ),
        {"ok": False, "error": "Could not resume failed VideoAutoPipeline job."},
    )


@router.post("/operator/vap-status")
async def api_operator_vap_status(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: start_vap_status_job(_text_from_body(data, "vap_root"), _text_from_body(data, "input_video"), _text_from_body(data, "output_root")),
        {"ok": False, "error": "Could not show VideoAutoPipeline worker status."},
    )


@router.post("/operator/vap-show-output-root")
async def api_operator_vap_show_output_root(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: vap_show_output_root(_text_from_body(data, "output_root")),
        {"ok": False, "error": "Could not show VideoAutoPipeline output root."},
    )


@router.post("/operator/videoautopipeline-batch")
async def api_operator_videoautopipeline_batch(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: start_videoautopipeline_batch_job(
            _text_from_body(data, "vap_root"),
            _text_from_body(data, "input_folder"),
            _text_from_body(data, "output_root"),
            data.get("limit"),
        ),
        {"ok": False, "error": "Could not start VideoAutoPipeline batch."},
    )


@router.post("/operator/process-videoautopipeline-outputs")
async def api_operator_process_videoautopipeline_outputs(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: start_process_videoautopipeline_outputs_job(
            _text_from_body(data, "output_root"),
            dry_run=_bool_from_body(data, "dry_run", True),
            auto_fix=_bool_from_body(data, "auto_fix", True),
            copy_results=_bool_from_body(data, "copy_results", True),
            send_telegram=_bool_from_body(data, "send_telegram", False),
        ),
        {"ok": False, "error": "Could not process VideoAutoPipeline outputs."},
    )


@router.post("/operator/process-waiting-for-plato")
async def api_operator_process_waiting_for_plato(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: start_process_waiting_for_plato_job(
            _text_from_body(data, "output_root"),
            dry_run=_bool_from_body(data, "dry_run", True),
            auto_fix=_bool_from_body(data, "auto_fix", True),
            copy_results=_bool_from_body(data, "copy_results", True),
        ),
        {"ok": False, "error": "Could not process waiting VideoAutoPipeline jobs."},
    )


@router.post("/operator/send-approved-to-telegram")
async def api_operator_send_approved_to_telegram(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: start_send_approved_to_telegram_job(_text_from_body(data, "output_root")),
        {"ok": False, "error": "Could not send approved clips to Telegram."},
    )


@router.post("/operator/full-videoautopipeline-flow")
async def api_operator_full_videoautopipeline_flow(request: Request):
    data = await _json_body(request)
    return _safe_payload(
        lambda: start_full_videoautopipeline_flow_job(
            _text_from_body(data, "vap_root"),
            _text_from_body(data, "output_root"),
            input_video=_text_from_body(data, "input_video"),
            input_folder=_text_from_body(data, "input_folder"),
            limit=data.get("limit"),
            dry_run=_bool_from_body(data, "dry_run", True),
            auto_fix=_bool_from_body(data, "auto_fix", True),
            copy_results=_bool_from_body(data, "copy_results", True),
            send_telegram=_bool_from_body(data, "send_telegram", False),
            davinci_mode=_text_from_body(data, "davinci_mode") or "required",
            cleanup_mode=_text_from_body(data, "cleanup_mode") or "keep_all",
        ),
        {"ok": False, "error": "Could not run full VideoAutoPipeline to Plato flow."},
    )


@router.post("/operator/full-pipeline-run")
async def api_operator_full_pipeline_run(request: Request):
    return await api_operator_full_videoautopipeline_flow(request)


@router.post("/operator/retry-full-pipeline")
async def api_operator_retry_full_pipeline(request: Request):
    data = await _json_body(request)
    return _safe_payload(lambda: start_retry_full_pipeline_job(data), {"ok": False, "error": "Could not retry full pipeline."})


@router.post("/operator/retry-plato-only")
async def api_operator_retry_plato_only(request: Request):
    data = await _json_body(request)
    return _safe_payload(lambda: start_retry_plato_only_job(data), {"ok": False, "error": "Could not retry Plato processing."})


@router.post("/operator/retry-delivery-only")
async def api_operator_retry_delivery_only(request: Request):
    data = await _json_body(request)
    return _safe_payload(lambda: start_retry_delivery_only_job(data), {"ok": False, "error": "Could not retry delivery."})


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
