import argparse
import html
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import DB_PATH, REPORTS_DIR, project_path
from modules.verdict_resolver import more_conservative_verdict, verdict_from_score


CANONICAL_REQUIRED_FIELDS = ("cap_final_verdict", "adjusted_score_verdict", "verdict_source")
CANONICAL_SCORING_FIELDS = (*CANONICAL_REQUIRED_FIELDS, "final_verdict")


def _as_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_json(value) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    return json.loads(value)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _band_alignment(final_verdict: str, adjusted_score: float) -> str:
    if final_verdict == "STRONG PUBLISH":
        if adjusted_score >= 90:
            return "aligned"
        return "minor_gap" if adjusted_score >= 86 else "major_gap"
    if final_verdict == "PUBLISH":
        if 80 <= adjusted_score < 90:
            return "aligned"
        return "minor_gap" if 76 <= adjusted_score < 92 else "major_gap"
    if final_verdict == "SAFE TO TEST":
        if 68 <= adjusted_score < 80:
            return "aligned"
        return "minor_gap" if adjusted_score < 68 else "major_gap"
    if final_verdict == "REWORK":
        if 50 <= adjusted_score < 68:
            return "aligned"
        return "minor_gap" if adjusted_score < 50 else "major_gap"
    if final_verdict in {"HOLD", "HOLD / CLIP FIRST"}:
        if adjusted_score < 50:
            return "aligned"
        return "minor_gap" if adjusted_score < 70 else "major_gap"
    if final_verdict == "REJECT":
        if adjusted_score < 35:
            return "aligned"
        return "minor_gap" if adjusted_score < 50 else "major_gap"
    return "aligned"


def _top_edit_points(edit_points: list[dict]) -> list[str]:
    output = []
    for point in edit_points[:3]:
        output.append(f"{point.get('priority', '-')}: {point.get('issue_type', point.get('description', '-'))}")
    return output


def _has_consistency_model(data: dict, scoring: dict) -> bool:
    return "adjusted_investment_score" in data and "consistency_penalties" in scoring


def _has_any_canonical_field(scoring: dict) -> bool:
    return any(field in scoring for field in CANONICAL_REQUIRED_FIELDS)


def _expected_source(cap_final_verdict: str, adjusted_score_verdict: str, final_verdict: str) -> str:
    if cap_final_verdict == adjusted_score_verdict:
        return "tie"
    if final_verdict == adjusted_score_verdict:
        return "adjusted_score"
    return "cap"


def audit_report_record(record: dict) -> dict:
    data = _parse_json(record.get("report_json", record))
    scoring = data.get("scoring") or {}
    has_consistency_model = _has_consistency_model(data, scoring)
    has_any_canonical = _has_any_canonical_field(scoring)
    old_schema = not has_consistency_model or not has_any_canonical
    raw_score = _as_float(scoring.get("raw_score", data.get("raw_investment_score", data.get("investment_score"))))
    adjusted_score = _as_float(scoring.get("adjusted_score", data.get("investment_score")))
    total_penalty = _as_float(
        scoring.get(
            "total_consistency_penalty",
            max(0.0, raw_score - adjusted_score),
        )
    )
    raw_verdict = scoring.get("raw_verdict") or data.get("raw_verdict") or data.get("verdict")
    cap_final_verdict = (
        scoring.get("cap_final_verdict")
        or data.get("cap_final_verdict")
        or (data.get("verdict_cap") or {}).get("final_verdict")
        or data.get("verdict")
        or raw_verdict
    )
    adjusted_score_verdict = scoring.get("adjusted_score_verdict") or data.get("adjusted_score_verdict") or verdict_from_score(adjusted_score)
    final_verdict = scoring.get("final_verdict") or data.get("final_verdict") or data.get("verdict") or raw_verdict
    expected_final_verdict = more_conservative_verdict(cap_final_verdict, adjusted_score_verdict)
    verdict_source = scoring.get("verdict_source") or data.get("verdict_source")
    expected_verdict_source = _expected_source(cap_final_verdict, adjusted_score_verdict, expected_final_verdict)
    cap_reasons = list(scoring.get("cap_reasons") or (data.get("verdict_cap") or {}).get("cap_reasons", []))
    edit_points = list(data.get("edit_points") or [])
    alignment = scoring.get("score_verdict_alignment") or (
        "cap_limited" if final_verdict != adjusted_score_verdict and expected_verdict_source == "cap" else _band_alignment(final_verdict, adjusted_score)
    )

    flags = []
    notes = []

    if old_schema:
        flags.append("old report detected, needs reanalysis")
        notes.append("Report predates canonical verdict fields. Re-analyze manually to migrate.")
    else:
        for field in CANONICAL_SCORING_FIELDS:
            if field not in scoring:
                flags.append(f"missing {field} in scoring object")
        if final_verdict != expected_final_verdict:
            flags.append(
                "final_verdict does not equal more_conservative(cap_final_verdict, adjusted_score_verdict)"
            )
        if verdict_source and verdict_source != expected_verdict_source:
            flags.append("verdict_source does not match canonical resolver source")

    filename = record.get("filename") or record.get("original_filename") or (data.get("asset_overview") or {}).get("filename")
    status = "pending_reanalysis" if old_schema else ("needs_review" if flags else "ok")
    return {
        "report_id": record.get("report_id") or record.get("id") or data.get("report_id"),
        "clip_id": record.get("clip_id") or (data.get("asset_overview") or {}).get("clip_id"),
        "filename": filename,
        "raw_score": round(raw_score, 1),
        "adjusted_score": round(adjusted_score, 1),
        "raw_verdict": raw_verdict,
        "cap_final_verdict": cap_final_verdict,
        "adjusted_score_verdict": adjusted_score_verdict,
        "final_verdict": final_verdict,
        "expected_final_verdict": expected_final_verdict,
        "verdict_source": verdict_source,
        "expected_verdict_source": expected_verdict_source,
        "total_penalty": round(total_penalty, 1),
        "cap_reasons": cap_reasons,
        "top_edit_points": _top_edit_points(edit_points),
        "alignment": alignment,
        "flags": flags,
        "status": status,
        "old_schema": old_schema,
        "needs_reanalysis": old_schema,
        "pending_reanalysis": status == "pending_reanalysis",
        "needs_review": status == "needs_review",
        "notes": notes,
    }


