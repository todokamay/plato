import html
import json
from datetime import datetime, timezone

from config import THRESHOLDS
from modules.verdict_resolver import resolve_final_verdict


def _clean_metadata(metadata: dict) -> dict:
    return {key: value for key, value in metadata.items() if key != "raw"}


def _fmt_number(value, suffix: str = "", precision: int = 1) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if precision == 0:
        return f"{number:.0f}{suffix}"
    return f"{number:.{precision}f}{suffix}"


def _append_parameter(rows: list[dict], seen: set[str], key: str, name: str, measured_value: str, threshold: str, result: str) -> None:
    if key in seen:
        for row in rows:
            if row["key"] == key and result and result not in row["resulting_penalty_or_cap"]:
                row["resulting_penalty_or_cap"] += f"; {result}"
        return
    seen.add(key)
    rows.append(
        {
            "key": key,
            "parameter_name": name,
            "measured_value": measured_value,
            "threshold": threshold,
            "resulting_penalty_or_cap": result,
        }
    )


def _cap_evaluation_parameters(analyses: dict, scores: dict, edit_points: list[dict]) -> list[dict]:
    metadata = analyses.get("metadata", {})
    visual = analyses.get("visual", {})
    opening = analyses.get("opening", {})
    audio = analyses.get("audio", {})
    rhythm = analyses.get("rhythm", {})
    active = visual.get("active_content") or {}
    cap_reasons = (scores.get("verdict_cap") or {}).get("cap_reasons", [])
    important_types = {
        point.get("issue_type")
        for point in edit_points
        if point.get("priority") in {"P0", "P1"}
    }
    cap_text = " ".join(cap_reasons).lower()
    rows: list[dict] = []
    seen: set[str] = set()

    if "bitrate" in cap_text or important_types & {"low_bitrate", "very_low_bitrate"}:
        related = [reason for reason in cap_reasons if "bitrate" in reason.lower()]
        _append_parameter(
            rows,
            seen,
            "video_bitrate_kbps",
            "Video Bitrate",
            _fmt_number(metadata.get("video_bitrate_kbps"), " kbps"),
            (
                f"{THRESHOLDS['very_low_video_bitrate_kbps']} kbps very-low floor; "
                f"{THRESHOLDS['min_video_bitrate_kbps']} kbps minimum; "
                f"{THRESHOLDS['preferred_video_bitrate_kbps']} kbps preferred"
            ),
            "; ".join(related) or "P0/P1 low-bitrate edit point",
        )

    if "first half-second" in cap_text or "opening score" in cap_text or important_types & {"weak_opening", "low_visual_change_opening"}:
        related = [reason for reason in cap_reasons if "first half-second" in reason.lower() or "opening" in reason.lower()]
        value = "low visual change" if opening.get("opening_first_half_static") else f"opening score {_fmt_number(opening.get('opening_score'))}"
        _append_parameter(
            rows,
            seen,
            "opening_visual_change",
            "Opening Visual Change",
            value,
            "opening score < 60 caps to REWORK; < 70 caps to SAFE TO TEST; first 0.5s should show visible change",
            "; ".join(related) or "P0/P1 opening edit point",
        )

    if "retention score" in cap_text or important_types & {"dead_time_segment", "static_segment", "repeated_frame_segment", "low_motion_segment", "static_ending"}:
        related = [reason for reason in cap_reasons if "retention" in reason.lower() or "static" in reason.lower() or "motion" in reason.lower()]
        _append_parameter(
            rows,
            seen,
            "scene_rhythm",
            "Scene Rhythm / Dead Time",
            f"dead time ratio {_fmt_number(rhythm.get('dead_time_ratio'), precision=3)}",
            "P0/P1 when deterministic rhythm analyzer finds dead/static/repeated sections",
            "; ".join(related) or "P0/P1 rhythm edit point",
        )

    if "active content" in cap_text or important_types & {"low_active_content_area", "pillarbox_detected", "letterbox_detected", "small_center_content"}:
        related = [reason for reason in cap_reasons if "active content" in reason.lower()]
        _append_parameter(
            rows,
            seen,
            "active_content_ratio",
            "Active Content Ratio",
            _fmt_number(active.get("active_content_ratio"), precision=3),
            "0.40 critical floor; 0.55 rework floor; 0.70 preferred mobile fill",
            "; ".join(related) or "P0/P1 composition edit point",
        )

    if "horizontal" in cap_text or "duration" in cap_text or important_types & {"horizontal_source", "duration_too_long"}:
        related = [reason for reason in cap_reasons if "horizontal" in reason.lower() or "duration" in reason.lower() or "source" in reason.lower()]
        measured = f"aspect {_fmt_number(metadata.get('aspect_ratio'), precision=3)}, duration {_fmt_number(metadata.get('duration'), 's')}"
        _append_parameter(
            rows,
            seen,
            "format_duration",
            "Format / Duration",
            measured,
            f"vertical aspect near {THRESHOLDS['vertical_aspect_target']}; max short duration {THRESHOLDS['max_short_duration']}s",
            "; ".join(related) or "P0/P1 format edit point",
        )

    if "black" in cap_text or "unreadable" in cap_text or "critical" in cap_text or important_types & {"black_segment"}:
        related = [reason for reason in cap_reasons if "black" in reason.lower() or "unreadable" in reason.lower() or "critical" in reason.lower()]
        measured = f"black ratio {_fmt_number(visual.get('black_ratio'), precision=3)}, static ratio {_fmt_number(visual.get('static_ratio'), precision=3)}"
        _append_parameter(
            rows,
            seen,
            "critical_visual",
            "Critical Visual State",
            measured,
            "black ratio >= 0.65 or static ratio >= 0.85 triggers critical penalty/cap",
            "; ".join(related) or "P0 critical visual edit point",
        )

    if important_types & {"no_audio", "audio_too_quiet", "opening_silence", "silence_segment", "possible_clipping"}:
        _append_parameter(
            rows,
            seen,
            "audio_quality",
            "Audio Quality",
            f"mean {_fmt_number(audio.get('mean_volume_db'), ' dB')}, silence ratio {_fmt_number(audio.get('silence_ratio'), precision=3)}",
            "quiet if mean volume < -25 dB; opening silence and long silence create edit points",
            "P0/P1 audio edit point",
        )

    return rows


