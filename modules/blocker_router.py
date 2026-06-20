from __future__ import annotations


PLATO_FIX_TERMS = {
    "black frame": "black frames can be trimmed or removed by Plato",
    "black frames": "black frames can be trimmed or removed by Plato",
    "near black": "dark frames can be trimmed or removed by Plato",
    "first frame dark": "dark first frame can be trimmed by Plato",
    "dark frame": "dark frames can be trimmed or removed by Plato",
    "low motion start": "low-motion opening can be trimmed by Plato",
    "opening silence": "leading silence can be trimmed or audio-boosted by Plato",
    "dead air": "short dead air can be trimmed by Plato",
    "leading silence": "leading silence can be trimmed by Plato",
    "trailing silence": "trailing silence can be trimmed by Plato",
    "low audio": "low audio can be normalized by Plato",
    "audio too quiet": "low audio can be normalized by Plato",
    "mean audio volume is low": "low audio can be normalized by Plato",
    "low bitrate": "low bitrate can be safely re-exported by Plato",
    "very low bitrate": "low bitrate can be safely re-exported by Plato",
}

VAP_RERENDER_TERMS = {
    "unsafe banner zone": "banner-safe layout needs VideoAutoPipeline rerender",
    "subtitle overlap": "subtitle overlap needs VideoAutoPipeline rerender",
    "wrong layout": "layout issue needs VideoAutoPipeline rerender",
    "bad crop": "crop issue needs VideoAutoPipeline rerender",
    "bad cropping": "crop issue needs VideoAutoPipeline rerender",
    "davinci": "DaVinci/render issue needs VideoAutoPipeline rerender",
    "render issue": "render issue needs VideoAutoPipeline rerender",
}

MANUAL_TERMS = {
    "weak content": "content weakness is not deterministic auto-fix work",
    "poor hook": "hook weakness needs editorial review",
    "unclear speech": "unclear speech needs manual review",
    "missing context": "missing context needs editorial review",
    "low visual interest": "low visual interest needs editorial review",
}

TEXT_KEYS = {
    "reason",
    "items",
    "description",
    "issue_type",
    "recommendation",
    "recommendations",
    "failure_reason",
    "improvement_reason",
    "fix_rejection_reason",
    "top_original_issue",
    "top_remaining_issue",
    "suggested_next_action",
    "blocker_type",
}
PARENT_KEYS = {"blockers", "fix_recommendation", "issues", "clip_issues"}


def _interesting_key(key: str) -> bool:
    key = key.lower()
    return key in TEXT_KEYS or "issue" in key or "reason" in key or "recommend" in key or "blocker" in key


def _texts(value, key: str = "") -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if not key or _interesting_key(key) else []
    if isinstance(value, (int, float, bool)):
        return []
    if isinstance(value, dict):
        found: list[str] = []
        for item_key, item in value.items():
            item_key = str(item_key)
            if _interesting_key(item_key) or item_key.lower() in PARENT_KEYS:
                found.extend(_texts(item, item_key))
        return found
    if isinstance(value, (list, tuple, set)):
        found: list[str] = []
        for item in value:
            found.extend(_texts(item, key))
        return found
    return []


def _match(text: str, terms: dict[str, str]) -> tuple[str, str]:
    lowered = text.lower()
    for term, reason in terms.items():
        if term in lowered:
            return term, reason
    return "", ""


def classify_blockers(*sources) -> dict:
    text = " | ".join(_texts(list(sources))).strip()
    if not text:
        return {
            "blocker_type": "unknown",
            "route": "manual_review",
            "reason": "No blocker details were available.",
            "safe_to_attempt": False,
        }

    term, reason = _match(text, VAP_RERENDER_TERMS)
    if term:
        return {
            "blocker_type": term,
            "route": "vap_rerender",
            "reason": reason,
            "safe_to_attempt": False,
        }

    term, reason = _match(text, PLATO_FIX_TERMS)
    if term:
        return {
            "blocker_type": term,
            "route": "plato_fix",
            "reason": reason,
            "safe_to_attempt": True,
        }

    term, reason = _match(text, MANUAL_TERMS)
    if term:
        return {
            "blocker_type": term,
            "route": "manual_review",
            "reason": reason,
            "safe_to_attempt": False,
        }

    return {
        "blocker_type": "unknown",
        "route": "manual_review",
        "reason": "No safe automatic route matched these blockers.",
        "safe_to_attempt": False,
    }
