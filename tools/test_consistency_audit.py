import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.audit_score_verdict_consistency import audit_report_record, audit_reports, build_audit_payload


def _record(raw=90, adjusted=85, final="SAFE TO TEST", penalty=5, alignment="major_gap", cap_reasons=None, include_consistency=True, report_id="report1"):
    report_json = {
        "report_id": report_id,
        "asset_overview": {"clip_id": "clip1", "filename": "sample.mp4"},
        "investment_score": adjusted,
        "raw_investment_score": raw,
        "verdict": final,
        "raw_verdict": "STRONG PUBLISH" if raw >= 90 else "PUBLISH",
        "edit_points": [],
    }
    if include_consistency:
        report_json["adjusted_investment_score"] = adjusted
        report_json["scoring"] = {
            "raw_score": raw,
            "adjusted_score": adjusted,
            "total_consistency_penalty": penalty,
            "raw_verdict": "STRONG PUBLISH" if raw >= 90 else "PUBLISH",
            "final_verdict": final,
            "score_verdict_alignment": alignment,
            "consistency_penalties": [],
            "cap_reasons": cap_reasons if cap_reasons is not None else ["video bitrate is low at 1768 kbps"],
        }
    return {
        "report_id": report_id,
        "clip_id": "clip1",
        "filename": "sample.mp4",
        "report_json": report_json,
    }


def main() -> int:
    confusing = audit_report_record(_record(raw=90, adjusted=85, final="SAFE TO TEST", alignment="major_gap"))
    assert confusing["needs_review"] is True
    assert any("adjusted remains >=80" in flag for flag in confusing["flags"])

    aligned = audit_report_record(_record(raw=90, adjusted=78, final="SAFE TO TEST", penalty=12, alignment="aligned"))
    assert aligned["needs_review"] is False

    tiny_penalty = audit_report_record(_record(raw=88, adjusted=87.5, final="SAFE TO TEST", penalty=0.5, alignment="major_gap"))
    assert tiny_penalty["needs_review"] is True
    assert any("total penalty <2" in flag for flag in tiny_penalty["flags"])

    legacy = audit_report_record(_record(raw=88, adjusted=88, final="SAFE TO TEST", penalty=0, alignment="major_gap", include_consistency=False))
    assert legacy["status"] == "pending_reanalysis"
    assert legacy["needs_review"] is False

    cap_only = audit_report_record(_record(raw=91, adjusted=91, final="PUBLISH", penalty=0, alignment="cap_only_gap"))
    assert cap_only["status"] == "needs_review"
    assert any("zero consistency penalty" in flag for flag in cap_only["flags"])

    results = audit_reports(
        [
            _record(raw=90, adjusted=78, final="SAFE TO TEST", penalty=12, alignment="aligned_with_penalty", report_id="ok"),
            _record(raw=88, adjusted=88, final="SAFE TO TEST", penalty=0, alignment="major_gap", include_consistency=False, report_id="legacy"),
            _record(raw=91, adjusted=91, final="PUBLISH", penalty=0, alignment="cap_only_gap", report_id="cap_only"),
        ]
    )
    audit_payload = build_audit_payload(results)
    assert "pending_reanalysis" in audit_payload
    assert "needs_review" in audit_payload
    pending_ids = {item["report_id"] for item in audit_payload["pending_reanalysis"]}
    review_ids = {item["report_id"] for item in audit_payload["needs_review"]}
    assert pending_ids.isdisjoint(review_ids)
    assert len(audit_payload["pending_reanalysis"]) == 1
    assert len(audit_payload["needs_review"]) == 1

    payload = build_audit_payload(audit_reports([_record(raw=90, adjusted=78, final="SAFE TO TEST", penalty=12, alignment="aligned_with_penalty")]))
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "sample.mp4" in encoded
    assert "Traceback" not in encoded

    print("test_consistency_audit: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