def _scoring_payload(scores: dict) -> dict:
    scoring = dict(scores.get("scoring") or {})
    raw_score = scores.get("raw_investment_score", scores.get("investment_score"))
    adjusted_score = scores.get("adjusted_investment_score", scores.get("investment_score"))
    if raw_score is not None:
        raw_score = round(float(raw_score), 1)
    if adjusted_score is not None:
        adjusted_score = round(float(adjusted_score), 1)
    if "total_consistency_penalty" in scores:
        total_penalty = round(float(scores.get("total_consistency_penalty") or 0), 1)
    elif raw_score is not None and adjusted_score is not None:
        total_penalty = round(max(0.0, raw_score - adjusted_score), 1)
    else:
        total_penalty = 0.0

    cap_reasons = scoring.get("cap_reasons")
    if cap_reasons is None:
        cap_reasons = (scores.get("verdict_cap") or {}).get("cap_reasons", [])

    raw_verdict = scoring.get("raw_verdict") or scores.get("raw_verdict") or scores.get("verdict")
    cap_final_verdict = (
        scoring.get("cap_final_verdict")
        or scores.get("cap_final_verdict")
        or (scores.get("verdict_cap") or {}).get("final_verdict")
        or scores.get("verdict")
        or raw_verdict
    )
    consistency_penalties = scoring.get("consistency_penalties", scores.get("consistency_penalties", []))
    resolution = resolve_final_verdict(raw_verdict, cap_final_verdict, adjusted_score, cap_reasons, consistency_penalties)

    scoring["raw_score"] = raw_score
    scoring["raw_investment_score"] = raw_score
    scoring["adjusted_score"] = adjusted_score
    scoring["adjusted_investment_score"] = adjusted_score
    scoring["investment_score"] = adjusted_score
    scoring["total_consistency_penalty"] = total_penalty
    scoring["raw_verdict"] = resolution["raw_verdict"]
    scoring["cap_final_verdict"] = resolution["cap_final_verdict"]
    scoring["adjusted_score_verdict"] = resolution["adjusted_score_verdict"]
    scoring["final_verdict"] = resolution["final_verdict"]
    scoring["verdict_source"] = resolution["verdict_source"]
    scoring["resolution_reason"] = resolution["resolution_reason"]
    default_alignment = "aligned" if scoring["final_verdict"] == scoring["adjusted_score_verdict"] else "cap_limited"
    scoring.setdefault("score_verdict_alignment", scores.get("score_verdict_alignment", default_alignment))
    scoring.setdefault("score_verdict_gap", scores.get("score_verdict_gap"))
    scoring.setdefault("consistency_penalties", consistency_penalties)
    scoring.setdefault("cap_reasons", cap_reasons)
    scoring.setdefault("consistency_flags", scores.get("consistency_flags", []))
    scoring.setdefault("consistency_penalty_capped", scores.get("consistency_penalty_capped", False))
    return scoring


