from __future__ import annotations

from config import THRESHOLDS
from modules.verdict_resolver import publishability_rank, resolve_final_verdict, verdict_rank


def _as_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _slug(value: str | None) -> str:
    return (value or "unknown").lower().replace(" / ", "_").replace(" ", "_")


def _cap_reasons(score_result: dict) -> list[str]:
    cap = score_result.get("verdict_cap") or {}
    return list(cap.get("cap_reasons") or [])


def _metadata(analyses: dict) -> dict:
    return analyses.get("metadata") or {}


def _active_content(analyses: dict) -> dict:
    return (analyses.get("visual") or {}).get("active_content") or {}


def _opening(analyses: dict) -> dict:
    return analyses.get("opening") or {}


def _add_penalty(
    penalties: dict[str, dict],
    code: str,
    label: str,
    amount: float,
    reason: str,
    related_cap_reason: str | None = None,
    related_edit_point: dict | None = None,
) -> None:
    amount = round(max(0.0, float(amount)), 1)
    if amount <= 0:
        return

    item = penalties.get(code)
    if not item:
        item = {
            "code": code,
            "label": label,
            "amount": amount,
            "reason": reason,
            "related_cap_reasons": [],
            "related_edit_point_ids": [],
        }
        penalties[code] = item
    elif amount > item["amount"]:
        item["amount"] = amount
        item["label"] = label
        item["reason"] = reason

    if related_cap_reason and related_cap_reason not in item["related_cap_reasons"]:
        item["related_cap_reasons"].append(related_cap_reason)
    if related_edit_point and related_edit_point.get("id"):
        point_id = related_edit_point["id"]
        if point_id not in item["related_edit_point_ids"]:
            item["related_edit_point_ids"].append(point_id)


def _finish_penalties(penalties: dict[str, dict]) -> list[dict]:
    finished = []
    for item in penalties.values():
        output = dict(item)
        output["related_cap_reason"] = output["related_cap_reasons"][0] if output["related_cap_reasons"] else None
        output["related_edit_point_id"] = output["related_edit_point_ids"][0] if output["related_edit_point_ids"] else None
        finished.append(output)
    return sorted(finished, key=lambda item: (-item["amount"], item["code"]))


def _cap_penalty_items(penalty_items: list[dict], raw_score: float) -> tuple[list[dict], float, bool]:
    uncapped_total = round(sum(float(item["amount"]) for item in penalty_items), 1)
    capped_total = round(max(0.0, float(raw_score)), 1)
    if uncapped_total <= capped_total:
        return penalty_items, uncapped_total, False

    if not penalty_items:
        return penalty_items, 0.0, False

    # When penalties exceed the raw score, scale individual amounts
    # proportionally so the visible line items still sum to the reported total.
    ratio = capped_total / uncapped_total if uncapped_total else 0.0
    scaled = []
    running_total = 0.0
    for item in penalty_items[:-1]:
        updated = dict(item)
        updated["uncapped_amount"] = item["amount"]
        updated["amount"] = round(float(item["amount"]) * ratio, 1)
        running_total = round(running_total + updated["amount"], 1)
        scaled.append(updated)

    last = dict(penalty_items[-1])
    last["uncapped_amount"] = last["amount"]
    last["amount"] = round(max(0.0, capped_total - running_total), 1)
    last["note"] = (
        "Total penalty capped at raw score; individual amounts scaled "
        f"proportionally from an uncapped total of {uncapped_total}."
    )
    scaled.append(last)
    return scaled, capped_total, True


def _bitrate_penalty(bitrate: float | None) -> float:
    if bitrate is None:
        return 2.0
    bitrate = float(bitrate)
    if bitrate < THRESHOLDS["very_low_video_bitrate_kbps"]:
        return 12.0
    if bitrate < 2500:
        return 5.5
    if bitrate < 3500:
        return 2.5
    return 0.0


def _active_content_penalty(ratio: float | None) -> float:
    if ratio is None:
        return 0.0
    ratio = float(ratio)
    if ratio < 0.40:
        return 14.0
    if ratio < 0.55:
        return 8.0
    if ratio < 0.70:
        return 4.0
    return 0.0


