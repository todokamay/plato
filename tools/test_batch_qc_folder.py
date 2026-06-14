import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules import db
from modules.batch_qc import run_batch_qc
from tools.test_helpers import create_test_video


def _cleanup_db(prefix: str) -> None:
    with db.get_connection() as conn:
        rows = conn.execute("SELECT id FROM clips WHERE original_filename LIKE ?", (f"{prefix}%",)).fetchall()
        for row in rows:
            conn.execute("DELETE FROM clips WHERE id = ?", (row["id"],))


def main() -> int:
    db.init_db()
    prefix = f"batch_qc_{uuid.uuid4().hex[:8]}"
    source_dir = project_path("data/temp") / prefix
    output_dir = project_path("data/temp") / f"{prefix}_out"
    output_dir2 = project_path("data/temp") / f"{prefix}_out2"
    output_dir3 = project_path("data/temp") / f"{prefix}_out3"
    try:
        source = create_test_video(source_dir / f"{prefix}_clip.mp4", duration=1.2, audio=True, size="360x640")

        dry = run_batch_qc(source_dir, dry_run=True)
        assert dry["counts"]["scanned_count"] == 1
        assert dry["counts"]["analyzed_count"] == 0
        assert not dry["paths"]

        first = run_batch_qc(source_dir, output_dir=output_dir, copy_results=True)
        assert first["counts"]["scanned_count"] == 1
        assert first["counts"]["analyzed_count"] == 1
        assert Path(first["paths"]["batch_summary_csv"]).exists()
        assert Path(first["paths"]["batch_summary_json"]).exists()
        assert Path(first["paths"]["batch_report_html"]).exists()
        assert Path(first["paths"]["fix_plan_csv"]).exists()
        assert first["clips"][0]["copied_path"]
        assert Path(first["clips"][0]["copied_path"]).exists()

        second = run_batch_qc(source_dir, output_dir=output_dir2)
        assert second["counts"]["skipped_count"] == 1
        assert second["counts"]["analyzed_count"] == 0

        forced = run_batch_qc(source_dir, output_dir=output_dir3, force=True)
        assert forced["counts"]["analyzed_count"] == 1
        assert forced["clips"][0]["report_id"]
        assert source.exists()
    finally:
        _cleanup_db(prefix)
        for path in [source_dir, output_dir, output_dir2, output_dir3]:
            if path.exists():
                shutil.rmtree(path)
    print("test_batch_qc_folder: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