def generate_report_json(clip: dict, analyses: dict, scores: dict, recommendations: dict, report_id: str) -> dict:
    metadata = _clean_metadata(analyses.get("metadata", {}))
    edit_points = recommendations.get("edit_points", [])
    estimated_after_fixes = recommendations.get("estimated_after_fixes", {})
    scoring = _scoring_payload(scores)
    final_verdict = scoring.get("final_verdict")
    cap_parameters = _cap_evaluation_parameters(analyses, scores, edit_points)
    limitations = [
        "No ML in v0.2.",
        "No OCR in v0.2.",
        "Edit points are deterministic.",
        "Credits-like/static text-card detection is heuristic and low-confidence.",
        "Active content detection is heuristic and deterministic.",
        "Adjusted score is formula-based.",
        "Expected score lift is formula-based, not historically validated.",
        "Score lift and consistency penalties are not empirically validated.",
    ]
    return {
        "report_id": report_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "executive_summary": {
            "investment_score": scoring.get("adjusted_score"),
            "raw_investment_score": scoring.get("raw_score"),
            "adjusted_investment_score": scoring.get("adjusted_score"),
            "total_consistency_penalty": scoring.get("total_consistency_penalty"),
            "verdict": final_verdict,
            "raw_verdict": scoring.get("raw_verdict"),
            "cap_final_verdict": scoring.get("cap_final_verdict"),
            "adjusted_score_verdict": scoring.get("adjusted_score_verdict"),
            "final_verdict": final_verdict,
            "verdict_source": scoring.get("verdict_source"),
            "resolution_reason": scoring.get("resolution_reason"),
            "verdict_cap": scores.get("verdict_cap", {}),
            "score_verdict_alignment": scoring.get("score_verdict_alignment"),
            "consistency_penalties": scoring.get("consistency_penalties", []),
            "consistency_penalty_capped": scoring.get("consistency_penalty_capped", False),
            "main_bottleneck": recommendations.get("main_bottleneck"),
            "best_fix": recommendations.get("best_fix"),
            "top_edit_point": edit_points[0] if edit_points else None,
            "estimated_after_fixes": estimated_after_fixes,
            "expected_score_after_fixes": recommendations.get("expected_score_after_fixes"),
            "expected_score_note": recommendations.get("expected_score_note"),
        },
        "asset_overview": {
            "clip_id": clip.get("id"),
            "filename": clip.get("original_filename"),
            "file_size": clip.get("file_size"),
            "status": clip.get("status"),
            "duration": metadata.get("duration"),
            "width": metadata.get("width"),
            "height": metadata.get("height"),
            "fps": metadata.get("fps"),
            "aspect_ratio": metadata.get("aspect_ratio"),
            "has_audio": metadata.get("has_audio"),
        },
        "investment_score": scoring.get("adjusted_score"),
        "raw_investment_score": scoring.get("raw_score"),
        "adjusted_investment_score": scoring.get("adjusted_score"),
        "verdict": final_verdict,
        "raw_verdict": scoring.get("raw_verdict"),
        "cap_final_verdict": scoring.get("cap_final_verdict"),
        "adjusted_score_verdict": scoring.get("adjusted_score_verdict"),
        "final_verdict": final_verdict,
        "verdict_source": scoring.get("verdict_source"),
        "resolution_reason": scoring.get("resolution_reason"),
        "verdict_cap": scores.get("verdict_cap", {}),
        "scoring": scoring,
        "cap_evaluation_parameters": cap_parameters,
        "strong_publish_requirements": scores.get("strong_publish_requirements", []),
        "score_breakdown": scores.get("scores", {}),
        "penalties": scores.get("penalties", {}),
        "main_bottleneck": recommendations.get("main_bottleneck"),
        "edit_points": edit_points,
        "estimated_after_fixes": estimated_after_fixes,
        "weak_points": recommendations.get("weak_points", []),
        "improvement_plan": recommendations.get("improvement_plan", []),
        "opening_entry_point_analysis": analyses.get("opening", {}),
        "retention_drawdown_timeline": analyses.get("retention", {}).get("drawdown_segments", []),
        "timeline": {
            "drawdown_segments": analyses.get("retention", {}).get("drawdown_segments", []),
            "audio_segments": analyses.get("audio", {}).get("silence_segments", []),
            "audio_drop_segments": analyses.get("audio", {}).get("audio_drop_segments", []),
            "audio_energy_timeline": analyses.get("audio", {}).get("audio_energy_timeline", []),
            "rhythm_segments": analyses.get("rhythm", {}).get("segments", []),
        },
        "evaluation_parameters": {
            "opening": analyses.get("opening", {}),
            "retention": {
                "retention_score": analyses.get("retention", {}).get("retention_score"),
                "drawdown_count": len(analyses.get("retention", {}).get("drawdown_segments", [])),
            },
            "rhythm": analyses.get("rhythm", {}),
            "composition": analyses.get("visual", {}).get("active_content", {}),
            "audio": {
                "mean_volume_db": analyses.get("audio", {}).get("mean_volume_db"),
                "max_volume_db": analyses.get("audio", {}).get("max_volume_db"),
                "silence_ratio": analyses.get("audio", {}).get("silence_ratio"),
                "opening_silence": analyses.get("audio", {}).get("opening_silence"),
                "audio_drop_count": len(analyses.get("audio", {}).get("audio_drop_segments", [])),
            },
            "technical": {
                "video_bitrate_kbps": metadata.get("video_bitrate_kbps"),
                "audio_bitrate_kbps": metadata.get("audio_bitrate_kbps"),
                "fps": metadata.get("fps"),
                "width": metadata.get("width"),
                "height": metadata.get("height"),
                "avg_sharpness": analyses.get("visual", {}).get("avg_sharpness"),
            },
        },
        "technical_quality": {
            "metadata": metadata,
            "visual_metrics": {
                "avg_brightness": analyses.get("visual", {}).get("avg_brightness"),
                "avg_sharpness": analyses.get("visual", {}).get("avg_sharpness"),
                "black_ratio": analyses.get("visual", {}).get("black_ratio"),
                "static_ratio": analyses.get("visual", {}).get("static_ratio"),
                "active_content_ratio": analyses.get("visual", {}).get("active_content_ratio"),
                "active_width_ratio": analyses.get("visual", {}).get("active_width_ratio"),
                "active_height_ratio": analyses.get("visual", {}).get("active_height_ratio"),
                "black_border_ratio": analyses.get("visual", {}).get("black_border_ratio"),
            },
            "issues": scores.get("technical_issues", []),
        },
        "composition": analyses.get("visual", {}).get("active_content", {}),
        "audio_quality": analyses.get("audio", {}),
        "final_recommendation": {
            "verdict": final_verdict,
            "best_fix": recommendations.get("best_fix"),
            "positioning": _final_positioning(final_verdict),
        },
        "limitations": limitations,
        "analysis_limitations": limitations,
    }


