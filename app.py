import json
import shutil
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import (
    APP_NAME,
    MAX_UPLOAD_MB,
    MVP_TARGET,
    SUPPORTED_EXTENSIONS,
    UPLOAD_DIR,
    ensure_data_dirs,
    project_path,
)
from modules import db
from modules.auto_qc import recent_auto_qc_runs
from modules.batch_qc import recent_batches
from modules.history_engine import history_summary
from modules.log_center import recent_logs
from modules.orchestrator import orchestrator_status
from modules.operator_actions import operator_status as operator_wizard_status
from modules.pipeline import analyze_clip
from modules.queue_engine import queue_stats
from modules.replace_diagnostics import replace_diagnostics
from modules.report_center import report_payload
from modules.videoautopipeline_detector import detect_videoautopipeline_outputs
from modules.video_probe import probe_video
from modules.watch_folder import DEFAULT_STATE_FILE, load_state
from routes.api import router as api_router

ensure_data_dirs()
db.init_db()

app = FastAPI(title=APP_NAME)
app.include_router(api_router)
templates = Jinja2Templates(directory=str(project_path("templates")))

static_dir = project_path("static")
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.mount("/uploads", StaticFiles(directory=str(project_path(UPLOAD_DIR))), name="uploads")


def verdict_class(verdict: str | None) -> str:
    verdict = verdict or "REJECT"
    if "PUBLISH" in verdict:
        return "good"
    if verdict == "SAFE TO TEST":
        return "info"
    if verdict == "REWORK":
        return "warn"
    if "HOLD" in verdict:
        return "hold"
    return "bad"


def format_seconds(value) -> str:
    if value is None:
        return "-"
    value = float(value)
    minutes = int(value // 60)
    seconds = value - minutes * 60
    if minutes:
        return f"{minutes}:{seconds:04.1f}"
    return f"{seconds:.1f}s"


def format_bytes(value) -> str:
    if value is None:
        return "-"
    value = float(value)
    for unit in ["B", "KB", "MB", "GB"]:
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


templates.env.filters["verdict_class"] = verdict_class
templates.env.filters["seconds"] = format_seconds
templates.env.filters["bytes"] = format_bytes


def _safe_filename(filename: str) -> str:
    name = Path(filename or "clip").name
    keep = [char if char.isalnum() or char in "._- " else "_" for char in name]
    cleaned = "".join(keep).strip(" .")
    return cleaned or "clip.mp4"


def _clip_or_404(clip_id: str) -> dict:
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    return clip


@app.get("/")
def dashboard(request: Request):
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "Dashboard",
            "stats": db.dashboard_stats(),
        },
    )


@app.get("/dashboard")
def dashboard_alias(request: Request):
    return dashboard(request)


@app.get("/upload")
def upload_page(request: Request):
    return templates.TemplateResponse(
        "upload.html",
        {
            "request": request,
            "title": "Upload",
            "target": MVP_TARGET,
            "extensions": ", ".join(SUPPORTED_EXTENSIONS),
            "max_upload_mb": MAX_UPLOAD_MB,
            "error": None,
        },
    )


@app.get("/batch-qc")
def batch_qc_page(request: Request):
    batches = recent_batches()
    latest = batches[0] if batches else None
    pending = 0
    if latest:
        pending = sum(1 for clip in latest.get("clips", []) if clip.get("needs_reanalysis"))
    return templates.TemplateResponse(
        "batch_qc.html",
        {
            "request": request,
            "title": "Batch QC",
            "latest": latest,
            "batches": batches,
            "pending_reanalysis_count": pending,
        },
    )


@app.get("/auto-qc")
def auto_qc_page(request: Request):
    runs = recent_auto_qc_runs()
    latest = runs[0] if runs else None
    return templates.TemplateResponse(
        "auto_qc.html",
        {
            "request": request,
            "title": "Auto QC",
            "latest": latest,
            "runs": runs,
        },
    )


@app.get("/control-center")
def control_center_page(request: Request):
    runs = recent_auto_qc_runs()
    return templates.TemplateResponse(
        "control_center.html",
        {
            "request": request,
            "title": "Control Center",
            "status": orchestrator_status(),
            "queue": queue_stats(),
            "report": report_payload("all-time"),
            "history": history_summary(),
            "logs": recent_logs(limit=20),
            "watch_state": load_state(DEFAULT_STATE_FILE),
            "detector": detect_videoautopipeline_outputs(),
            "latest_run": runs[0] if runs else None,
            "replace": replace_diagnostics(),
        },
    )


