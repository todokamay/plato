import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.frame_sampler import create_contact_sheet, planned_timestamps, sample_frames
from modules.video_probe import probe_video
from tools.test_helpers import create_test_video, temp_file


def main() -> int:
    video = create_test_video(temp_file("sampler.mp4"), duration=3, audio=False)
    metadata = probe_video(str(video))
    assert metadata["ok"], metadata

    frames = sample_frames(str(video), "test_sampler", metadata["duration"])
    successful = [frame for frame in frames if frame["ok"]]
    assert successful, frames
    assert all(Path(frame["frame_path"]).exists() for frame in successful)
    assert planned_timestamps(0.3) == [0.0]
    assert 2.0 in planned_timestamps(3.0)

    sheet = create_contact_sheet(frames)
    assert sheet and Path(sheet).exists()

    print("test_frame_sampler: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