def _edit_penalty(point: dict) -> tuple[str, str, float, str] | None:
    issue_type = point.get("issue_type") or ""
    priority = point.get("priority") or "P3"

    if issue_type in {"low_bitrate", "very_low_bitrate"}:
        amount = 5.5 if issue_type == "low_bitrate" else 12.0
        return "low_bitrate_cap", "Low bitrate", amount, "Technical bitrate blocks a clean publish recommendation."
    if issue_type == "low_visual_change_opening":
        return "weak_opening_cap", "Weak first half-second", 2.5, "The opening does not create enough immediate visual change."
    if issue_type == "weak_opening":
        return "weak_opening_cap", "Weak opening", 4.0, "The first seconds are not strong enough for the raw score."
    if issue_type in {"opening_black", "opening_silence"}:
        amount = 9.0 if issue_type == "opening_black" else 5.0
        return "weak_opening_cap", "Opening blocker", amount, "The opening has a visible or audible blocker."
    if issue_type in {"low_active_content_area", "pillarbox_detected", "letterbox_detected", "small_center_content"}:
        return "active_content_cap", "Composition blocker", 6.0, "The mobile frame is not filled strongly enough."
    if issue_type in {"black_segment", "static_segment", "dead_time_segment", "repeated_frame_segment", "low_motion_segment", "static_ending"}:
        if issue_type == "black_segment":
            return "critical_visual_blocker", "Black-frame blocker", 14.0, "Black frames create a major retention and quality risk."
        if priority == "P0":
            return "visual_rhythm_blocker", "High priority visual rhythm issue", 7.0, "A high priority visual rhythm edit is needed."
        return "visual_rhythm_issue", "Dead time / static section", 1.0, "A deterministic P1 rhythm issue should slightly reduce the visible score."
    if issue_type in {"no_audio", "audio_too_quiet", "opening_silence", "silence_segment", "possible_clipping"}:
        if issue_type == "no_audio":
            return "audio_blocker", "No audio", 10.0, "Missing audio is a major publishing risk."
        if priority in {"P0", "P1"}:
            return "audio_issue", "Audio issue", 3.0, "Audio quality issue should be visible in the adjusted score."
    if issue_type in {"horizontal_source", "duration_too_long"}:
        return "format_blocker", "Format/source blocker", 8.0, "The asset behaves like source footage rather than a final short."

    if priority == "P0":
        return f"p0_{issue_type or 'edit_point'}", "P0 edit point", 7.0, "A P0 edit point blocks confident publishing."
    if priority == "P1":
        return f"p1_{issue_type or 'edit_point'}", "P1 edit point", 2.0, "A P1 edit point should be reflected in the adjusted score."
    return None


def _add_cap_penalties(penalties: dict[str, dict], score_result: dict, analyses: dict) -> None:
    metadata = _metadata(analyses)
    active = _active_content(analyses)
    opening = _opening(analyses)
    bitrate = metadata.get("video_bitrate_kbps")
    active_ratio = active.get("active_content_ratio")

    for reason in _cap_reasons(score_result):
        lower = reason.lower()
        if "bitrate" in lower:
            amount = _bitrate_penalty(bitrate)
            _add_penalty(
                penalties,
                "low_bitrate_cap",
                "Low bitrate",
                amount,
                "Video bitrate is below the publishing-quality floor.",
                related_cap_reason=reason,
            )
        elif "first half-second" in lower:
            _add_penalty(
                penalties,
                "weak_opening_cap",
                "Weak first half-second",
                2.5,
                "The opening has low visual change in the first half-second.",
                related_cap_reason=reason,
            )
        elif "first two seconds" in lower or "opening score" in lower:
            amount = 8.0 if opening.get("opening_static") else 5.0
            _add_penalty(
                penalties,
                "weak_opening_cap",
                "Weak opening",
                amount,
                "The opening is not strong enough for the raw score.",
                related_cap_reason=reason,
            )
        elif "opening is black" in lower or "too dark" in lower:
            _add_penalty(
                penalties,
                "weak_opening_cap",
                "Opening visual blocker",
                10.0,
                "The opening is black or too dark.",
                related_cap_reason=reason,
            )
        elif "active content" in lower:
            _add_penalty(
                penalties,
                "active_content_cap",
                "Composition blocker",
                _active_content_penalty(active_ratio),
                "Active content does not fill enough of the vertical frame.",
                related_cap_reason=reason,
            )
        elif "horizontal" in lower or "duration" in lower or "source footage" in lower:
            _add_penalty(
                penalties,
                "format_blocker",
                "Format/source blocker",
                8.0,
                "The asset is capped because it behaves like source material or misses short-form format needs.",
                related_cap_reason=reason,
            )
        elif "critical" in lower or "black" in lower or "static-video" in lower or "unreadable" in lower:
            _add_penalty(
                penalties,
                "critical_visual_blocker",
                "Critical visual blocker",
                55.0,
                "A critical unreadable, black, or static-video issue must dominate the adjusted score.",
                related_cap_reason=reason,
            )
        elif "high severity" in lower:
            _add_penalty(
                penalties,
                "high_severity_blocker",
                "High severity blocker",
                4.0,
                "High severity issues block a confident publish recommendation.",
                related_cap_reason=reason,
            )
        elif "retention score" in lower:
            _add_penalty(
                penalties,
                "retention_cap",
                "Retention cap",
                4.0,
                "Low retention score should be visible in the adjusted score.",
                related_cap_reason=reason,
            )


