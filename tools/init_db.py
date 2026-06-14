import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import DB_PATH, ensure_data_dirs, project_path
from modules.db import init_db


if __name__ == "__main__":
    ensure_data_dirs()
    init_db()
    print(f"Database ready: {project_path(DB_PATH)}")
