# ponytail: quarantine candidate; keep until v1.2 after production validation.
from __future__ import annotations

from pathlib import Path

from modules.auto_qc import run_auto_qc_fix


SAFE_FIXES = {"trim", "normalize_audio", "re_export", "remove_segment"}


def run_auto_fix_v2(
    input_folder: str | Path,
    *,
    passes: int = 2,
    output_dir: str | Path | None = None,
    copy_results: bool = True,
    allow_original_short: bool = True,
    short_clip_min_duration: float = 5.0,
) -> dict:
    current_folder = Path(input_folder)
    pass_results = []
    for index in range(1, max(1, passes) + 1):
        pass_output = Path(output_dir) / f"pass_{index}" if output_dir else None
        result = run_auto_qc_fix(
            current_folder,
            auto_fix=True,
            copy_results=copy_results,
            output_dir=pass_output,
            allow_original_short=allow_original_short,
            short_clip_min_duration=short_clip_min_duration,
            force=True,
        )
        pass_results.append(result)
        fixed = [Path(row.get("fixed_path")) for row in result.get("clips", []) if row.get("fix_accepted") and row.get("fixed_path")]
        if not fixed:
            break
        current_folder = fixed[0].parent
    accepted = sum((result.get("counts") or {}).get("accepted_fix_count", 0) for result in pass_results)
    return {"passes": pass_results, "accepted_fix_count": accepted, "safe_fixes": sorted(SAFE_FIXES), "rollback": "originals untouched"}
