import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DOC_PATH = ROOT / "docs" / "verdict_to_bucket_mapping.md"

QC_VERDICTS = [
    "STRONG PUBLISH",
    "PUBLISH",
    "SAFE TO TEST",
    "REWORK",
    "HOLD",
    "REJECT",
]

FINAL_BUCKETS = [
    "publish_ready",
    "safe_to_test",
    "fixed_publish_ready",
    "fixed_safe_to_test",
    "rejected",
    "failed_fix",
    "hold_source",
    "debug_review",
]


def main() -> int:
    assert DOC_PATH.exists(), f"missing doc: {DOC_PATH}"
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "QC verdict" in text or "QC Verdicts" in text
    assert "final bucket" in text.lower() or "Routing" in text
    for verdict in QC_VERDICTS:
        assert verdict in text, f"doc should mention verdict: {verdict}"
    for bucket in FINAL_BUCKETS:
        assert bucket in text, f"doc should mention bucket: {bucket}"
    assert "auto_qc.py" in text or "_final_bucket_for_original" in text
    print("test_verdict_bucket_mapping_doc: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
