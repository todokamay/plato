import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.davinci_export import seconds_to_timecode


def main() -> int:
    assert seconds_to_timecode(0.0, 30) == "00:00:00:00"
    assert seconds_to_timecode(0.5, 30) == "00:00:00:15"
    assert seconds_to_timecode(65.0, 30) == "00:01:05:00"
    assert seconds_to_timecode(1.0, None) == "00:00:01:00"
    assert seconds_to_timecode(1.0, 0) == "00:00:01:00"
    print("test_timecode: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
