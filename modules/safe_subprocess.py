import subprocess


def _trim(value: str, limit: int = 4000) -> str:
    if not value:
        return ""
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


def run_command(args: list[str], timeout: int = 60) -> dict:
    if not isinstance(args, list) or not args:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "error": "Command must be a non-empty list.",
        }

    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "stdout": exc.stdout or "",
            "stderr": _trim(exc.stderr or ""),
            "returncode": -1,
            "error": f"Command timed out after {timeout}s.",
        }
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "error": f"Executable not found: {exc.filename}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "error": str(exc),
        }

    return {
        "ok": completed.returncode == 0,
        "stdout": completed.stdout or "",
        "stderr": _trim(completed.stderr or ""),
        "returncode": completed.returncode,
        "error": None if completed.returncode == 0 else f"Command failed with code {completed.returncode}.",
    }
