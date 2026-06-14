import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.auto_fix_planner import kept_ranges_after_cuts, merge_cut_ranges, validate_cut_ranges


def main() -> int:
    merged = merge_cut_ranges([(0.0, 1.0), (0.8, 2.0), (5.0, 6.0)], 10.0)
    assert merged == [(0.0, 2.0), (5.0, 6.0)]

    kept = kept_ranges_after_cuts(merged, 10.0)
    assert kept == [(2.0, 5.0), (6.0, 10.0)]

    ok, reason = validate_cut_ranges([(12.0, 13.0)], 10.0, 1.0)
    assert not ok
    assert "outside" in reason

    ok, reason = validate_cut_ranges([(1.0, 1.0)], 10.0, 1.0)
    assert not ok
    assert "after start" in reason

    ok, reason = validate_cut_ranges([(0.0, 9.8)], 10.0, 1.0)
    assert not ok
    assert "remaining duration" in reason

    ok, reason = validate_cut_ranges([(0.0, 1.0), (9.0, 10.0)], 12.0, 8.0)
    assert ok, reason

    print("test_auto_fix_time_ranges: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
