"""Tests for tools/check_repo_safety.py.

Covers:
  - safe repository passes
  - staged forbidden .mp4 is flagged (via a temp git repo + monkeypatched git)
  - staged forbidden data file is flagged (pure classify_staged_path unit)
  - outside a git repo does not traceback
  - --json emits valid JSON
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tools.check_repo_safety as crs  # noqa: E402


# --- pure unit checks on classify_staged_path -------------------------------


def test_classify_allows_source_files() -> None:
    assert crs.classify_staged_path("app.py") is None
    assert crs.classify_staged_path("modules/scoring.py") is None
    assert crs.classify_staged_path("templates/operator_wizard.html") is None
    assert crs.classify_staged_path("tools/check_repo_safety.py") is None


def test_classify_flags_video() -> None:
    reason = crs.classify_staged_path("temp_test.mp4")
    assert reason == "staged video file"
    # Backslash form (Windows porcelain) should also be caught.
    assert crs.classify_staged_path("data\\temp\\clip.mp4") is not None


def test_classify_flags_data_tree() -> None:
    assert crs.classify_staged_path("data") is not None
    assert crs.classify_staged_path("data/app.sqlite3") is not None
    assert crs.classify_staged_path("data/reports/abc.json") is not None
    # Backslash form.
    assert crs.classify_staged_path("data\\logs\\run.log") is not None


def test_classify_flags_db_pyc_pycache_log() -> None:
    assert crs.classify_staged_path("app.sqlite") is not None
    assert crs.classify_staged_path("app.sqlite3") is not None
    assert crs.classify_staged_path("__pycache__/mod.cpython-311.pyc") is not None
    assert crs.classify_staged_path("modules/__pycache__/x.pyc") is not None
    assert crs.classify_staged_path("run.log") is not None
    assert crs.classify_staged_path("logs/2026-06-15.log") is not None


# --- integration: real temp git repo ---------------------------------------


def _git_available() -> bool:
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True,
            check=False,
        )
        return True
    except FileNotFoundError:
        return False


def _make_temp_repo() -> Path:
    repo = Path(tempfile.mkdtemp(prefix="plato_safety_"))
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "Plato Test"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "test@example.com"
    for args in (["init", "-q"], ["config", "user.name", "Plato Test"],
                 ["config", "user.email", "test@example.com"]):
        subprocess.run(["git", *args], cwd=str(repo), capture_output=True, check=True, env=env)
    (repo / "README.md").write_text("temp repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo),
                   capture_output=True, check=True, env=env)
    subprocess.run(["git", "checkout", "-q", "-b", "test-branch"], cwd=str(repo),
                   capture_output=True, check=True, env=env)
    return repo


def test_safe_repo_passes() -> None:
    # check_repo on the real Plato root with expected_root overridden must pass.
    result = crs.check_repo(cwd=ROOT, expected_root=str(ROOT))
    assert result["ok"], result
    names = {c["name"]: c["ok"] for c in result["checks"]}
    assert names["no_forbidden_staged"] is True


def test_staged_mp4_fails() -> None:
    if not _git_available():
        print("test_staged_mp4_fails: SKIP - git not installed")
        return
    repo = _make_temp_repo()
    try:
        (repo / "temp_test.mp4").write_bytes(b"\x00\x00\x00 ftypisom")
        subprocess.run(["git", "add", "temp_test.mp4"], cwd=str(repo),
                       capture_output=True, check=True)
        result = crs.check_repo(cwd=repo, expected_root=str(repo))
        assert not result["ok"], result
        forbidden = result["staged_forbidden"]
        assert any(p["path"].endswith("temp_test.mp4") for p in forbidden), forbidden
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_staged_data_file_fails() -> None:
    if not _git_available():
        print("test_staged_data_file_fails: SKIP - git not installed")
        return
    repo = _make_temp_repo()
    try:
        (repo / "data").mkdir(exist_ok=True)
        (repo / "data" / "app.sqlite3").write_bytes(b"SQLite format 3\x00")
        subprocess.run(["git", "add", "data/app.sqlite3"], cwd=str(repo),
                       capture_output=True, check=True)
        result = crs.check_repo(cwd=repo, expected_root=str(repo))
        assert not result["ok"], result
        assert result["staged_forbidden"], result["staged_forbidden"]
        assert any("data" in p["path"] for p in result["staged_forbidden"])
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# --- non-git + JSON ---------------------------------------------------------


def test_outside_git_does_not_traceback() -> None:
    # A plain temp dir with no .git should not raise and should report unsafe
    # because the git_work_tree / status checks cannot succeed.
    non_git = Path(tempfile.mkdtemp(prefix="plato_notgit_"))
    try:
        result = crs.check_repo(cwd=non_git, expected_root=str(non_git))
        names = {c["name"]: c for c in result["checks"]}
        assert names["git_work_tree"]["ok"] is False
        assert names["git_status_readable"]["ok"] is False
        assert result["ok"] is False
    finally:
        shutil.rmtree(non_git, ignore_errors=True)


def test_json_output_is_valid() -> None:
    # Drive main() with --json, capturing stdout; must be valid JSON with an "ok" key.
    rc, out = _run_cli(["--json", "--cwd", str(ROOT)])
    payload = json.loads(out)
    assert "ok" in payload and "checks" in payload
    assert rc == 0


def _run_cli(argv: list[str]) -> tuple[int, str]:
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = crs.main(argv)
    return rc, buf.getvalue()


def main() -> int:
    tests = [
        test_classify_allows_source_files,
        test_classify_flags_video,
        test_classify_flags_data_tree,
        test_classify_flags_db_pyc_pycache_log,
        test_safe_repo_passes,
        test_staged_mp4_fails,
        test_staged_data_file_fails,
        test_outside_git_does_not_traceback,
        test_json_output_is_valid,
    ]
    failures = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001 - test runner reports failures
            failures += 1
            print(f"FAIL {fn.__name__}: {exc!r}")

    print()
    print(f"test_repo_safety: {len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