def _add_edit_point_penalties(penalties: dict[str, dict], edit_points: list[dict]) -> None:
    extra_p1_codes = set()
    for point in edit_points:
        result = _edit_penalty(point)
        if not result:
            continue
        code, label, amount, reason = result

        # Cap-driven P1 points should merge with their cap penalty. Extra P1 issues
        # get a small adjustment, capped by root cause to avoid noisy overstacking.
        if point.get("priority") == "P1" and code not in {"low_bitrate_cap", "weak_opening_cap", "active_content_cap"}:
            if code in extra_p1_codes:
                continue
            extra_p1_codes.add(code)
            amount = min(amount, 2.0)

        _add_penalty(
            penalties,
            code,
            label,
            amount,
            reason,
            related_edit_point=point,
        )


def _verdict_band_alignment(final_verdict: str, raw_score: float, adjusted_score: float, cap_reasons: list[str]) -> str:
    final_verdict = final_verdict or ""
    adjusted_score = float(adjusted_score)
    raw_score = float(raw_score)

    if final_verdict == "STRONG PUBLISH":
        if adjusted_score >= 90:
            return "aligned"
        return "minor_gap" if adjusted_score >= 86 else "major_gap"
    if final_verdict == "PUBLISH":
        if 80 <= adjusted_score < 90:
            return "aligned"
        if 76 <= adjusted_score < 92:
            return "minor_gap"
        return "major_gap"
    if final_verdict == "SAFE TO TEST":
        if 68 <= adjusted_score < 80:
            return "aligned"
        if adjusted_score < 68:
            return "minor_gap"
        return "major_gap"
    if final_verdict == "REWORK":
        if 50 <= adjusted_score < 68:
            return "aligned"
        if adjusted_score < 50:
            return "minor_gap"
        return "major_gap"
    if final_verdict in {"HOLD", "HOLD / CLIP FIRST"}:
        if adjusted_score < 50:
            return "aligned"
        if raw_score < 70 or cap_reasons:
            return "minor_gap"
        return "major_gap"
    if final_verdict == "REJECT":
        if adjusted_score < 35:
            return "aligned"
        if cap_reasons and adjusted_score < 50:
            return "minor_gap"
        return "major_gap"
    return "aligned"


def _alignment_status(resolution: dict, raw_score: float, adjusted_score: float, cap_reasons: list[str]) -> str:
    if resolution.get("verdict_source") == "cap":
        return "cap_limited"
    return _verdict_band_alignment(resolution.get("final_verdict"), raw_score, adjusted_score, cap_reasons)


def _consistency_flags(
    raw_score: float,
    adjusted_score: float,
    raw_verdict: str,
    cap_final_verdict: str,
    adjusted_score_verdict: str,
    final_verdict: str,
    alignment: str,
    cap_reasons: list[str],
    total_penalty: float,
) -> list[str]:
    flags = []
    if alignment == "major_gap":
        flags.append("Adjusted score still does not match the final verdict band.")
    if alignment == "cap_limited" and not cap_reasons:
        flags.append("Final verdict is cap-limited but no cap reasons are recorded.")
    if raw_score >= 85 and final_verdict == "SAFE TO TEST" and adjusted_score >= 80:
        flags.append("High raw score remains publish-band after SAFE TO TEST cap.")
    if raw_score >= 80 and final_verdict == "REWORK" and adjusted_score >= 68:
        flags.append("Adjusted score remains SAFE/PUBLISH-band after REWORK cap.")
    if raw_score >= 70 and final_verdict in {"HOLD", "HOLD / CLIP FIRST", "REJECT"} and adjusted_score >= 50:
        flags.append("Adjusted score remains high for a HOLD/REJECT final verdict.")
    if cap_reasons and total_penalty < 2:
        flags.append("Verdict cap exists but score adjustment is too small to explain it.")
    drop = publishability_rank(raw_verdict) - publishability_rank(final_verdict)
    if drop >= 2 and alignment not in {"aligned", "cap_limited"}:
        flags.append("Final verdict is two or more tiers below raw verdict.")
    if final_verdict != adjusted_score_verdict and verdict_rank(final_verdict) < verdict_rank(adjusted_score_verdict):
        flags.append("Final verdict is less conservative than the adjusted-score verdict.")
    if final_verdict != cap_final_verdict and verdict_rank(final_verdict) < verdict_rank(cap_final_verdict):
        flags.append("Final verdict is less conservative than the cap verdict.")
    return flags


