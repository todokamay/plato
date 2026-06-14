from __future__ import annotations

import csv
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import REPORTS_DIR, SUPPORTED_EXTENSIONS, project_path
from modules import db
from modules.clip_identity import get_clip_identity
from modules.davinci_export import export_davinci_files
from modules.pipeline import analyze_clip, import_clip_file
from modules.portfolio_ranking import (
    BUCKET_HIGH_UPSIDE,
    BUCKET_HOLD,
    BUCKET_PUBLISH,
    BUCKET_QUICK_FIX,
    BUCKET_REJECT,
    BUCKET_SAFE,
    build_portfolio_metrics,
    bucket_folder,
    safe_filename,
)


SUMMARY_COLUMNS = [
    "rank",
    "filename",
    "file_path",
    "clip_id",
    "report_id",
    "adjusted_score",
    "raw_score",
    "total_penalty",
    "final_verdict",
    "raw_verdict",
    "cap_final_verdict",
    "adjusted_score_verdict",
    "verdict_source",
    "score_verdict_alignment",
    "portfolio_bucket",
    "publish_priority_score",
    "quick_fix_score",
    "upside_score",
    "risk_score",
    "risk_level",
    "P0_count",
    "P1_count",
    "top_edit_point",
    "top_action",
    "estimated_after_p0",
    "estimated_after_p0_p1",
    "old_schema",
    "needs_reanalysis",
    "html_report_path",
    "json_report_path",
    "copied_path",
    "davinci_marker_path",
]


