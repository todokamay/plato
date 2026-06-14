import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.audit_score_verdict_consistency import audit_report_record, audit_reports, build_audit_payload


def _record(
    raw=87.3,
    adjusted=78.3,
    raw_verdict="PUBLISH",
    cap_final="SAFE TO TEST",
    adjusted_verdict="SAFE TO TEST",
    final="SAFE TO TEST",
    source="tie",
    include_canonical=True,
    report_id="report1",
):
    report_json = {
        "report_id": report_id,
        "asset_overview": {"clip_id": "clip1", "filename": "sample.mp4"},
        "investment_score": adjusted,
        "raw_investment_score": raw,
        "adjusted_investment_score": adjusted,
        "verdict": final,
        "raw_verdict": raw_verdict,
        "cap_final_verdict": cap_final,
        "adjusted_score_verdict": adjusted_verdict,
        "final_verdict": final,
        "verdict_source": source,
        "verdict_cap": {
            "raw_verdict": raw_verdict,
            "final_verdict": cap_final,
            "cap_reasons": ["video bitrate is low at 1768 kbps"],
        },
        "edit_points": [],
        "scoring": {
            "raw_score": raw,
            "adjusted_score": adjusted,
            "total_consistency_penalty": round(max(0, raw - adjusted), 1),
            "raw_verdict": raw_verdict,
            "cap_final_verdict": cap_final,
            "adjusted_score_verdict": adjusted_verdict,
            "final_verdict": final,
            "verdict_source": source,
            "score_verdict_alignment": "aligned" if final == adjusted_verdict else "cap_limited",
            "consistency_penalties": [],
            "cap_reasons": ["video bitrate is low at 1768 kbps"],
        },
    }
    if not include_canonical:
        report_json.pop("cap_final_verdict", None)
        report_json.pop("adjusted_score_verdict", None)
        report_json.pop("final_verdict", None)
        report_json.pop("verdict_source", None)
        for field in ["cap_final_verdict", "adjusted_score_verdict", "final_verdict", "verdict_source"]:
            report_json["scoring"].pop(field, None)
    return {
        "report_id": report_id,
        "clip_id": "clip1",
        "filename": "sample.mp4",
        "report_json": report_json,
    }


def main() -> int:
    aligned = audit_report_record(_record(report_id="ok"))
    assert aligned["status"] == "ok"
    assert aligned["needs_review"] is False
    assert aligned["old_schema"] is False

    mismatch = audit_report_record(
        _record(
            adjusted=77,
            cap_final="PUBLISH",
            adjusted_verdict="SAFE TO TEST",
            final="PUBLISH",
            source="cap",
            report_id="mismatch",
        )
    )
    assert mismatch["status"] == "needs_review"
    assert any("more_conservative" in flag for flag in mismatch["flags"])

    partial_record = _record(report_id="partial")
    partial_record["report_json"]["scoring"].pop("cap_final_verdict")
    partial = audit_report_record(partial_record)
    assert partial["status"] == "needs_review"
    assert any("missing cap_final_verdict" in flag for flag in partial["flags"])

    legacy = audit_report_record(_record(include_canonical=False, report_id="legacy"))
    assert legacy["status"] == "pending_reanalysis"
    assert legacy["needs_review"] is False
    assert legacy["old_schema"] is True
    assert legacy["needs_reanalysis"] is True

    results = audit_reports(
        [
            _record(report_id="ok"),
            _record(include_canonical=False, report_id="legacy"),
            _record(
                adjusted=77,
                cap_final="PUBLISH",
                adjusted_verdict="SAFE TO TEST",
                final="PUBLISH",
                source="cap",
                report_id="mismatch",
            ),
        ]
    )
    payload = build_audit_payload(results)
    assert len(payload["ok"]) == 1
    assert len(payload["pending_reanalysis"]) == 1
    assert len(payload["needs_review"]) == 1
    assert payload["pending_reanalysis"][0]["old_schema"] is True

    encoded = json.dumps(payload, ensure_ascii=False)
    assert "sample.mp4" in encoded
    assert "Traceback" not in encoded

    print("test_consistency_audit: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
