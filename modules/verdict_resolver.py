from __future__ import annotations


CANONICAL_VERDICTS = {
    "STRONG_PUBLISH": "STRONG PUBLISH",
    "STRONG PUBLISH": "STRONG PUBLISH",
    "PUBLISH": "PUBLISH",
    "SAFE_TO_TEST": "SAFE TO TEST",
    "SAFE TO TEST": "SAFE TO TEST",
    "REWORK": "REWORK",
    "HOLD": "HOLD",
    "HOLD_CLIP_FIRST": "HOLD / CLIP FIRST",
    "HOLD / CLIP FIRST": "HOLD / CLIP FIRST",
    "REJECT": "REJECT",
}


CONSERVATIVE_RANK = {
    "STRONG PUBLISH": 0,
    "PUBLISH": 1,
    "SAFE TO TEST": 2,
    "REWORK": 3,
    "HOLD": 4,
    "HOLD / CLIP FIRST": 4,
    "REJECT": 5,
}


PUBLISHABILITY_RANK = {
    "REJECT": 0,
    "HOLD": 1,
    "HOLD / CLIP FIRST": 1.5,
    "REWORK": 2,
    "SAFE TO TEST": 3,
    "PUBLISH": 4,
    "STRONG PUBLISH": 5,
}


def normalize_verdict(verdict: str | None, default: str = "REJECT") -> str:
    value = (verdict or default or "REJECT").strip().upper().replace("-", "_")
    value = " ".join(value.split())
    value = value.replace(" / ", " / ")
    value = value.replace(" ", "_") if value not in CANONICAL_VERDICTS else value
    return CANONICAL_VERDICTS.get(value, CANONICAL_VERDICTS.get((default or "REJECT").upper(), "REJECT"))


def verdict_rank(verdict: str | None) -> int:
    return CONSERVATIVE_RANK.get(normalize_verdict(verdict), CONSERVATIVE_RANK["REJECT"])


def publishability_rank(verdict: str | None) -> float:
    return PUBLISHABILITY_RANK.get(normalize_verdict(verdict), PUBLISHABILITY_RANK["REJECT"])


def verdict_from_score(score: float | int | str | None) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        value = 0.0

    if value >= 90:
        return "STRONG PUBLISH"
    if value >= 80:
        return "PUBLISH"
    if value >= 68:
        return "SAFE TO TEST"
    if value >= 50:
        return "REWORK"
    if value >= 35:
        return "HOLD"
    return "REJECT"


def more_conservative_verdict(a: str | None, b: str | None) -> str:
    verdict_a = normalize_verdict(a)
    verdict_b = normalize_verdict(b)
    return verdict_a if verdict_rank(verdict_a) >= verdict_rank(verdict_b) else verdict_b


def _source_for(cap_final_verdict: str, adjusted_score_verdict: str, final_verdict: str) -> str:
    if cap_final_verdict == adjusted_score_verdict:
        return "tie"
    if final_verdict == adjusted_score_verdict:
        return "adjusted_score"
    return "cap"


def _reason_for(source: str, cap_reasons: list | None, consistency_penalties: list | None) -> str:
    if source == "tie":
        return "cap and adjusted score agree"
    if source == "adjusted_score":
        count = len(consistency_penalties or [])
        if count:
            return "Final verdict was downgraded because adjusted score falls into a lower verdict band."
        return "Final verdict follows the adjusted score verdict band."
    reason_count = len(cap_reasons or [])
    if reason_count:
        return "Final verdict is limited by hard cap reasons."
    return "Final verdict is limited by the cap verdict."


def resolve_final_verdict(
    raw_verdict: str | None,
    cap_final_verdict: str | None,
    adjusted_score: float | int | str | None,
    cap_reasons: list | None = None,
    consistency_penalties: list | None = None,
) -> dict:
    adjusted_score_verdict = verdict_from_score(adjusted_score)
    cap_verdict = normalize_verdict(cap_final_verdict or raw_verdict or adjusted_score_verdict)
    raw = normalize_verdict(raw_verdict or cap_verdict)
    final = more_conservative_verdict(cap_verdict, adjusted_score_verdict)
    source = _source_for(cap_verdict, adjusted_score_verdict, final)

    return {
        "raw_verdict": raw,
        "cap_final_verdict": cap_verdict,
        "adjusted_score_verdict": adjusted_score_verdict,
        "final_verdict": final,
        "verdict_source": source,
        "resolution_reason": _reason_for(source, cap_reasons, consistency_penalties),
    }
