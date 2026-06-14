import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules.auto_fix_executor import apply_auto_fix_plan
from modules.video_probe import probe_video
from tools.test_helpers import create_test_video


def plan(strategy, start=None, end=None):
    return {
        "can_auto_fix": True,
        "reason": "test",
        "fixes": [
            {
                "fix_id": "fix_001",
                "ffmpeg_strategy": strategy,
                "action": strategy,
                "start_time": start,
                "end_time": end,
                "priority": "P1",
                "confidence": "high",
                "expected_lift": {"investment": 5},
            }
        ],
    }


def assert_readable(path: Path):
    metadata = probe_video(str(path))
    assert metadata["ok"], metadata
    assert metadata["duration"] > 0
    return metadata


def main() -> int:
    prefix = f"auto_fix_exec_{uuid.uuid4().hex[:8]}"
    temp = project_path("data/temp") / prefix
    try:
        source = create_test_video(temp / "source.mp4", duration=3.0, audio=True, size="360x640", video_bitrate="800k")
        before = source.stat()

        re_export = temp / "re_export.mp4"
        result = apply_auto_fix_plan(source, plan("re_export"), re_export, {"min_duration_after_cut": 0.5, "timeout": 90})
        assert result["ok"], result
        assert result["input_unchanged"]
        assert_readable(re_export)

        trim_start = temp / "trim_start.mp4"
        result = apply_auto_fix_plan(source, plan("trim_start", 0, 0.5), trim_start, {"min_duration_after_cut": 0.5, "timeout": 90})
        assert result["ok"], result
        assert assert_readable(trim_start)["duration"] < assert_readable(source)["duration"]

        trim_end = temp / "trim_end.mp4"
        result = apply_auto_fix_plan(source, plan("trim_end", 2.2, 3.0), trim_end, {"min_duration_after_cut": 0.5, "timeout": 90})
        assert result["ok"], result
        assert assert_readable(trim_end)["duration"] < assert_readable(source)["duration"]

        normalized = temp / "normalized.mp4"
        result = apply_auto_fix_plan(source, plan("normalize_audio"), normalized, {"min_duration_after_cut": 0.5, "timeout": 90})
        assert result["ok"], result
        assert_readable(normalized)

        removed = temp / "removed.mp4"
        result = apply_auto_fix_plan(source, plan("remove_segment", 1.0, 1.5), removed, {"min_duration_after_cut": 0.5, "timeout": 90})
        assert result["ok"], result
        assert assert_readable(removed)["duration"] < assert_readable(source)["duration"]

        after = source.stat()
        assert before.st_size == after.st_size
        assert before.st_mtime_ns == after.st_mtime_ns

        bad_input = temp / "bad.mp4"
        bad_input.write_text("not video", encoding="utf-8")
        failed = apply_auto_fix_plan(bad_input, plan("re_export"), temp / "bad_out.mp4", {"timeout": 5})
        assert not failed["ok"]
        assert failed["error"]
        assert not (temp / "bad_out.mp4").exists()
    finally:
        if temp.exists():
            shutil.rmtree(temp)

    print("test_auto_fix_executor: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
