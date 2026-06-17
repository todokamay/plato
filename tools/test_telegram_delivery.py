from pathlib import Path
import tempfile

from modules.telegram_delivery import send_video


def test_missing_env_skips():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "clip.mp4"
        path.write_bytes(b"video")
        result = send_video(path, env={})
        assert result["ok"] is False
        assert result["skipped"] is True
        assert "missing" in result["reason"]


def test_dry_run_skips_send():
    result = send_video("missing.mp4", dry_run=True, env={"PLATO_TELEGRAM_BOT_TOKEN": "x", "PLATO_TELEGRAM_CHAT_ID": "y"})
    assert result["ok"] is True
    assert result["skipped"] is True


def main():
    test_missing_env_skips()
    test_dry_run_skips_send()
    print("test_telegram_delivery: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
