import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.verdict_resolver import (
    more_conservative_verdict,
    resolve_final_verdict,
    verdict_from_score,
    verdict_rank,
)


def main() -> int:
    result = resolve_final_verdict("PUBLISH", "PUBLISH", 77, [], [])
    assert result["adjusted_score_verdict"] == "SAFE TO TEST"
    assert result["final_verdict"] == "SAFE TO TEST"
    assert result["verdict_source"] == "adjusted_score"

    result = resolve_final_verdict("PUBLISH", "REWORK", 85, ["opening score is 55"], [])
    assert result["adjusted_score_verdict"] == "PUBLISH"
    assert result["final_verdict"] == "REWORK"
    assert result["verdict_source"] == "cap"

    result = resolve_final_verdict("PUBLISH", "SAFE TO TEST", 78, ["video bitrate is low"], [])
    assert result["adjusted_score_verdict"] == "SAFE TO TEST"
    assert result["final_verdict"] == "SAFE TO TEST"
    assert result["verdict_source"] == "tie"

    result = resolve_final_verdict("PUBLISH", "PUBLISH", 62, [], [])
    assert result["adjusted_score_verdict"] == "REWORK"
    assert result["final_verdict"] == "REWORK"
    assert result["verdict_source"] == "adjusted_score"

    upgraded = resolve_final_verdict("PUBLISH", "REWORK", 95, ["hard cap"], [])
    assert upgraded["final_verdict"] == "REWORK"
    assert upgraded["verdict_source"] == "cap"

    assert verdict_rank("STRONG PUBLISH") < verdict_rank("PUBLISH")
    assert verdict_rank("PUBLISH") < verdict_rank("SAFE TO TEST")
    assert verdict_rank("SAFE TO TEST") < verdict_rank("REWORK")
    assert verdict_rank("REWORK") < verdict_rank("HOLD")
    assert verdict_rank("HOLD") < verdict_rank("REJECT")
    assert more_conservative_verdict("PUBLISH", "REWORK") == "REWORK"
    assert verdict_from_score(68) == "SAFE TO TEST"

    print("test_verdict_resolver: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
