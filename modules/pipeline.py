import json
import shutil
import uuid
from pathlib import Path

from config import REPORTS_DIR, UPLOAD_DIR, ensure_data_dirs, project_path
from modules import db
from modules.audio_analyzer import analyze_audio
from modules.edit_point_generator import estimate_after_fixes, generate_edit_points
from modules.frame_sampler import create_contact_sheet, sample_frames
from modules.opening_analyzer import analyze_opening
from modules.recommendation_engine import build_recommendations
from modules.report_generator import generate_report_html, generate_report_json
from modules.retention_analyzer import analyze_retention
from modules.rhythm_analyzer import analyze_rhythm
from modules.score_consistency import apply_score_consistency, calculate_consistency_penalties
from modules.scoring import score_clip
from modules.video_probe import probe_video
from modules.visual_analyzer import analyze_visual_frames


def _empty_analyses(metadata: dict) -> dict:
    return {
        "metadata": metadata,
        "frames": [],
        "contact_sheet": "",
        "visual": {
            "frames": [],
            "black_ratio": 0,
            "static_ratio": 0,
            "avg_sharpness": 0,
            "avg_brightness": 0,
            "active_content": {
                "active_content_ratio": None,
                "active_width_ratio": None,
                "active_height_ratio": None,
                "black_border_ratio": None,
                "pillarbox_detected": False,
                "letterbox_detected": False,
                "small_center_content_detected": False,
                "confidence": "low",
                "issues": [],
                "frame_count": 0,
            },
            "low_motion_segments": [],
            "black_segments": [],
            "static_segments": [],
            "credits_like_segments": [],
            "issues": [],
        },
        "audio": {
            "has_audio": False,
            "mean_volume_db": None,
            "max_volume_db": None,
            "silence_ratio": None,
            "opening_silence": True,
            "silence_segments": [],
            "audio_drop_segments": [],
            "audio_energy_timeline": [],
            "audio_issues": [],
        },
        "opening": {
            "opening_score": 0,
            "opening_issues": [],
            "recommended_start_time": None,
            "opening_static": False,
            "opening_first_half_static": False,
            "opening_black": False,
            "opening_silence": True,
            "opening_motion_score": 0,
        },
        "retention": {"retention_score": 0, "drawdown_segments": []},
        "rhythm": {
            "scene_change_count": 0,
            "scene_changes": [],
            "scene_change_density_per_10s": 0,
            "dead_time_ratio": 0,
            "repeated_frame_ratio": 0,
            "longest_dead_segment": None,
            "average_motion_score": 0,
            "low_motion_segments": [],
            "black_segments": [],
            "visual_rhythm_score": 0,
            "segments": [],
        },
    }


def analyze_clip(clip_id: str) -> dict:
    ensure_data_dirs()
    db.init_db()
    clip = db.get_clip(clip_id)
    if not clip:
        raise ValueError(f"Clip not found: {clip_id}")

    db.update_clip_status(clip_id, "analyzing")
    clip = db.get_clip(clip_id)
    report_id = uuid.uuid4().hex

    try:
        metadata = probe_video(clip["file_path"])
        if metadata.get("ok"):
            db.update_clip_metadata(clip_id, metadata)
            clip = db.get_clip(clip_id)

            sampled = sample_frames(clip["file_path"], clip_id, metadata.get("duration") or 0)
            contact_sheet = create_contact_sheet(sampled)
            visual = analyze_visual_frames(sampled)
            audio = analyze_audio(clip["file_path"], metadata.get("has_audio"), metadata.get("duration"))
            opening = analyze_opening(visual, audio, metadata.get("duration") or 0)
            retention = analyze_retention(visual, audio, metadata.get("duration") or 0)
            rhythm = analyze_rhythm(visual, metadata.get("duration") or 0)
            analyses = {
                "metadata": metadata,
                "frames": sampled,
                "contact_sheet": contact_sheet,
                "visual": visual,
                "audio": audio,
                "opening": opening,
                "retention": retention,
                "rhythm": rhythm,
            }
            score_result = score_clip(metadata, visual, audio, opening, retention)
            final_status = "analyzed"
            error_message = None
        else:
            analyses = _empty_analyses(metadata)
            score_result = score_clip(metadata, analyses["visual"], analyses["audio"], analyses["opening"], analyses["retention"])
            final_status = "failed"
            error_message = metadata.get("error")

        recommendations = build_recommendations(clip, analyses, score_result)
        edit_points = generate_edit_points(clip, analyses, score_result, recommendations)
        consistency = calculate_consistency_penalties(score_result, analyses, edit_points)
        score_result = apply_score_consistency(score_result, consistency)
        recommendations = build_recommendations(clip, analyses, score_result)
        estimated_after_fixes = estimate_after_fixes(score_result, edit_points)
        recommendations["edit_points"] = edit_points
        recommendations["estimated_after_fixes"] = estimated_after_fixes
        report_json = generate_report_json(clip, analyses, score_result, recommendations, report_id)
        reports_dir = project_path(REPORTS_DIR)
        reports_dir.mkdir(parents=True, exist_ok=True)
        json_path = reports_dir / f"{report_id}.json"
        html_path = reports_dir / f"{report_id}.html"
        json_path.write_text(json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8")
        html_path.write_text(generate_report_html(report_json), encoding="utf-8")

        db.create_report(report_id, clip_id, score_result, report_json, str(html_path))
        db.insert_issues(clip_id, report_id, recommendations.get("weak_points", []))
        db.replace_frames(clip_id, analyses.get("visual", {}).get("frames", []))
        db.update_clip_status(clip_id, final_status, error_message)
        return {
            "clip_id": clip_id,
            "report_id": report_id,
            "report_json_path": str(json_path),
            "report_html_path": str(html_path),
            "score": score_result.get("investment_score"),
            "verdict": score_result.get("verdict"),
            "status": final_status,
        }
    except Exception as exc:
        db.update_clip_status(clip_id, "failed", str(exc))
        raise


def import_clip_file(source_path: str | Path) -> dict:
    ensure_data_dirs()
    db.init_db()
    source = Path(source_path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Video file not found: {source}")
    stored_name = f"{uuid.uuid4().hex}{source.suffix.lower()}"
    target = project_path(UPLOAD_DIR) / stored_name
    shutil.copy2(source, target)
    return db.create_clip(source.name, stored_name, str(target), target.stat().st_size)