def _final_positioning(verdict: str | None) -> str:
    if verdict in {"STRONG PUBLISH", "PUBLISH"}:
        return "This asset is a publish candidate, subject to human creative review."
    if verdict == "SAFE TO TEST":
        return "This asset is reasonable to test if the publishing slot is not scarce."
    if verdict == "REWORK":
        return "Improve the top weak points before spending a publishing slot."
    if verdict == "HOLD / CLIP FIRST":
        return "Treat this as source footage and extract a stronger short-form clip."
    if verdict == "HOLD":
        return "Hold until the format or timeline risk is reduced."
    return "Do not publish this version."


def _badge_class(verdict: str | None) -> str:
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


def _row(label: str, value) -> str:
    return f"<tr><th>{html.escape(label)}</th><td>{html.escape(str(value if value is not None else '-'))}</td></tr>"


def _verdict_source_note(source: str | None) -> str:
    if source == "adjusted_score":
        return "Final verdict was downgraded because adjusted score falls into a lower verdict band."
    if source == "cap":
        return "Final verdict is limited by hard cap reasons."
    if source == "tie":
        return "Cap verdict and adjusted-score verdict agree."
    return "Final verdict was resolved from canonical scoring fields."


def _time_range(item: dict) -> str:
    start = item.get("start_time")
    end = item.get("end_time")
    if start is None and end is None:
        return "-"
    if end is None:
        return f"{float(start):.1f}s"
    return f"{float(start or 0):.1f}-{float(end):.1f}s"