def audit_reports(records: list[dict]) -> list[dict]:
    return [audit_report_record(record) for record in records]


def split_audit_results(results: list[dict]) -> dict:
    return {
        "pending_reanalysis": [item for item in results if item.get("status") == "pending_reanalysis"],
        "needs_review": [item for item in results if item.get("status") == "needs_review"],
        "ok": [item for item in results if item.get("status") == "ok"],
    }


def load_report_records(days: int | None = None) -> list[dict]:
    db_path = project_path(DB_PATH)
    if not db_path.exists():
        return []
    cutoff = None
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                r.id AS report_id,
                r.clip_id,
                r.investment_score,
                r.verdict,
                r.report_json,
                r.created_at,
                c.original_filename AS filename
            FROM clip_reports r
            LEFT JOIN clips c ON c.id = r.clip_id
            WHERE r.id = (
                SELECT latest.id
                FROM clip_reports latest
                WHERE latest.clip_id = r.clip_id
                ORDER BY latest.created_at DESC
                LIMIT 1
            )
            ORDER BY r.created_at DESC
            """
        ).fetchall()
    finally:
        conn.close()

    records = [dict(row) for row in rows]
    if cutoff is not None:
        records = [
            record
            for record in records
            if (created := _parse_time(record.get("created_at"))) is not None and created >= cutoff
        ]
    return records


def _summary(results: list[dict]) -> dict:
    split = split_audit_results(results)
    return {
        "reports_scanned": len(results),
        "pending_reanalysis": len(split["pending_reanalysis"]),
        "needs_review": len(split["needs_review"]),
        "ok": len(split["ok"]),
        "old_schema": sum(1 for item in results if item.get("old_schema")),
        "minor_gap": sum(1 for item in results if item["alignment"] == "minor_gap"),
        "major_gap": sum(1 for item in results if item["alignment"] == "major_gap"),
    }


def _json_output(results: list[dict]) -> dict:
    split = split_audit_results(results)
    return {
        "summary": _summary(results),
        "pending_reanalysis": split["pending_reanalysis"],
        "needs_review": split["needs_review"],
        "ok": split["ok"],
        "results": results,
    }


def build_audit_payload(results: list[dict]) -> dict:
    return _json_output(results)


def _format_table(results: list[dict]) -> str:
    if not results:
        return "No reports found."
    headers = [
        "filename",
        "clip_id",
        "raw",
        "adjusted",
        "raw verdict",
        "cap verdict",
        "adjusted verdict",
        "final verdict",
        "source",
        "penalty",
        "alignment",
        "status",
    ]
    rows = []
    for item in results:
        rows.append(
            [
                item.get("filename") or "-",
                item.get("clip_id") or "-",
                item["raw_score"],
                item["adjusted_score"],
                item.get("raw_verdict") or "-",
                item.get("cap_final_verdict") or "-",
                item.get("adjusted_score_verdict") or "-",
                item.get("final_verdict") or "-",
                item.get("verdict_source") or "-",
                item["total_penalty"],
                item.get("alignment") or "-",
                item.get("status") or "-",
            ]
        )
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(str(value)))
    line = " | ".join(header.ljust(widths[index]) for index, header in enumerate(headers))
    divider = "-+-".join("-" * width for width in widths)
    body = [" | ".join(str(value).ljust(widths[index]) for index, value in enumerate(row)) for row in rows]
    pending = [item for item in results if item.get("status") == "pending_reanalysis"]
    details = []
    for item in results:
        if item["needs_review"]:
            details.append(f"- {item.get('filename') or item.get('clip_id')}: " + "; ".join(item["flags"]))
    pending_details = [
        f"- {item.get('filename') or item.get('clip_id')}: old_schema=true, needs_reanalysis=true"
        for item in pending
    ]
    return "\n".join(
        [
            line,
            divider,
            *body,
            "",
            f"{len(pending)} reports pending re-analysis under the canonical verdict schema (not flagged as inconsistent).",
            f"{len(details)} reports flagged for genuine score/verdict gaps.",
            "",
            "Pending re-analysis:",
            *(pending_details or ["- none"]),
            "",
            "Flag details:",
            *(details or ["- none"]),
        ]
    )


def _write_report(results: list[dict]) -> tuple[Path, Path]:
    reports_dir = project_path(REPORTS_DIR)
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = reports_dir / f"score_verdict_consistency_{stamp}.json"
    html_path = reports_dir / f"score_verdict_consistency_{stamp}.html"
    payload = _json_output(results)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = "\n".join(
        f"""
        <tr>
          <td>{html.escape(str(item.get('filename') or '-'))}</td>
          <td>{html.escape(str(item.get('clip_id') or '-'))}</td>
          <td>{item['raw_score']}</td>
          <td>{item['adjusted_score']}</td>
          <td>{html.escape(str(item.get('raw_verdict') or '-'))}</td>
          <td>{html.escape(str(item.get('cap_final_verdict') or '-'))}</td>
          <td>{html.escape(str(item.get('adjusted_score_verdict') or '-'))}</td>
          <td>{html.escape(str(item.get('final_verdict') or '-'))}</td>
          <td>{html.escape(str(item.get('verdict_source') or '-'))}</td>
          <td>{item['total_penalty']}</td>
          <td>{html.escape(str(item.get('alignment') or '-'))}</td>
          <td>{html.escape(str(item.get('status') or '-'))}</td>
          <td>{html.escape('; '.join(item.get('flags') or []))}</td>
        </tr>
        """
        for item in results
    )
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Score / Verdict Consistency Audit</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; background:#101216; color:#eef3f8; }}
    main {{ max-width: 1180px; margin: 32px auto; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #303947; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ color: #9da8b7; }}
  </style>
</head>
<body>
<main>
  <h1>Score / Verdict Consistency Audit</h1>
  <p>{payload['summary']['pending_reanalysis']} reports pending re-analysis under the canonical verdict schema (not flagged as inconsistent).</p>
  <p>{payload['summary']['needs_review']} reports flagged for genuine score/verdict gaps.</p>
  <p>Reports scanned: {payload['summary']['reports_scanned']} | OK: {payload['summary']['ok']}</p>
  <table>
    <thead><tr><th>Filename</th><th>Clip ID</th><th>Raw</th><th>Adjusted</th><th>Raw Verdict</th><th>Cap Verdict</th><th>Adjusted Verdict</th><th>Final Verdict</th><th>Source</th><th>Penalty</th><th>Alignment</th><th>Status</th><th>Flags</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</main>
</body>
</html>"""
    html_path.write_text(html_doc, encoding="utf-8")
    return json_path, html_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit score/verdict consistency across reports.")
    parser.add_argument("--days", type=int, help="Only include reports created within the last N days.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a table.")
    parser.add_argument("--write-report", action="store_true", help="Write JSON and HTML audit reports under data/reports.")
    args = parser.parse_args(argv)

    results = audit_reports(load_report_records(args.days))
    if args.write_report:
        json_path, html_path = _write_report(results)
        print(f"Wrote JSON report: {json_path}")
        print(f"Wrote HTML report: {html_path}")
    if args.json:
        print(json.dumps(_json_output(results), ensure_ascii=False, indent=2))
    else:
        print(_format_table(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
