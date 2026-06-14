import csv
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules.davinci_export import export_davinci_files, marker_rows_for_clip


def _entry() -> dict:
    return {
        "filename": "sample.mp4",
        "file_path": "C:/clips/sample.mp4",
        "clip_id": "clip1",
        "portfolio_bucket": "Quick Fix",
        "final_verdict": "REWORK",
        "adjusted_score": 62,
        "fps": 30,
        "html_report_path": "C:/reports/sample.html",
        "edit_points": [
            {
                "priority": "P1",
                "start_time": 0.5,
                "end_time": 1.0,
                "issue_type": "low_visual_change_opening",
                "action": "cut",
                "recommended_edit": "Cut the first beat.",
                "expected_lift": {"investment": 3},
                "confidence": "high",
                "detected_by": ["opening_analyzer"],
            },
            {
                "priority": "P3",
                "start_time": 2.0,
                "issue_type": "minor_note",
                "action": "review",
                "recommended_edit": "Optional.",
                "expected_lift": {"investment": 0},
            },
        ],
    }


def main() -> int:
    out = project_path("data/temp") / f"davinci_export_{uuid.uuid4().hex}"
    try:
        entry = _entry()
        marker_rows = marker_rows_for_clip(entry)
        assert len(marker_rows) == 1
        assert marker_rows[0]["timecode"] == "00:00:00:15"
        assert marker_rows[0]["color"] == "Orange"

        paths = export_davinci_files([entry], out)
        assert Path(paths["fix_plan_csv"]).exists()
        assert Path(paths["fix_plan_json"]).exists()
        assert entry["davinci_marker_path"]
        assert Path(entry["davinci_marker_path"]).exists()

        with Path(paths["fix_plan_csv"]).open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 1
        assert rows[0]["priority"] == "P1"
        assert rows[0]["start_timecode"] == "00:00:00:15"
    finally:
        if out.exists():
            shutil.rmtree(out)
    print("test_davinci_export: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
