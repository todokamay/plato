import json
import shutil
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules.final_cleanup import cleanup_after_delivery


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def make_case(root: Path, *, delivery_status: str = "sent", sent: bool = True) -> tuple[Path, dict]:
    output_root = root / "vap_output"
    delivery_root = root / "delivery"
    job_id = "job1"
    approved = output_root / job_id / "final" / "approved.mp4"
    extra = output_root / job_id / "final" / "extra.mp4"
    state = output_root / "jobs" / job_id / "state.json"
    metadata = output_root / job_id / "metadata" / "job1.metadata.json"
    status = output_root / job_id / "status" / "job1.status.json"
    vap_temp = output_root.parent / "temp" / job_id / "raw" / "scratch.mp4"
    qc_file = delivery_root / "qc_runs" / job_id / "rejected.mp4"
    source = root / "LongVideos" / "source.mp4"
    for path in [approved, extra, state, metadata, status, vap_temp, qc_file, source]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"video")
    row = {
        "job_id": job_id,
        "source_final_path": str(extra),
        "approved_output_path": str(approved),
        "delivery_status": delivery_status,
        "telegram_status": "sent" if sent else "skipped",
        "sent": sent,
        "metadata_path": str(metadata),
        "status_path": str(status),
    }
    summary = delivery_root / "delivery_summary.json"
    write_json(summary, {"output_root": str(output_root), "jobs": [row]})
    return summary, {
        "approved": approved,
        "extra": extra,
        "state": state,
        "metadata": metadata,
        "status": status,
        "vap_temp": vap_temp,
        "qc_file": qc_file,
        "source": source,
        "delivery_root": delivery_root,
    }


def main() -> int:
    root = project_path("data/temp") / f"cleanup_{uuid.uuid4().hex[:8]}"
    cleanup_summary = project_path("data/cleanup/cleanup_summary.json")
    try:
        summary, files = make_case(root / "dry")
        result = cleanup_after_delivery(summary, mode="dry_run")
        assert result["ok"] is True
        assert str(files["extra"].resolve()) in result["planned_delete"]
        assert files["extra"].exists()
        assert cleanup_summary.exists()

        summary, files = make_case(root / "refuse")
        result = cleanup_after_delivery(summary, mode="keep_final_only")
        assert result["ok"] is False
        assert "confirm" in " ".join(result["errors"]).lower()
        assert files["extra"].exists()

        summary, files = make_case(root / "delete")
        result = cleanup_after_delivery(summary, mode="keep_final_only", confirm=True)
        assert result["ok"] is True
        assert summary.exists()
        assert files["approved"].exists()
        assert files["source"].exists()
        assert not files["extra"].exists()
        assert not files["state"].exists()
        assert files["metadata"].exists()
        assert files["status"].exists()
        assert not files["vap_temp"].exists()
        assert not files["qc_file"].exists()
        assert (cleanup_summary.parent / "jobs" / "job1.audit.json").exists()
        assert cleanup_summary.exists()

        summary, files = make_case(root / "approved_not_sent", delivery_status="approved_not_sent", sent=False)
        result = cleanup_after_delivery(summary, mode="keep_final_only", confirm=True)
        assert result["ok"] is True
        assert files["approved"].exists()
        assert not files["extra"].exists()

        summary, files = make_case(root / "rejected", delivery_status="rejected", sent=False)
        result = cleanup_after_delivery(summary, mode="keep_final_only", confirm=True)
        assert result["ok"] is False
        assert files["extra"].exists()

        unsafe_summary = root / "unsafe" / "delivery_summary.json"
        write_json(unsafe_summary, {"output_root": str(Path("C:/").resolve()), "jobs": []})
        result = cleanup_after_delivery(unsafe_summary, mode="dry_run")
        assert result["ok"] is False
        assert "Drive root" in " ".join(result["errors"])
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("test_final_cleanup: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