def generate_report_html(report_json: dict) -> str:
    verdict = report_json.get("verdict")
    score = report_json.get("investment_score")
    overview = report_json.get("asset_overview", {})
    scores = report_json.get("score_breakdown", {})
    weak_points = report_json.get("weak_points", [])
    edit_points = report_json.get("edit_points", [])
    estimate = report_json.get("estimated_after_fixes") or {}
    timeline = report_json.get("retention_drawdown_timeline", [])
    summary = report_json.get("executive_summary", {})
    best_fix = summary.get("best_fix") or {}
    verdict_cap = report_json.get("verdict_cap") or {}
    composition = report_json.get("composition") or {}
    scoring = report_json.get("scoring") or {}
    cap_parameters = report_json.get("cap_evaluation_parameters") or []

    score_rows = "\n".join(_row(key.title(), value) for key, value in scores.items())
    overview_rows = "\n".join(_row(key.replace("_", " ").title(), value) for key, value in overview.items())
    cap_rows = "\n".join(
        f"<li>{html.escape(reason)}</li>" for reason in verdict_cap.get("cap_reasons", [])
    ) or "<li>No cap applied.</li>"
    penalty_rows = "\n".join(
        f"""
        <tr>
          <td>{html.escape(item.get('label', item.get('code', 'Adjustment')))}</td>
          <td>-{html.escape(str(item.get('amount', 0)))}</td>
          <td>{html.escape(item.get('reason', '-'))}{' ' + html.escape(item.get('note', '')) if item.get('note') else ''}</td>
        </tr>
        """
        for item in scoring.get("consistency_penalties", [])
    ) or "<tr><td colspan='3'>No consistency adjustment applied.</td></tr>"
    consistency_notes = []
    if scoring.get("score_verdict_alignment") == "cap_limited":
        cap_text = "; ".join(str(reason) for reason in scoring.get("cap_reasons", [])) or "hard verdict cap"
        consistency_notes.append(
            "Final verdict is limited by a hard verdict cap. "
            f"Cap reasons: {cap_text}."
        )
    if scoring.get("consistency_penalty_capped"):
        consistency_notes.append("Penalty capped at raw score; adjusted score floored at 0.")
    consistency_notes.append(_verdict_source_note(scoring.get("verdict_source")))
    consistency_note_html = "".join(f"<p>{html.escape(note)}</p>" for note in consistency_notes)
    scoring_rows = "\n".join(
        [
            _row("Raw Score", scoring.get("raw_score", report_json.get("raw_investment_score"))),
            _row("Adjusted Score", scoring.get("adjusted_score", score)),
            _row("Total Adjustment", f"-{scoring.get('total_consistency_penalty', 0)}"),
            _row("Raw Verdict", scoring.get("raw_verdict", report_json.get("raw_verdict"))),
            _row("Cap Final Verdict", scoring.get("cap_final_verdict", report_json.get("cap_final_verdict"))),
            _row("Adjusted-Score Verdict", scoring.get("adjusted_score_verdict", report_json.get("adjusted_score_verdict"))),
            _row("Final Verdict", scoring.get("final_verdict", verdict)),
            _row("Verdict Source", scoring.get("verdict_source", report_json.get("verdict_source"))),
            _row("Alignment", scoring.get("score_verdict_alignment", "aligned")),
        ]
    )
    cap_parameter_rows = "\n".join(
        f"""
        <tr>
          <td>{html.escape(item.get('parameter_name', '-'))}</td>
          <td>{html.escape(str(item.get('measured_value', '-')))}</td>
          <td>{html.escape(str(item.get('threshold', '-')))}</td>
          <td>{html.escape(str(item.get('resulting_penalty_or_cap', '-')))}</td>
        </tr>
        """
        for item in cap_parameters
    ) or "<tr><td colspan='4'>No cap or P0/P1 edit parameters recorded.</td></tr>"
    composition_rows = "\n".join(
        _row(label, composition.get(key))
        for label, key in [
            ("Active content ratio", "active_content_ratio"),
            ("Active width ratio", "active_width_ratio"),
            ("Active height ratio", "active_height_ratio"),
            ("Black border ratio", "black_border_ratio"),
            ("Pillarbox detected", "pillarbox_detected"),
            ("Letterbox detected", "letterbox_detected"),
            ("Small center content", "small_center_content_detected"),
            ("Confidence", "confidence"),
        ]
    )

    weak_html = "\n".join(
        f"""
        <li>
          <strong>{html.escape(item.get('priority', 'P3'))} - {html.escape(item.get('description', 'Issue'))}</strong>
          <p>{html.escape(item.get('recommendation', 'Review manually.'))}</p>
          <small>{html.escape(item.get('affected_score', '-'))} +{html.escape(str(item.get('expected_score_lift', 0)))} formula points</small>
        </li>
        """
        for item in weak_points[:8]
    ) or "<li>No major deterministic weak points found.</li>"

    edit_rows = "\n".join(
        f"""
        <tr>
          <td>{html.escape(point.get('priority', '-'))}</td>
          <td>{html.escape(_time_range(point))}</td>
          <td>{html.escape(point.get('description', '-'))}</td>
          <td>{html.escape(point.get('recommended_edit', '-'))}</td>
          <td>+{html.escape(str(point.get('expected_lift', {}).get('investment', 0)))}</td>
          <td>{html.escape(point.get('confidence', '-'))}</td>
          <td>{html.escape('/'.join(point.get('detected_by', [])))}</td>
        </tr>
        """
        for point in edit_points
    ) or "<tr><td colspan='7'>No edit points detected.</td></tr>"

    timeline_rows = "\n".join(
        f"""
        <tr>
          <td>{html.escape(str(item.get('start_time', '-')))}</td>
          <td>{html.escape(str(item.get('end_time', '-')))}</td>
          <td>{html.escape(item.get('severity', '-'))}</td>
          <td>{html.escape(item.get('reason', item.get('description', '-')))}</td>
          <td>{html.escape(item.get('recommendation', '-'))}</td>
        </tr>
        """
        for item in timeline
    ) or "<tr><td colspan='5'>No timeline drawdowns detected.</td></tr>"

    raw_json = html.escape(json.dumps(report_json, ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Plato Video Lab Report</title>
  <style>
    :root {{ color-scheme: dark; --bg:#111318; --panel:#1b2029; --line:#2c3442; --text:#eef2f7; --muted:#9aa6b5; --green:#2ecc71; --blue:#4aa3ff; --yellow:#ffd166; --orange:#f4a261; --red:#ff5c6c; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-family:Inter,Segoe UI,Arial,sans-serif; line-height:1.5; }}
    main {{ max-width:1120px; margin:0 auto; padding:32px 20px 56px; }}
    h1,h2 {{ margin:0 0 14px; }}
    section,.hero {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:20px; margin-top:18px; }}
    .hero {{ display:grid; grid-template-columns:1fr auto; gap:18px; align-items:center; }}
    .score {{ font-size:56px; font-weight:800; }}
    .badge {{ display:inline-flex; padding:6px 10px; border-radius:6px; font-weight:700; }}
    .good {{ background:rgba(46,204,113,.16); color:var(--green); }}
    .info {{ background:rgba(74,163,255,.16); color:var(--blue); }}
    .warn {{ background:rgba(255,209,102,.16); color:var(--yellow); }}
    .hold {{ background:rgba(244,162,97,.16); color:var(--orange); }}
    .bad {{ background:rgba(255,92,108,.16); color:var(--red); }}
    .grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ border-bottom:1px solid var(--line); padding:10px 8px; text-align:left; vertical-align:top; }}
    th {{ color:var(--muted); font-weight:600; }}
    li {{ margin-bottom:14px; }}
    p,small {{ color:var(--muted); }}
    pre {{ overflow:auto; background:#0b0d11; border:1px solid var(--line); border-radius:8px; padding:14px; }}
    @media (max-width:760px) {{ .hero,.grid {{ grid-template-columns:1fr; }} .score {{ font-size:44px; }} }}
  </style>
</head>
<body>
<main>
  <div class="hero">
    <div>
      <h1>{html.escape(str(overview.get('filename') or 'Video report'))}</h1>
      <span class="badge {_badge_class(verdict)}">{html.escape(str(verdict))}</span>
      <p>{html.escape(report_json.get('final_recommendation', {}).get('positioning', ''))}</p>
    </div>
    <div class="score">{html.escape(str(score))}</div>
  </div>

  <section>
    <h2>Score Consistency</h2>
    <div class="grid">
      <table>{scoring_rows}</table>
      <div>
        <p>Adjusted score, consistency penalties, and expected lift are formula-based. Raw score is the pre-cap weighted formula.</p>
        {consistency_note_html}
        <table>
          <thead><tr><th>Adjustment</th><th>Penalty</th><th>Reason</th></tr></thead>
          <tbody>{penalty_rows}</tbody>
        </table>
      </div>
    </div>
  </section>

  <section>
    <h2>Main Bottleneck</h2>
    <p><strong>{html.escape(str(summary.get('main_bottleneck', {}).get('label', '-')))}</strong>: {html.escape(str(summary.get('main_bottleneck', {}).get('description', '-')))}</p>
    <p><strong>Best fix:</strong> {html.escape(best_fix.get('recommendation', 'Review manually.'))}</p>
    <p>{html.escape(summary.get('expected_score_note', ''))}</p>
  </section>

  <div class="grid">
    <section>
      <h2>Score Breakdown</h2>
      <table>{score_rows}</table>
    </section>
    <section>
      <h2>Asset Overview</h2>
      <table>{overview_rows}</table>
    </section>
  </div>

  <section>
    <h2>Verdict Cap Explanation</h2>
    <p><strong>Raw verdict:</strong> {html.escape(str(verdict_cap.get('raw_verdict', report_json.get('raw_verdict', '-'))))} | <strong>Final verdict:</strong> {html.escape(str(verdict))}</p>
    <ul>{cap_rows}</ul>
    <table>
      <thead><tr><th>Parameter</th><th>Measured Value</th><th>Threshold</th><th>Result</th></tr></thead>
      <tbody>{cap_parameter_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>Active Content / Composition</h2>
    <table>{composition_rows}</table>
  </section>

  <section>
    <h2>Before / After Estimate</h2>
    <table>
      <tr><th>Current</th><td>{html.escape(str(estimate.get('current_score', score)))}</td></tr>
      <tr><th>After P0</th><td>{html.escape(str(estimate.get('estimated_after_p0', '-')))}</td></tr>
      <tr><th>After P0 + P1</th><td>{html.escape(str(estimate.get('estimated_after_p0_p1', '-')))}</td></tr>
      <tr><th>Estimated Verdict</th><td>{html.escape(str(estimate.get('estimated_verdict_after_p0_p1', '-')))}</td></tr>
      <tr><th>Note</th><td>{html.escape(str(estimate.get('notes', 'Formula-based estimate, not historically validated.')))}</td></tr>
    </table>
  </section>

  <section>
    <h2>Edit Point Timeline</h2>
    <table>
      <thead><tr><th>Priority</th><th>Time</th><th>Problem</th><th>Action</th><th>Lift</th><th>Confidence</th><th>Detected By</th></tr></thead>
      <tbody>{edit_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>Weak Points</h2>
    <ol>{weak_html}</ol>
  </section>

  <section>
    <h2>Retention Timeline</h2>
    <table>
      <thead><tr><th>Start</th><th>End</th><th>Severity</th><th>Reason</th><th>Recommendation</th></tr></thead>
      <tbody>{timeline_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>Machine JSON</h2>
    <pre>{raw_json}</pre>
  </section>
</main>
</body>
</html>"""
