from __future__ import annotations

from modules.auto_qc import recent_auto_qc_runs


def _clip_score(row: dict) -> float:
    try:
        return float(row.get("fixed_adjusted_score") or row.get("original_adjusted_score") or 0)
    except (TypeError, ValueError):
        return 0.0


def _risk(row: dict) -> int:
    return int(row.get("P0_after") or row.get("P0_before") or 0) * 100 + int(row.get("P1_after") or row.get("P1_before") or 0) * 25


def leaderboards(limit: int = 10) -> dict:
    clips = []
    for run in recent_auto_qc_runs(limit=100):
        for row in run.get("clips", []):
            item = dict(row)
            item["run_id"] = run.get("run_id")
            item["score"] = _clip_score(item)
            item["risk"] = _risk(item)
            item["fix_lift"] = float(item.get("delta_score") or 0) if item.get("delta_score") != "" else 0
            clips.append(item)
    return {
        "top_score": sorted(clips, key=lambda item: item["score"], reverse=True)[:limit],
        "highest_risk": sorted(clips, key=lambda item: item["risk"], reverse=True)[:limit],
        "best_fix_lift": sorted(clips, key=lambda item: item["fix_lift"], reverse=True)[:limit],
        "total_clips": len(clips),
    }
