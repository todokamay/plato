import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules.operator_actions import validate_operator_folder


def main() -> int:
    project = project_path(".").resolve()
    assert not validate_operator_folder(project)["ok"]

    drive_root = Path(project.anchor)
    assert not validate_operator_folder(drive_root)["ok"]

    manual = project_path("data/temp/manual_videoautopipeline_outputs")
    manual.mkdir(parents=True, exist_ok=True)
    result = validate_operator_folder(r"data\temp\manual_videoautopipeline_outputs")
    assert result["ok"], result
    assert result["folder"] == str(manual.resolve())

    empty = validate_operator_folder("")
    assert not empty["ok"]

    print("test_operator_folder_safety: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