def batch_id_now() -> str:
    return "batch_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def scan_video_files(folder: str | Path, recursive: bool = False, limit: int | None = None) -> list[Path]:
    root = Path(folder)
    pattern = "**/*" if recursive else "*"
    files = [
        path
        for path in root.glob(pattern)
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    files = sorted(files, key=lambda path: str(path).lower())
    return files[:limit] if limit else files


def _parse_report(report: dict | None) -> dict | None:
    if not report:
        return None
    value = report.get("report_json")
    if isinstance(value, dict):
        return value
    if not value:
        return None
    return json.loads(value)


def _report_paths(report: dict | None) -> tuple[str, str]:
    if not report:
        return "", ""
    report_id = report.get("id") or report.get("report_id")
    html_path = report.get("html_path") or ""
    json_path = str(project_path(REPORTS_DIR) / f"{report_id}.json") if report_id else ""
    return html_path, json_path


def _entry_from_report(source_path: Path, clip: dict, report: dict, status: str) -> dict:
    report_data = _parse_report(report) or {}
    metrics = build_portfolio_metrics(report_data)
    html_path, json_path = _report_paths(report)
    overview = report_data.get("asset_overview") or {}
    entry = {
        "filename": source_path.name,
        "file_path": str(source_path.resolve()),
        "clip_id": clip.get("id"),
        "report_id": report.get("id") or report.get("report_id"),
        "html_report_path": html_path,
        "json_report_path": json_path,
        "batch_status": status,
        "fps": clip.get("fps") or overview.get("fps") or 30,
        "duration": clip.get("duration") or overview.get("duration"),
        "edit_points": report_data.get("edit_points") or [],
        "edit_points_summary": [
            {
                "priority": point.get("priority"),
                "time": point.get("start_time"),
                "issue_type": point.get("issue_type"),
                "action": point.get("action"),
                "recommended_edit": point.get("recommended_edit"),
            }
            for point in (report_data.get("edit_points") or [])[:5]
        ],
    }
    entry.update(metrics)
    return entry


def _empty_entry(source_path: Path, status: str, error: str | None = None) -> dict:
    return {
        "rank": "",
        "filename": source_path.name,
        "file_path": str(source_path.resolve()),
        "clip_id": "",
        "report_id": "",
        "adjusted_score": 0,
        "raw_score": 0,
        "total_penalty": 0,
        "final_verdict": "REJECT",
        "raw_verdict": "",
        "cap_final_verdict": "",
        "adjusted_score_verdict": "",
        "verdict_source": "",
        "score_verdict_alignment": "",
        "portfolio_bucket": BUCKET_REJECT,
        "portfolio_reason": error or status,
        "publish_priority_score": -999,
        "quick_fix_score": 0,
        "upside_score": 0,
        "risk_score": 100,
        "risk_level": "CRITICAL",
        "P0_count": 0,
        "P1_count": 0,
        "P2_count": 0,
        "P3_count": 0,
        "top_edit_point": "",
        "top_action": "",
        "estimated_after_p0": 0,
        "estimated_after_p0_p1": 0,
        "old_schema": False,
        "needs_reanalysis": False,
        "html_report_path": "",
        "json_report_path": "",
        "copied_path": "",
        "davinci_marker_path": "",
        "batch_status": status,
        "error": error or "",
        "edit_points": [],
        "edit_points_summary": [],
        "fps": 30,
    }


def _copy_with_suffix(source: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = safe_filename(source.name)
    target = target_dir / safe_name
    if not target.exists():
        shutil.copy2(source, target)
        return target
    stem = target.stem
    suffix = target.suffix
    for index in range(2, 10000):
        candidate = target_dir / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            shutil.copy2(source, candidate)
            return candidate
    raise RuntimeError(f"Could not find available copy target for {source}")


def _write_summary_csv(path: Path, entries: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(entries)


def _best(entries: list[dict], bucket: str, key: str) -> dict | None:
    candidates = [entry for entry in entries if entry.get("portfolio_bucket") == bucket and not entry.get("old_schema")]
    return max(candidates, key=lambda entry: float(entry.get(key) or 0), default=None)


def _payload(batch_id: str, input_folder: Path, output_dir: Path | None, entries: list[dict], counts: dict, paths: dict) -> dict:
    valid = [entry for entry in entries if not entry.get("old_schema")]
    return {
        "batch_id": batch_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_folder": str(input_folder.resolve()),
        "output_dir": str(output_dir) if output_dir else "",
        "counts": counts,
        "best": {
            "publish_candidate": _best(entries, BUCKET_PUBLISH, "publish_priority_score"),
            "safe_test": _best(entries, BUCKET_SAFE, "publish_priority_score"),
            "quick_fix": _best(entries, BUCKET_QUICK_FIX, "quick_fix_score"),
            "high_upside": _best(entries, BUCKET_HIGH_UPSIDE, "upside_score"),
            "highest_risk": max(valid, key=lambda entry: int(entry.get("risk_score") or 0), default=None),
        },
        "paths": paths,
        "clips": entries,
    }


def _bucket_counts(entries: list[dict]) -> dict:
    return {
        "publish_candidate_count": sum(1 for entry in entries if entry.get("portfolio_bucket") == BUCKET_PUBLISH),
        "safe_test_count": sum(1 for entry in entries if entry.get("portfolio_bucket") == BUCKET_SAFE),
        "quick_fix_count": sum(1 for entry in entries if entry.get("portfolio_bucket") == BUCKET_QUICK_FIX),
        "high_upside_rework_count": sum(1 for entry in entries if entry.get("portfolio_bucket") == BUCKET_HIGH_UPSIDE),
        "hold_count": sum(1 for entry in entries if entry.get("portfolio_bucket") == BUCKET_HOLD),
        "reject_count": sum(1 for entry in entries if entry.get("portfolio_bucket") == BUCKET_REJECT),
    }


def _html_report(payload: dict) -> str:
    counts = payload["counts"]
    best = payload.get("best") or {}
    rows = "\n".join(
        f"""
        <tr>
          <td>{entry.get('rank', '')}</td>
          <td>{entry.get('filename', '')}</td>
          <td>{entry.get('adjusted_score', '')}</td>
          <td>{entry.get('final_verdict', '')}</td>
          <td>{entry.get('portfolio_bucket', '')}</td>
          <td>{entry.get('publish_priority_score', '')}</td>
          <td>{entry.get('quick_fix_score', '')}</td>
          <td>{entry.get('upside_score', '')}</td>
          <td>{entry.get('risk_level', '')} {entry.get('risk_score', '')}</td>
          <td>{entry.get('top_action', '')}</td>
          <td>{'<a href=\"' + entry.get('html_report_path', '') + '\">report</a>' if entry.get('html_report_path') else ''}</td>
        </tr>
        """
        for entry in payload.get("clips", [])
    )
    fix_rows = "\n".join(
        f"<li>{entry.get('filename')}: {entry.get('top_edit_point') or '-'} ({entry.get('top_action') or '-'})</li>"
        for entry in payload.get("clips", [])
        if (entry.get("P0_count") or 0) or (entry.get("P1_count") or 0)
    ) or "<li>No P0/P1 fixes found.</li>"
    hold_rows = "\n".join(
        f"<li>{entry.get('filename')}: {entry.get('portfolio_bucket')} - {entry.get('portfolio_reason')}</li>"
        for entry in payload.get("clips", [])
        if entry.get("portfolio_bucket") in {BUCKET_HOLD, BUCKET_REJECT}
    ) or "<li>No hold/reject clips.</li>"
    pending_rows = "\n".join(
        f"<li>{entry.get('filename')}: old_schema=true, needs_reanalysis=true</li>"
        for entry in payload.get("clips", [])
        if entry.get("old_schema")
    ) or "<li>No pending reanalysis items.</li>"
    best_items = "\n".join(
        f"<li><strong>{label.replace('_', ' ').title()}:</strong> {(item or {}).get('filename', '-')}</li>"
        for label, item in best.items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Plato Batch QC Report</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; background:#101216; color:#eef3f8; margin:0; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 28px; }}
    section {{ background:#191e27; border:1px solid #303947; border-radius:8px; padding:18px; margin:18px 0; }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ border-bottom:1px solid #303947; padding:8px; text-align:left; vertical-align:top; }}
    th {{ color:#9da8b7; }}
    a {{ color:#8bd3ff; }}
  </style>
</head>
<body>
<main>
  <h1>Batch QC Report</h1>
  <section>
    <h2>Executive Summary</h2>
    <p>Input: {payload.get('input_folder')}</p>
    <p>Scanned: {counts.get('scanned_count')} | New: {counts.get('new_count')} | Skipped: {counts.get('skipped_count')} | Analyzed: {counts.get('analyzed_count')} | Failed: {counts.get('failed_count')}</p>
    <p>Publish: {counts.get('publish_candidate_count')} | Safe Test: {counts.get('safe_test_count')} | Quick Fix: {counts.get('quick_fix_count')} | High Upside: {counts.get('high_upside_rework_count')} | Hold: {counts.get('hold_count')} | Reject: {counts.get('reject_count')}</p>
  </section>
  <section><h2>Best Picks</h2><ul>{best_items}</ul></section>
  <section>
    <h2>Portfolio Table</h2>
    <table>
      <thead><tr><th>Rank</th><th>Filename</th><th>Score</th><th>Verdict</th><th>Bucket</th><th>Publish</th><th>Quick Fix</th><th>Upside</th><th>Risk</th><th>Top Action</th><th>Report</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
  <section><h2>Needs DaVinci Fix</h2><ul>{fix_rows}</ul></section>
  <section><h2>Reject / Hold</h2><ul>{hold_rows}</ul></section>
  <section><h2>Pending Reanalysis</h2><ul>{pending_rows}</ul></section>
</main>
</body>
</html>"""


def _write_report_links(output_dir: Path, entries: list[dict]) -> str:
    path = output_dir / "reports" / "links_or_copies_to_reports.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{entry.get('filename')}\t{entry.get('html_report_path')}\t{entry.get('json_report_path')}"
        for entry in entries
        if entry.get("html_report_path") or entry.get("json_report_path")
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def write_batch_outputs(batch_id: str, input_folder: Path, output_dir: Path, entries: list[dict], counts: dict, copy_results: bool = False) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    for folder in {"publish_ready", "safe_to_test", "needs_davinci_fix", "high_upside_rework", "hold_source", "reject"}:
        (output_dir / folder).mkdir(parents=True, exist_ok=True)

    if copy_results:
        for entry in entries:
            source = Path(entry.get("file_path") or "")
            if source.exists() and source.is_file():
                copied = _copy_with_suffix(source, output_dir / bucket_folder(entry.get("portfolio_bucket")))
                entry["copied_path"] = str(copied)

    davinci_paths = export_davinci_files(entries, output_dir)
    report_links = _write_report_links(output_dir, entries)
    paths = {
        "batch_summary_json": str(output_dir / "batch_summary.json"),
        "batch_summary_csv": str(output_dir / "batch_summary.csv"),
        "batch_report_html": str(output_dir / "batch_report.html"),
        "report_links": report_links,
        **davinci_paths,
    }
    payload = _payload(batch_id, input_folder, output_dir, entries, counts, paths)
    _write_summary_csv(output_dir / "batch_summary.csv", entries)
    (output_dir / "batch_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "batch_report.html").write_text(_html_report(payload), encoding="utf-8")
    return payload


def run_batch_qc(
    input_folder: str | Path,
    *,
    force: bool = False,
    recursive: bool = False,
    copy_results: bool = False,
    output_dir: str | Path | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    db.init_db()
    folder = Path(input_folder)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Input folder not found: {folder}")

    batch_id = batch_id_now()
    files = scan_video_files(folder, recursive=recursive, limit=limit)
    output = Path(output_dir) if output_dir else project_path("data/qc_results") / batch_id
    entries: list[dict] = []
    new_count = 0
    skipped_count = 0
    analyzed_count = 0
    failed_count = 0

    for source in files:
        try:
            identity = get_clip_identity(source)
            existing = db.find_clip_by_identity(identity)
            report = db.get_latest_report_for_clip(existing["id"]) if existing else None
            report_data = _parse_report(report)
            old_schema = True if report_data is None else build_portfolio_metrics(report_data).get("old_schema", True)

            if dry_run:
                status = "would_force_reanalyze" if existing and force else ("would_skip_existing" if existing and not old_schema else "would_analyze")
                entries.append(_empty_entry(source, status))
                continue

            if existing and report and not force:
                skipped_count += 1
                entries.append(_entry_from_report(source, existing, report, "pending_reanalysis" if old_schema else "skipped_existing"))
                continue

            if existing and (force or not report):
                clip = existing
            else:
                clip = import_clip_file(source)
                new_count += 1
            result = analyze_clip(clip["id"])
            report = db.get_report(result["report_id"])
            analyzed_count += 1
            entries.append(_entry_from_report(source, db.get_clip(clip["id"]) or clip, report, "analyzed"))
        except Exception as exc:
            failed_count += 1
            entries.append(_empty_entry(source, "failed", str(exc)))

    entries.sort(
        key=lambda entry: (
            bool(entry.get("old_schema")),
            -float(entry.get("publish_priority_score") or -999),
            int(entry.get("risk_score") or 0),
            entry.get("filename") or "",
        )
    )
    for index, entry in enumerate(entries, start=1):
        entry["rank"] = index

    counts = {
        "scanned_count": len(files),
        "new_count": new_count,
        "skipped_count": skipped_count,
        "analyzed_count": analyzed_count,
        "failed_count": failed_count,
    }
    counts.update(_bucket_counts(entries))

    paths = {}
    if dry_run:
        return _payload(batch_id, folder, None, entries, counts, paths)
    return write_batch_outputs(batch_id, folder, output, entries, counts, copy_results=copy_results)


def recent_batches(limit: int = 8) -> list[dict]:
    root = project_path("data/qc_results")
    if not root.exists():
        return []
    summaries = sorted(root.glob("batch_*/batch_summary.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    output = []
    for path in summaries[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        output.append(data)
    return output
