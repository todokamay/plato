"""Plato repo safety checker.

Verifies that a coding agent is operating in the canonical Plato repository and
that no forbidden artifacts (videos, SQLite databases, logs, Python bytecode,
generated data) are staged for commit. Intended to be safe to run from anywhere,
including outside a git work tree, and never raises on git failures.

CLI:
    py tools\\check_repo_safety.py
    py tools\\check_repo_safety.py --json

Exit code:
    0  -> repository is safe
    1  -> one or more safety checks failed
    2  -> could not even determine safety (bad arguments, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable

# Canonical working tree. Overridable for tests via the PLATO_REPO_ROOT env var
# or the expected_root keyword to check_repo().
CANONICAL_REPO_ROOT = r"C:\Users\User\Documents\plato"

# Video originals and local databases must never be committed.
FORBIDDEN_VIDEO_SUFFIXES = (".mp4", ".mov", ".avi")
FORBIDDEN_DB_SUFFIXES = (".sqlite", ".sqlite3")
FORBIDDEN_BYTECODE_SUFFIXES = (".pyc", ".pyo")
FORBIDDEN_LOG_SUFFIX = ".log"

# Protected top-level generated locations.
FORBIDDEN_DIR_SEGMENTS = ("data", "__pycache__", "logs")

# Exit codes.
EXIT_SAFE = 0
EXIT_UNSAFE = 1
EXIT_ERROR = 2


def _run_git(args: list[str], cwd: Path) -> tuple[bool, str]:
    """Run a git command, returning (ok, stdout). Never raises."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        # git is not installed.
        return False, ""
    except Exception:
        return False, ""
    return completed.returncode == 0, completed.stdout or ""


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def classify_staged_path(path: str) -> str | None:
    """Return a human-readable reason if ``path`` is a forbidden staged artifact.

    Returns None when the path is allowed. Pure function so tests can exercise it
    directly without touching git.
    """
    normalized = _normalize(path)
    if not normalized:
        return None
    lower = normalized.lower()

    # Generated data tree (covers data/reports, data/logs, data/*.sqlite3, ...).
    if lower == "data" or lower.startswith("data/"):
        return "staged generated data/ artifact"

    # Python bytecode caches.
    if "__pycache__" in lower:
        return "staged __pycache__ directory"
    if lower.endswith(FORBIDDEN_BYTECODE_SUFFIXES):
        return "staged Python bytecode file"

    # Video originals / outputs.
    if lower.endswith(FORBIDDEN_VIDEO_SUFFIXES):
        return "staged video file"

    # Local SQLite databases.
    if lower.endswith(FORBIDDEN_DB_SUFFIXES):
        return "staged SQLite database"

    # Logs.
    if lower.endswith(FORBIDDEN_LOG_SUFFIX):
        return "staged log file"
    parts = lower.split("/")
    if "logs" in parts:
        return "staged logs/ artifact"

    return None


def _same_path(a: Path, b: Path) -> bool:
    a_str = str(a)
    b_str = str(b)
    if os.name == "nt":
        return a_str.lower() == b_str.lower()
    return a_str == b_str


def _staged_forbidden(paths: Iterable[str]) -> list[dict]:
    findings: list[dict] = []
    for raw in paths:
        raw = raw.strip()
        if not raw:
            continue
        reason = classify_staged_path(raw)
        if reason:
            findings.append({"path": raw, "reason": reason})
    return findings


def check_repo(cwd: str | os.PathLike | None = None, expected_root: str | None = None) -> dict:
    """Run all safety checks and return a structured result dict.

    The returned dict has the shape::

        {
            "ok": bool,
            "checks": [{"name": str, "ok": bool, "detail": str}, ...],
            "staged_forbidden": [{"path": str, "reason": str}, ...],
        }
    """
    cwd_path = Path(cwd).resolve() if cwd is not None else Path(os.getcwd()).resolve()
    expected = expected_root or os.environ.get("PLATO_REPO_ROOT", CANONICAL_REPO_ROOT)
    expected_path = Path(expected).resolve()

    result: dict = {"ok": True, "checks": [], "staged_forbidden": []}

    def add(name: str, ok: bool, detail: str = "") -> None:
        # Only surface detail when it is informative: failing checks explain why,
        # and a few checks note the relevant directory/path even on success.
        result["checks"].append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            result["ok"] = False

    # 1. Working directory must be the canonical Plato repo.
    add(
        "working_directory",
        _same_path(cwd_path, expected_path),
        f"cwd={cwd_path} expected={expected_path}",
    )

    # 2. git must be reachable and we must be inside a work tree.
    inside, _ = _run_git(["rev-parse", "--is-inside-work-tree"], cwd_path)
    add("git_work_tree", inside, "" if inside else "not inside a git work tree")

    # 3. git status must be readable.
    status_ok, status_out = _run_git(["status", "--porcelain"], cwd_path)
    add("git_status_readable", status_ok, "" if status_ok else "git status could not be read")

    # 4. Branch must not be detached (HEAD must point at a branch).
    branch_ok, branch_out = _run_git(["branch", "--show-current"], cwd_path)
    detached = branch_ok and not branch_out.strip()
    add("not_detached", branch_ok and not detached, "detached HEAD" if detached else "")

    # 5. No forbidden artifacts staged for commit.
    staged_forbidden: list[dict] = []
    if inside:
        diff_ok, diff_out = _run_git(
            ["diff", "--cached", "--name-only", "--no-renames", "-z"], cwd_path
        )
        if diff_ok:
            staged_forbidden = _staged_forbidden(diff_out.split("\0"))
        else:
            # Fall back to porcelain parsing if -z form is unavailable.
            staged_forbidden = _staged_forbidden(status_out.splitlines())
    add(
        "no_forbidden_staged",
        not staged_forbidden,
        "; ".join(f"{f['path']} ({f['reason']})" for f in staged_forbidden),
    )

    result["staged_forbidden"] = staged_forbidden
    return result


def format_report(result: dict) -> str:
    lines = ["Plato Repo Safety Check"]
    for check in result["checks"]:
        mark = "PASS" if check["ok"] else "FAIL"
        line = f"  {mark}  {check['name']}"
        if not check["ok"] and check["detail"]:
            line += f" -- {check['detail']}"
        lines.append(line)
    lines.append("")
    lines.append("SAFE" if result["ok"] else "UNSAFE")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Plato repo safety for coding agents.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a text report.")
    parser.add_argument(
        "--cwd",
        default=None,
        help="Working directory to check (defaults to the current directory).",
    )
    args = parser.parse_args(argv)

    try:
        result = check_repo(cwd=args.cwd)
    except Exception as exc:  # pragma: no cover - defensive
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(f"check_repo_safety: error: {exc}")
        return EXIT_ERROR

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_report(result))
    return EXIT_SAFE if result["ok"] else EXIT_UNSAFE


if __name__ == "__main__":
    raise SystemExit(main())
