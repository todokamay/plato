import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules import auto_qc


def make_report(filename, score, verdict, duration, edit_points=None, estimated=None):
    if estimated is None:
        estimated = score
    return {
        "asset_overview": {"filename": filename, "duration": duration, "has_audio": True},
        "technical_quality": {
            "metadata": {"duration": duration, "has_audio": True, "video_bitrate_kbps": 900},
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
    prefix = f"short_auto_qc_{uuid.uuid4().hex[:8]}"
    source_dir = project_path("data/temp") / prefix
    output_dir = project_path("data/temp") / f"{prefix}_out"
    source = source_dir / "short_accept.mp4"
    created_reports = []
    original_analyze = auto_qc._analyze_source
    fixed_analyze = auto_qc._analyze_fixed
    executor = auto_qc.apply_auto_fix_plan

    try:
        source_dir.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"original short clip bytes")
        before = source.stat()

        original_report = make_report(
            "short_accept.mp4",
            50,
            "REWORK",
            6.5,
            [low_bitrate_point()],
            estimated=74,
        )
        fixed_report = make_report("short_accept_plato_fixed.mp4", 69, "SAFE TO TEST", 6.3)

        def fake_analyze_source(source_path, force):
            report = write_report_artifacts(prefix, source_path.name, original_report, created_reports)
            return {"id": f"clip_{source_path.stem}", "fps": 30, "duration": 6.5}, report, original_report, False

        def fake_analyze_fixed(fixed_path):
            report = write_report_artifacts(prefix, fixed_path.name, fixed_report, created_reports)
            return {"id": f"clip_{fixed_path.stem}", "fps": 30, "duration": 6.3}, report, fixed_report

        def fake_executor(source_path, plan, output_path, options):
            shutil.copy2(source_path, output_path)
            return {"ok": True, "output_path": str(output_path), "strategies": ["re_export"], "input_unchanged": True}

        auto_qc._analyze_source = fake_analyze_source
        auto_qc._analyze_fixed = fake_analyze_fixed
        auto_qc.apply_auto_fix_plan = fake_executor

        result = auto_qc.run_auto_qc_fix(
            source_dir,
            auto_fix=True,
            copy_results=True,
            output_dir=output_dir,
            force=True,
            allow_original_short=True,
            short_clip_min_duration=5.0,
        )

        assert result["counts"]["scanned_count"] == 1
        assert result["counts"]["accepted_fix_count"] == 1
        row = result["clips"][0]
        assert row["filename"] == "short_accept.mp4"
        assert row["fix_accepted"]
        assert row["duration_policy"] == "accepted"
        assert row["original_duration_sec"] == 6.5
        assert row["fixed_duration_sec"] == 6.3
        assert row["is_original_short"] is True
        assert row["min_duration_used"] == 5.0
        assert row["fix_acceptance_reason"]
        assert not row["fix_rejection_reason"]
        assert row["final_bucket"] == "fixed_safe_to_test"
        assert Path(row["fixed_path"]).exists()
        assert Path(row["final_output_path"]).exists()

        after = source.stat()
        assert before.st_size == after.st_size
        assert before.st_mtime_ns == after.st_mtime_ns
    finally:
        auto_qc._analyze_source = original_analyze
        auto_qc._analyze_fixed = fixed_analyze
        auto_qc.apply_auto_fix_plan = executor
        for path in created_reports:
            path.unlink(missing_ok=True)
        for path in [source_dir, output_dir]:
            if path.exists():
                shutil.rmtree(path)

    print("test_auto_fix_acceptance_short_clips: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
