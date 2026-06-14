import importlib
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path


def main() -> int:
    static_dir = project_path("static")
    backup_dir = project_path(f"static_test_backup_{uuid.uuid4().hex}")

    try:
        if static_dir.exists():
            shutil.move(str(static_dir), str(backup_dir))

        assert not static_dir.exists()
        sys.modules.pop("app", None)
        importlib.import_module("app")
        assert static_dir.exists()

        if static_dir.exists():
            shutil.rmtree(static_dir)
        if backup_dir.exists():
            shutil.move(str(backup_dir), str(static_dir))

        assert static_dir.exists()
        assert (static_dir / ".gitkeep").exists()
    finally:
        sys.modules.pop("app", None)
        if static_dir.exists() and backup_dir.exists():
            shutil.rmtree(static_dir)
        if backup_dir.exists():
            shutil.move(str(backup_dir), str(static_dir))

    print("test_static_folder: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
