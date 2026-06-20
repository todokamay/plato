import os
from pathlib import Path

APP_NAME = "Plato Video Lab"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
VIDEOAUTOPIPELINE_ROOT = Path(os.environ.get("VIDEOAUTOPIPELINE_ROOT") or r"C:\Users\User\Desktop\Work\VideoAutoPipeline")
VIDEOAUTOPIPELINE_OUTPUT_ROOT = Path(
    os.environ.get("VIDEOAUTOPIPELINE_OUTPUT_ROOT") or VIDEOAUTOPIPELINE_ROOT / "data" / "output"
)
CLEANUP_MODE = os.environ.get("CLEANUP_MODE") or "keep_all"

UPLOAD_DIR = "data/uploads"
FRAMES_DIR = "data/frames"
REPORTS_DIR = "data/reports"
TEMP_DIR = "data/temp"
DB_PATH = "data/app.sqlite3"

MAX_UPLOAD_MB = 500

SUPPORTED_EXTENSIONS = [".mp4", ".mov", ".mkv", ".webm"]
MVP_TARGET = "generic_short_form"

SCORE_WEIGHTS = {
    "opening": 0.25,
    "retention": 0.25,
    "technical": 0.20,
    "audio": 0.15,
    "format": 0.15,
}

THRESHOLDS = {
    "vertical_aspect_target": 1.777,
    "min_video_bitrate_kbps": 2500,
    "preferred_video_bitrate_kbps": 3500,
    "very_low_video_bitrate_kbps": 1500,
    "black_brightness_threshold": 15,
    "static_frame_diff_threshold": 4.0,
    "sharpness_good": 150,
    "sharpness_ok": 80,
    "sharpness_bad": 30,
    "opening_seconds": 2.0,
    "ideal_min_duration": 20,
    "ideal_max_duration": 45,
    "max_short_duration": 60,
}


def project_path(relative_path: str | Path) -> Path:
    return BASE_DIR / relative_path


def ensure_data_dirs() -> None:
    for relative_path in [UPLOAD_DIR, FRAMES_DIR, REPORTS_DIR, TEMP_DIR]:
        project_path(relative_path).mkdir(parents=True, exist_ok=True)
