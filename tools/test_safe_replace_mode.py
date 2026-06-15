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
    estimated = score if estimated is None else estimated
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


def report_stub(prefix, name, data, created_paths):
    report_id = f"{prefix}_{Path(name).stem}"
    reports_dir = project_path("data/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"{report_id}.json"
    html_path = reports_dir / f"{report_id}.html"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(f"<html><body>{name}</body></html>", encoding="utf-8")
    created_paths.extend([json_path, html_path])
    return {"id": report_id, "html_path": str(html_path), "report_json": json.dumps(data)}


def install_fakes(prefix, created_paths, probe_ok=True):
    original_analyze = auto_qc._analyze_source
    fixed_analyze = auto_qc._analyze_fixed
    executor = auto_qc.apply_auto_fix_plan
    probe = auto_qc.video_probe.probe_video
    original_reports = {
        "accept.mp4": make_report("accept.mp4", 50, "REWORK", [low_bitrate_point()], estimated=74),
        "reject.mp4": make_report("reject.mp4", 50, "REWORK", [low_bitrate_point()], estimated=74),
    }

    def fake_analyze_source(source, force):
        data = original_reports[source.name]
        return {"id": f"clip_{source.stem}", "fps": 30, "duration": 12}, report_stub(prefix, source.name, data, created_paths), data, False

    def fake_analyze_fixed(fixed_path):
        if fixed_path.name.startswith("accept"):
            data = make_report(fixed_path.name, 73, "SAFE TO TEST")
        else:
            data = make_report(fixed_path.name, 50, "REWORK")
        return {"id": f"clip_{fixed_path.stem}", "fps": 30, "duration": 12}, report_stub(prefix, fixed_path.name, data, created_paths), data

    def fake_executor(source, plan, output, options):
        Path(output).write_bytes(f"fixed bytes for {Path(source).name}".encode("utf-8"))
        return {"ok": True, "output_path": str(output), "strategies": ["re_export"], "input_unchanged": True}

    auto_qc._analyze_source = fake_analyze_source
    auto_qc._analyze_fixed = fake_analyze_fixed
    auto_qc.apply_auto_fix_plan = fake_executor
    auto_qc.video_probe.probe_video = lambda path: {"ok": probe_ok, "error": "" if probe_ok else "bad fixed file"}

    def restore():
        auto_qc._analyze_source = original_analyze
        auto_qc._analyze_fixed = fixed_analyze
        auto_qc.apply_auto_fix_plan = executor
        auto_qc.video_probe.probe_video = probe

    return restore


def make_root():
    root = project_path("data/temp") / f"safe_replace_{uuid.uuid4().hex[:8]}"
    source = root / "source"
    source.mkdir(parents=True, exist_ok=True)
    (source / "accept.mp4").write_bytes(b"accept original")
    (source / "reject.mp4").write_bytes(b"reject original")
    return root, source


def test_default_does_not_replace():
    root, source = make_root()
    created = []
    restore = install_fakes(root.name, created)
    try:
        result = auto_qc.run_auto_qc_fix(source, auto_fix=True, output_dir=root / "out", force=True)
        assert result["counts"]["accepted_fix_count"] == 1
        assert (source / "accept.mp4").read_bytes() == b"accept original"
        assert "replace_log_json" not in result["paths"]
    finally:
        restore()
        for path in created:
            path.unlink(missing_ok=True)
        shutil.rmtree(root, ignore_errors=True)


def test_replace_requires_confirmation():
    root, source = make_root()
    created = []
    restore = install_fakes(root.name, created)
    try:
        result = auto_qc.run_auto_qc_fix(
            source,
            auto_fix=True,
            output_dir=root / "out",
            force=True,
            replace_with_fixed=True,
        )
        assert (source / "accept.mp4").read_bytes() == b"accept original"
        log = json.loads(Path(result["paths"]["replace_log_json"]).read_text(encoding="utf-8"))
        assert log["replaced_count"] == 0
        assert any(item["reason"] == "--confirm-replace is required" for item in log["items"])
    finally:
        restore()
        for path in created:
            path.unlink(missing_ok=True)
        shutil.rmtree(root, ignore_errors=True)


def test_replace_backup_rejected_skip_and_rollback():
    root, source = make_root()
    created = []
    restore = install_fakes(root.name, created)
    try:
        result = auto_qc.run_auto_qc_fix(
            source,
            auto_fix=True,
            output_dir=root / "out",
            force=True,
            replace_with_fixed=True,
            confirm_replace=True,
            backup_dir=root / "backups",
        )
        accept = source / "accept.mp4"
        reject = source / "reject.mp4"
        assert accept.read_bytes() == b"fixed bytes for accept.mp4"
        assert reject.read_bytes() == b"reject original"

        log_path = Path(result["paths"]["replace_log_json"])
        log = json.loads(log_path.read_text(encoding="utf-8"))
        replaced = next(item for item in log["items"] if item["filename"] == "accept.mp4")
        skipped = next(item for item in log["items"] if item["filename"] == "reject.mp4")
        assert replaced["status"] == "replaced"
        assert Path(replaced["backup_path"]).read_bytes() == b"accept original"
        assert skipped["status"] == "skipped"
        assert skipped["reason"] == "fixed clip was not accepted"

        rollback = auto_qc.rollback_replace_log(log_path)
        assert rollback["ok"] is True
        assert rollback["restored_count"] == 1
        assert accept.read_bytes() == b"accept original"
        assert reject.read_bytes() == b"reject original"
    finally:
        restore()
        for path in created:
            path.unlink(missing_ok=True)
        shutil.rmtree(root, ignore_errors=True)


def test_ffprobe_failure_does_not_replace():
    root, source = make_root()
    created = []
    restore = install_fakes(root.name, created, probe_ok=False)
    try:
        result = auto_qc.run_auto_qc_fix(
            source,
            auto_fix=True,
            output_dir=root / "out",
            force=True,
            replace_with_fixed=True,
            confirm_replace=True,
        )
        assert (source / "accept.mp4").read_bytes() == b"accept original"
        log = json.loads(Path(result["paths"]["replace_log_json"]).read_text(encoding="utf-8"))
        accepted = next(item for item in log["items"] if item["filename"] == "accept.mp4")
        assert accepted["status"] == "skipped"
        assert "ffprobe failed" in accepted["reason"]
    finally:
        restore()
        for path in created:
            path.unlink(missing_ok=True)
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    test_default_does_not_replace()
    test_replace_requires_confirmation()
    test_replace_backup_rejected_skip_and_rollback()
    test_ffprobe_failure_does_not_replace()
    print("test_safe_replace_mode: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