@app.get("/operator")
def operator_page(request: Request):
    return templates.TemplateResponse(
        "operator_wizard.html",
        {
            "request": request,
            "title": "Operator",
            "operator": operator_wizard_status(),
        },
    )


@app.post("/upload")
async def upload_clips(
    request: Request,
    files: list[UploadFile] = File(...),
    target_platform: str = Form(MVP_TARGET),
):
    created = []
    upload_dir = project_path(UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = MAX_UPLOAD_MB * 1024 * 1024

    for upload in files:
        original = _safe_filename(upload.filename or "clip.mp4")
        extension = Path(original).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            return templates.TemplateResponse(
                "upload.html",
                {
                    "request": request,
                    "title": "Upload",
                    "target": target_platform,
                    "extensions": ", ".join(SUPPORTED_EXTENSIONS),
                    "max_upload_mb": MAX_UPLOAD_MB,
                    "error": f"Unsupported file extension: {extension}",
                },
                status_code=400,
            )

        stored_filename = f"{uuid.uuid4().hex}{extension}"
        target_path = upload_dir / stored_filename
        size = 0
        with target_path.open("wb") as output:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    output.close()
                    target_path.unlink(missing_ok=True)
                    return templates.TemplateResponse(
                        "upload.html",
                        {
                            "request": request,
                            "title": "Upload",
                            "target": target_platform,
                            "extensions": ", ".join(SUPPORTED_EXTENSIONS),
                            "max_upload_mb": MAX_UPLOAD_MB,
                            "error": f"File exceeds {MAX_UPLOAD_MB} MB: {original}",
                        },
                        status_code=400,
                    )
                output.write(chunk)

        clip = db.create_clip(original, stored_filename, str(target_path), size)
        metadata = probe_video(str(target_path))
        if metadata.get("ok"):
            db.update_clip_metadata(clip["id"], metadata)
        else:
            db.update_clip_status(clip["id"], "uploaded", metadata.get("error"))
        created.append(db.get_clip(clip["id"]))

    if len(created) == 1:
        return RedirectResponse(f"/clips/{created[0]['id']}", status_code=303)
    return RedirectResponse("/clips", status_code=303)


@app.get("/clips")
def clips_page(request: Request):
    return templates.TemplateResponse(
        "clips.html",
        {
            "request": request,
            "title": "Clips",
            "clips": db.list_clips(),
        },
    )


@app.get("/clips/{clip_id}")
def clip_detail(request: Request, clip_id: str):
    clip = _clip_or_404(clip_id)
    report = db.get_latest_report_for_clip(clip_id)
    issues = db.get_issues_for_report(report["id"]) if report else []
    report_data = json.loads(report["report_json"]) if report else None
    return templates.TemplateResponse(
        "clip_detail.html",
        {
            "request": request,
            "title": clip.get("original_filename") or "Clip",
            "clip": clip,
            "report": report,
            "report_data": report_data,
            "issues": issues,
        },
    )


@app.post("/clips/{clip_id}/analyze")
def analyze_clip_route(clip_id: str):
    _clip_or_404(clip_id)
    analyze_clip(clip_id)
    return RedirectResponse(f"/clips/{clip_id}", status_code=303)


@app.post("/clips/{clip_id}/reanalyze")
def reanalyze_clip_route(clip_id: str):
    _clip_or_404(clip_id)
    analyze_clip(clip_id)
    return RedirectResponse(f"/clips/{clip_id}", status_code=303)


@app.get("/reports/{report_id}")
def report_page(request: Request, report_id: str):
    report = db.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    clip = db.get_clip(report["clip_id"])
    report_json = json.loads(report["report_json"])
    return templates.TemplateResponse(
        "report.html",
        {
            "request": request,
            "title": "Report",
            "report": report,
            "clip": clip,
            "data": report_json,
        },
    )


@app.get("/reports/{report_id}/json")
def report_json(report_id: str):
    report = db.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return JSONResponse(json.loads(report["report_json"]))


@app.get("/health")
def health():
    return {"ok": True, "app": APP_NAME}


if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
