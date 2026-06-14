import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DB_PATH, ensure_data_dirs, project_path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def get_connection() -> sqlite3.Connection:
    ensure_data_dirs()
    db_file = project_path(DB_PATH)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    original_filename TEXT,
    stored_filename TEXT,
    file_path TEXT,
    source_absolute_path TEXT,
    source_file_size INTEGER,
    source_modified_time TEXT,
    source_identity_key TEXT,
    file_size INTEGER,
    status TEXT,
    duration REAL,
    width INTEGER,
    height INTEGER,
    fps REAL,
    video_bitrate_kbps REAL,
    audio_bitrate_kbps REAL,
    has_audio INTEGER,
    created_at TEXT,
    updated_at TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS clip_reports (
    id TEXT PRIMARY KEY,
    clip_id TEXT,
    investment_score REAL,
    verdict TEXT,
    opening_score REAL,
    retention_score REAL,
    technical_score REAL,
    audio_score REAL,
    format_score REAL,
    risk_score REAL,
    report_json TEXT,
    html_path TEXT,
    created_at TEXT,
    FOREIGN KEY (clip_id) REFERENCES clips(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS clip_issues (
    id TEXT PRIMARY KEY,
    clip_id TEXT,
    report_id TEXT,
    issue_type TEXT,
    severity TEXT,
    priority TEXT,
    start_time REAL,
    end_time REAL,
    description TEXT,
    recommendation TEXT,
    expected_score_lift REAL,
    affected_score TEXT,
    difficulty TEXT,
    FOREIGN KEY (clip_id) REFERENCES clips(id) ON DELETE CASCADE,
    FOREIGN KEY (report_id) REFERENCES clip_reports(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS clip_frames (
    id TEXT PRIMARY KEY,
    clip_id TEXT,
    timestamp REAL,
    frame_path TEXT,
    brightness REAL,
    sharpness REAL,
    motion_score REAL,
    is_black INTEGER,
    is_static INTEGER,
    created_at TEXT,
    FOREIGN KEY (clip_id) REFERENCES clips(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_clip_reports_clip_id ON clip_reports(clip_id);
CREATE INDEX IF NOT EXISTS idx_clip_issues_report_id ON clip_issues(report_id);
CREATE INDEX IF NOT EXISTS idx_clip_frames_clip_id ON clip_frames(clip_id);
"""


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "clips", "source_absolute_path", "TEXT")
        _ensure_column(conn, "clips", "source_file_size", "INTEGER")
        _ensure_column(conn, "clips", "source_modified_time", "TEXT")
        _ensure_column(conn, "clips", "source_identity_key", "TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clips_source_identity_key ON clips(source_identity_key)")


def create_clip(
    original_filename: str,
    stored_filename: str,
    file_path: str | Path,
    file_size: int,
    status: str = "uploaded",
    source_identity: dict | None = None,
) -> dict:
    clip_id = uuid.uuid4().hex
    timestamp = now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO clips (
                id, original_filename, stored_filename, file_path,
                source_absolute_path, source_file_size, source_modified_time, source_identity_key,
                file_size,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clip_id,
                original_filename,
                stored_filename,
                str(file_path),
                (source_identity or {}).get("absolute_path"),
                (source_identity or {}).get("file_size"),
                (source_identity or {}).get("modified_time"),
                (source_identity or {}).get("identity_key"),
                int(file_size),
                status,
                timestamp,
                timestamp,
            ),
        )
    return get_clip(clip_id)


def find_clip_by_identity(identity: dict) -> dict | None:
    identity_key = identity.get("identity_key")
    absolute_path = identity.get("absolute_path")
    file_size = identity.get("file_size")
    modified_time = identity.get("modified_time")
    with get_connection() as conn:
        row = None
        if identity_key:
            row = conn.execute(
                "SELECT * FROM clips WHERE source_identity_key = ? ORDER BY created_at DESC LIMIT 1",
                (identity_key,),
            ).fetchone()
        if row is None and absolute_path:
            row = conn.execute(
                """
                SELECT * FROM clips
                WHERE source_absolute_path = ?
                  AND (source_file_size = ? OR source_file_size IS NULL)
                  AND (source_modified_time = ? OR source_modified_time IS NULL)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (absolute_path, file_size, modified_time),
            ).fetchone()
    return row_to_dict(row)


def update_clip_status(clip_id: str, status: str, error_message: str | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE clips
            SET status = ?, error_message = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, error_message, now_iso(), clip_id),
        )


def update_clip_metadata(clip_id: str, metadata: dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE clips
            SET duration = ?, width = ?, height = ?, fps = ?,
                video_bitrate_kbps = ?, audio_bitrate_kbps = ?,
                has_audio = ?, file_size = COALESCE(?, file_size),
                updated_at = ?
            WHERE id = ?
            """,
            (
                metadata.get("duration"),
                metadata.get("width"),
                metadata.get("height"),
                metadata.get("fps"),
                metadata.get("video_bitrate_kbps"),
                metadata.get("audio_bitrate_kbps"),
                1 if metadata.get("has_audio") else 0,
                metadata.get("file_size"),
                now_iso(),
                clip_id,
            ),
        )


def get_clip(clip_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return row_to_dict(row)


def list_clips(limit: int | None = None) -> list[dict]:
    sql = """
        SELECT
            c.*,
            r.id AS report_id,
            r.investment_score,
            r.verdict,
            r.created_at AS report_created_at
        FROM clips c
        LEFT JOIN clip_reports r
            ON r.id = (
                SELECT id FROM clip_reports
                WHERE clip_id = c.id
                ORDER BY created_at DESC
                LIMIT 1
            )
        ORDER BY c.created_at DESC
    """
    params: tuple[Any, ...] = ()
    if limit:
        sql += " LIMIT ?"
        params = (limit,)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [row_to_dict(row) for row in rows]


def create_report(
    report_id: str,
    clip_id: str,
    score_result: dict,
    report_json: dict,
    html_path: str,
) -> dict:
    scores = score_result.get("scores", {})
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO clip_reports (
                id, clip_id, investment_score, verdict,
                opening_score, retention_score, technical_score,
                audio_score, format_score, risk_score,
                report_json, html_path, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                clip_id,
                score_result.get("investment_score"),
                score_result.get("verdict"),
                scores.get("opening"),
                scores.get("retention"),
                scores.get("technical"),
                scores.get("audio"),
                scores.get("format"),
                scores.get("risk"),
                json.dumps(report_json, ensure_ascii=False, indent=2),
                html_path,
                now_iso(),
            ),
        )
    return get_report(report_id)


def insert_issues(clip_id: str, report_id: str, issues: list[dict]) -> None:
    with get_connection() as conn:
        for issue in issues:
            conn.execute(
                """
                INSERT INTO clip_issues (
                    id, clip_id, report_id, issue_type, severity, priority,
                    start_time, end_time, description, recommendation,
                    expected_score_lift, affected_score, difficulty
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    clip_id,
                    report_id,
                    issue.get("issue_type"),
                    issue.get("severity"),
                    issue.get("priority"),
                    issue.get("start_time"),
                    issue.get("end_time"),
                    issue.get("description"),
                    issue.get("recommendation"),
                    issue.get("expected_score_lift"),
                    issue.get("affected_score"),
                    issue.get("difficulty"),
                ),
            )


def replace_frames(clip_id: str, frames: list[dict]) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM clip_frames WHERE clip_id = ?", (clip_id,))
        for frame in frames:
            conn.execute(
                """
                INSERT INTO clip_frames (
                    id, clip_id, timestamp, frame_path, brightness, sharpness,
                    motion_score, is_black, is_static, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    clip_id,
                    frame.get("timestamp"),
                    frame.get("frame_path"),
                    frame.get("brightness"),
                    frame.get("sharpness"),
                    frame.get("motion_score"),
                    1 if frame.get("is_black") else 0,
                    1 if frame.get("is_static") else 0,
                    now_iso(),
                ),
            )


def get_report(report_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM clip_reports WHERE id = ?", (report_id,)).fetchone()
    return row_to_dict(row)


def get_latest_report_for_clip(clip_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM clip_reports
            WHERE clip_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (clip_id,),
        ).fetchone()
    return row_to_dict(row)


def get_issues_for_report(report_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM clip_issues
            WHERE report_id = ?
            ORDER BY
                CASE priority
                    WHEN 'P0' THEN 0
                    WHEN 'P1' THEN 1
                    WHEN 'P2' THEN 2
                    ELSE 3
                END,
                expected_score_lift DESC
            """,
            (report_id,),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def dashboard_stats() -> dict:
    clips = list_clips()
    analyzed = [clip for clip in clips if clip.get("investment_score") is not None]
    distribution = {
        "STRONG PUBLISH": 0,
        "PUBLISH": 0,
        "SAFE TO TEST": 0,
        "REWORK": 0,
        "HOLD": 0,
        "REJECT": 0,
        "HOLD / CLIP FIRST": 0,
    }
    for clip in analyzed:
        verdict = clip.get("verdict") or "REJECT"
        distribution[verdict] = distribution.get(verdict, 0) + 1

    average_score = None
    if analyzed:
        average_score = round(
            sum(float(clip["investment_score"]) for clip in analyzed) / len(analyzed),
            1,
        )

    ranked = sorted(analyzed, key=lambda item: item.get("investment_score") or 0, reverse=True)
    return {
        "total_clips": len(clips),
        "analyzed_clips": len(analyzed),
        "average_score": average_score,
        "distribution": distribution,
        "recent_clips": clips[:6],
        "best_clip": ranked[0] if ranked else None,
        "worst_clip": ranked[-1] if ranked else None,
    }
