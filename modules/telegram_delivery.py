from __future__ import annotations

import json
import mimetypes
import os
import urllib.request
import uuid
from pathlib import Path


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = f"----plato-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            str(value).encode(),
            b"\r\n",
        ])
    for name, path in files.items():
        file_path = Path(path)
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"; filename="{file_path.name}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            file_path.read_bytes(),
            b"\r\n",
        ])
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def send_video(path: str | Path, caption: str = "", *, dry_run: bool = False, env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    token = env.get("PLATO_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = env.get("PLATO_TELEGRAM_CHAT_ID", "").strip()
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry run"}
    if not token or not chat_id:
        return {"ok": False, "skipped": True, "reason": "missing PLATO_TELEGRAM_BOT_TOKEN or PLATO_TELEGRAM_CHAT_ID"}
    video = Path(path)
    if not video.exists():
        return {"ok": False, "skipped": False, "reason": f"video not found: {video}"}
    body, boundary = _multipart({"chat_id": chat_id, "caption": caption[:1024]}, {"video": video})
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendVideo",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "skipped": False, "reason": str(exc)}
    return {"ok": bool(data.get("ok")), "skipped": False, "reason": "" if data.get("ok") else str(data)[:500], "response": data}
