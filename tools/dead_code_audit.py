from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


QUARANTINE_CANDIDATES = {
    "modules/auto_fix_v2.py": ["modules.auto_fix_v2", "run_auto_fix_v2"],
    "modules/background_tasks.py": ["modules.background_tasks", "heartbeat", "maintenance"],
    "modules/storage_manager.py": [
        "modules.storage_manager",
        "directory_size",
        "archive_copy",
        "cleanup_generated_files",
    ],
    "modules/portfolio_center.py": ["modules.portfolio_center", "leaderboards"],
    "modules/router.py": ["modules.router", "copy_to_bucket", "route_auto_qc_row"],
}

SKIP_PARTS = {".git", "__pycache__", "data", "logs"}
SKIP_FILES = {"tools/dead_code_audit.py", "tools/test_dead_code_audit.py"}


def _repo_files(root: Path) -> list[Path]:
    files = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel in SKIP_FILES or any(part in SKIP_PARTS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def _matches(text: str, tokens: list[str]) -> list[str]:
    found = []
    for token in tokens:
        pattern = re.escape(token) if "." in token else rf"\b{re.escape(token)}\b"
        if re.search(pattern, text):
            found.append(token)
    return found


def audit(root: str | Path = ".") -> dict:
    root = Path(root).resolve()
    files = _repo_files(root)
    candidates = {}
    for rel, tokens in QUARANTINE_CANDIDATES.items():
        refs = []
        for path in files:
            path_rel = path.relative_to(root).as_posix()
            if path_rel == rel:
                continue
            found = _matches(path.read_text(encoding="utf-8", errors="ignore"), tokens)
            if found:
                refs.append({"path": path_rel, "tokens": found})
        candidates[rel] = {"tokens": tokens, "references": refs, "reference_count": len(refs)}
    return {"ok": True, "candidate_count": len(candidates), "candidates": candidates}


def format_text(payload: dict) -> str:
    lines = ["Dead Code Quarantine Audit"]
    for module, data in payload["candidates"].items():
        lines.append(f"{module}: {data['reference_count']} reference file(s)")
        for ref in data["references"]:
            lines.append(f"  {ref['path']}: {', '.join(ref['tokens'])}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit references to quarantined dead-code candidates.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument("--root", default=".", help="Repository root.")
    args = parser.parse_args()
    payload = audit(args.root)
    print(json.dumps(payload, indent=2) if args.json else format_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
