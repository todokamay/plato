from __future__ import annotations

import json
import tempfile
from pathlib import Path

from tools.dead_code_audit import audit, format_text


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root, "modules/router.py", "def copy_to_bucket(): pass\n")
        write(root, "tools/test_video_factory_os.py", "from modules.router import copy_to_bucket\ncopy_to_bucket()\n")
        write(root, "modules/background_tasks.py", "from modules.storage_manager import cleanup_generated_files\n")
        write(root, "modules/storage_manager.py", "def cleanup_generated_files(): pass\n")

        payload = audit(root)
        assert payload["candidate_count"] == 5
        assert payload["candidates"]["modules/router.py"]["reference_count"] == 1
        assert payload["candidates"]["modules/storage_manager.py"]["reference_count"] == 1
        assert payload["candidates"]["modules/auto_fix_v2.py"]["reference_count"] == 0
        assert "modules/router.py: 1 reference file(s)" in format_text(payload)
        json.dumps(payload)

    print("test_dead_code_audit: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