def calculate_consistency_penalties(score_result: dict, analyses: dict, edit_points: list[dict]) -> dict:
    raw_score = _as_float(score_result.get("raw_investment_score", score_result.get("investment_score")))
    raw_verdict = score_result.get("raw_verdict") or score_result.get("verdict")
    cap_result = score_result.get("verdict_cap") or {}
    cap_final_verdict = score_result.get("cap_final_verdict") or cap_result.get("final_verdict") or score_result.get("verdict") or raw_verdict
    cap_reasons = _cap_reasons(score_result)
    penalties: dict[str, dict] = {}

    _add_cap_penalties(penalties, score_result, analyses)
    _add_edit_point_penalties(penalties, edit_points or [])

    penalty_items = _finish_penalties(penalties)
    penalty_items, total_penalty, penalty_capped = _cap_penalty_items(penalty_items, raw_score)
    adjusted_score = round(max(0.0, raw_score - total_penalty), 1)
    resolution = resolve_final_verdict(raw_verdict, cap_final_verdict, adjusted_score, cap_reasons, penalty_items)
    final_verdict = resolution["final_verdict"]
    alignment = _alignment_status(resolution, raw_score, adjusted_score, cap_reasons)
    flags = _consistency_flags(
        raw_score,
        adjusted_score,
        resolution["raw_verdict"],
        resolution["cap_final_verdict"],
        resolution["adjusted_score_verdict"],
        final_verdict,
        alignment,
        cap_reasons,
        total_penalty,
    )

    return {
        "raw_score": round(raw_score, 1),
        "adjusted_score": adjusted_score,
        "total_consistency_penalty": total_penalty,
        "consistency_penalty_capped": penalty_capped,
        "raw_verdict": resolution["raw_verdict"],
        "cap_final_verdict": resolution["cap_final_verdict"],
        "adjusted_score_verdict": resolution["adjusted_score_verdict"],
        "final_verdict": final_verdict,
        "verdict_source": resolution["verdict_source"],
        "resolution_reason": resolution["resolution_reason"],
        "score_verdict_alignment": alignment,
        "score_verdict_gap": f"raw_{_slug(raw_verdict)}_final_{_slug(final_verdict)}",
        "consistency_penalties": penalty_items,
        "cap_reasons": cap_reasons,
        "consistency_flags": flags,
    }


def apply_score_consistency(score_result: dict, consistency: dict) -> dict:
    updated = dict(score_result)
    raw_score = consistency.get("raw_score", updated.get("raw_investment_score", updated.get("investment_score")))
    adjusted_score = consistency.get("adjusted_score", updated.get("investment_score"))

    updated["raw_investment_score"] = raw_score
    updated["adjusted_investment_score"] = adjusted_score
    updated["investment_score"] = adjusted_score
    updated["raw_verdict"] = consistency.get("raw_verdict", updated.get("raw_verdict"))
    updated["cap_final_verdict"] = consistency.get("cap_final_verdict", updated.get("cap_final_verdict"))
    updated["adjusted_score_verdict"] = consistency.get("adjusted_score_verdict")
    updated["final_verdict"] = consistency.get("final_verdict", updated.get("verdict"))
    updated["verdict"] = updated["final_verdict"]
    updated["verdict_source"] = consistency.get("verdict_source")
    updated["resolution_reason"] = consistency.get("resolution_reason")
    updated["total_consistency_penalty"] = consistency.get("total_consistency_penalty", 0.0)
    updated["consistency_penalty_capped"] = consistency.get("consistency_penalty_capped", False)
    updated["consistency_penalties"] = consistency.get("consistency_penalties", [])
    updated["score_verdict_alignment"] = consistency.get("score_verdict_alignment", "aligned")
    updated["score_verdict_gap"] = consistency.get("score_verdict_gap")
    updated["consistency_flags"] = consistency.get("consistency_flags", [])
    updated["scoring"] = dict(consistency)
    return updated
