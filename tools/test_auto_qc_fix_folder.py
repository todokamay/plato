import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules import auto_qc


def make_report(filename, score, verdict, edit_points=None, estimated=None):
    if estimated is None:
        estimated = score
    return {
        "asset_overview": {"filename": filename, "duration": 12.0, "has_audio": True},
        "technical_quality": {
            "metadata": {"duration": 12.0, "has_audio": True, "video_bitrate_kbps": 900},
            "issues": [],
            "visual_metrics": {"black_ratio": 0, "static_ratio": 0},
        },
        "audio_quality": {"has_audio": True, "mean_volume_db": -18, "max_volume_db": -3},
        "scoring": {
            "raw_score": score,
            "adjusted_score": score,
            "total_consistency_penalty": 0,
            "raw_verdict": verdict,
            "cap_final_verdict": verdict,
            "adjusted_score_verdict": verdict,
            "final_verdict": verdict,
            "verdict_source": "tie",
            "score_verdict_alignment": "aligned",
        },
        "investment_score": score,
        "final_verdict": verdict,
        "verdict": verdict,
        "edit_points": edit_points or [],
        "estimated_after_fixes": {"estimated_after_p0": estimated, "estimated_after_p0_p1": estimated},
        "weak_points": [],
    }


def low_bitrate_point():
    return {
        "id": "edit_low_bitrate",
        "priority": "P1",
        "issue_type": "low_bitrate",
        "action": "re_export",
        "confidence": "high",
        "expected_lift": {"investment": 18},
        "recommended_edit": "Re-export at a higher bitrate.",
    }


def write_report_artifacts(prefix, name, data, created_paths):
    report_id = f"{prefix}_{Path(name).stem}"
    reports_dir = project_path("data/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    html = reports_dir / f"{report_id}.html"
    json_path = reports_dir / f"{report_id}.json"
    html.write_text(f"<html><body>{name}</body></html>", encoding="utf-8")
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    created_paths.extend([html, json_path])
    return {"id": report_id, "html_path": str(html), "report_json": json.dumps(data)}


def main() -> int:
    prefix = f"auto_qc_{uuid.uuid4().hex[:8]}"
    source_dir = project_path("data/temp") / prefix
    output_dir = project_path("data/temp") / f"{prefix}_out"
    dry_output = project_path("data/temp") / f"{prefix}_dry"
    created_reports = []
    original_analyze = auto_qc._analyze_source
    fixed_analyze = auto_qc._analyze_fixed
    executor = auto_qc.apply_auto_fix_plan

    try:
        source_dir.mkdir(parents=True, exist_ok=True)
        sources = {
            "accept.mp4": b"accept original",
            "fail.mp4": b"fail original",
            "reject.mp4": b"reject original",
        }
        before = {}
        for name, data in sources.items():
            path = source_dir / name
            path.write_bytes(data)
            before[name] = path.stat()

        original_reports = {
            "accept.mp4": make_report("accept.mp4", 50, "REWORK", [low_bitrate_point()], estimated=74),
            "fail.mp4": make_report("fail.mp4", 50, "REWORK", [low_bitrate_point()], estimated=74),
            "reject.mp4": make_report("reject.mp4", 20, "REJECT"),
        }
        fixed_report = make_report("accept_plato_fixed.mp4", 73, "SAFE TO TEST")

        def fake_analyze_source(source, force):
            data = original_reports[source.name]
            report = write_report_artifacts(prefix, source.name, data, created_reports)
            return {"id": f"clip_{source.stem}", "fps": 30, "duration": 12}, report, data, False

        def fake_analyze_fixed(fixed_path):
            report = write_report_artifacts(prefix, fixed_path.name, fixed_report, created_reports)
            return {"id": f"clip_{fixed_path.stem}", "fps": 30, "duration": 12}, report, fixed_report

        def fake_executor(source, plan, output, options):
            if "fail" in Path(source).name:
                return {"ok": False, "error": "simulated ffmpeg failure", "strategies": ["re_export"], "input_unchanged": True}
            shutil.copy2(source, output)
            return {"ok": True, "output_path": str(output), "strategies": ["re_export"], "input_unchanged": True}

        auto_qc._analyze_source = fake_analyze_source
        auto_qc._analyze_fixed = fake_analyze_fixed
        auto_qc.apply_auto_fix_plan = fake_executor

        dry = auto_qc.run_auto_qc_fix(source_dir, dry_run=True, output_dir=dry_output)
        assert dry["counts"]["scanned_count"] == 3
        assert dry["counts"]["analyzed_count"] == 0
        assert dry["paths"] == {}
        assert not dry_output.exists()

        result = auto_qc.run_auto_qc_fix(source_dir, auto_fix=True, copy_results=True, output_dir=output_dir, force=True)
        assert result["counts"]["scanned_count"] == 3
        assert result["counts"]["auto_fix_attempted_count"] == 2
        assert result["counts"]["accepted_fix_count"] == 1
        assert result["counts"]["failed_fix_count"] == 1
        assert result["counts"]["rejected_count"] == 1
        assert Path(result["paths"]["run_summary_csv"]).exists()
        assert Path(result["paths"]["run_summary_json"]).exists()
        assert Path(result["paths"]["run_report_html"]).exists()
        assert Path(result["paths"]["run_fix_plan_csv"]).exists()
        assert Path(result["paths"]["run_fix_plan_json"]).exists()

        accept_row = next(row for row in result["clips"] if row["filename"] == "accept.mp4")
        fail_row = next(row for row in result["clips"] if row["filename"] == "fail.mp4")
        reject_row = next(row for row in result["clips"] if row["filename"] == "reject.mp4")
        assert accept_row["fix_accepted"]
        assert Path(accept_row["fixed_path"]).exists()
        assert accept_row["final_bucket"] == "fixed_safe_to_test"
        assert Path(accept_row["final_output_path"]).exists()
        assert fail_row["final_bucket"] == "failed_fix"
        assert Path(fail_row["final_output_path"]).exists()
        assert reject_row["final_bucket"] == "rejected"
        assert Path(reject_row["final_output_path"]).exists()

        for name in sources:
            path = source_dir / name
            after = path.stat()
            assert before[name].st_size == after.st_size
            assert before[name].st_mtime_ns == after.st_mtime_ns
    finally:
        auto_qc._analyze_source = original_analyze
        auto_qc._analyze_fixed = fixed_analyze
        auto_qc.apply_auto_fix_plan = executor
        for path in created_reports:
            path.unlink(missing_ok=True)
        for path in [source_dir, output_dir, dry_output]:
            if path.exists():
                shutil.rmtree(path)

    print("test_auto_qc_fix_folder: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
