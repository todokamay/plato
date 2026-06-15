# Verdict Vocabulary vs Routing Buckets

Plato uses **two related but distinct vocabularies** when deciding what to do with a clip after QC. This document explains why both exist, where each is produced, and how they map to one another.

## Why Two Vocabularies?

| Layer | Vocabulary | Purpose |
|-------|------------|---------|
| **QC verdicts** | Human-readable score bands (`STRONG PUBLISH`, `PUBLISH`, …) | Describe clip quality after deterministic scoring and consistency caps. Used in reports, UI, and fix-evaluation logic. |
| **Routing / final buckets** | Machine-oriented folder names (`publish_ready`, `safe_to_test`, …) | Route outputs into run folders for operator review, copying, and downstream workflows. |

QC verdicts answer *"how good is this clip?"* Final buckets answer *"where should this file land in the run output tree?"*

The verdict layer is **score-centric**; the bucket layer is **workflow-centric** (original vs fixed, copy targets, failure handling).

## QC Verdicts

Canonical verdicts (from `modules/verdict_resolver.py` and `modules/scoring.py`):

| Verdict | Typical score band | Meaning |
|---------|-------------------|---------|
| `STRONG PUBLISH` | ≥ 90 | Top band; strong publish candidate after caps |
| `PUBLISH` | 80–89 | Publish candidate, subject to human review |
| `SAFE TO TEST` | 68–79 | Reasonable to test; not scarce-slot publish |
| `REWORK` | 50–67 | Needs improvement before spending a slot |
| `HOLD` | 35–49 | Source material; clip or hold |
| `REJECT` | < 35 | Do not publish this version |

### Where QC verdicts are produced

1. **Raw score band** — `modules/scoring.py` → `verdict_for_score()` maps adjusted investment score to a band.
2. **Consistency caps** — `modules/score_consistency.py` may downgrade verdicts based on opening score, bitrate, P0 edit points, and other blockers.
3. **Canonical final verdict** — `modules/verdict_resolver.py` → `resolve_final_verdict()` picks the more conservative of cap vs adjusted-score verdicts.
4. **Reports** — `modules/report_generator.py` surfaces `raw_verdict`, `cap_final_verdict`, `adjusted_score_verdict`, and `final_verdict` in JSON/HTML output.

Verdicts appear in SQLite clip reports and batch/auto-QC CSV rows as `original_final_verdict` / `fixed_final_verdict`.

## Portfolio Buckets (Intermediate)

Before final routing, batch QC and auto-QC also assign **portfolio buckets** (`modules/portfolio_ranking.py`):

- `Publish Candidate`
- `Safe Test`
- `Quick Fix`
- `High Upside Rework`
- `Hold / Source Material`
- `Reject`

These combine verdict, adjusted score, P0/P1 burden, and alignment flags into an operator-facing priority label. They are **not** the same as final routing buckets, but they drive the mapping below.

## Final Routing Buckets

Defined in `modules/auto_qc.py` → `FINAL_BUCKETS` and `modules/router.py`:

| Final bucket | Typical use |
|--------------|-------------|
| `publish_ready` | Original passed QC; publish-band portfolio bucket |
| `safe_to_test` | Original is safe-test band |
| `fixed_publish_ready` | Auto-fix accepted; fixed verdict is `STRONG PUBLISH` or `PUBLISH` |
| `fixed_safe_to_test` | Auto-fix accepted; fixed verdict is `SAFE TO TEST` |
| `rejected` | Original or fixed verdict is `REJECT`, or source was rejected |
| `failed_fix` | Fix attempted but fixed output did not reach publish/safe band |
| `hold_source` | Original is hold/source material |
| `debug_review` | Rework / quick-fix / high-upside clips needing manual review |

### Where final buckets are assigned

- **Original clips** — `modules/auto_qc.py` → `_final_bucket_for_original()` maps portfolio bucket → final bucket.
- **Fixed clips** — `modules/auto_qc.py` → `_final_bucket_for_fixed()` maps fixed verdict (+ original reject state) → final bucket.
- **Copy routing** — `modules/router.py` copies files into bucket subfolders when `--copy-results` is enabled.

Implementation reference:

```334:354:modules/auto_qc.py
def _final_bucket_for_original(bucket: str) -> str:
    if bucket == BUCKET_PUBLISH:
        return "publish_ready"
    if bucket == BUCKET_SAFE:
        return "safe_to_test"
    if bucket == BUCKET_REJECT:
        return "rejected"
    if bucket == BUCKET_HOLD:
        return "hold_source"
    return "debug_review"


def _final_bucket_for_fixed(fixed_verdict: str | None, original_bucket: str) -> str:
    verdict = fixed_verdict or "REJECT"
    if verdict in {"STRONG PUBLISH", "PUBLISH"}:
        return "fixed_publish_ready"
    if verdict == "SAFE TO TEST":
        return "fixed_safe_to_test"
    if verdict == "REJECT" or original_bucket == BUCKET_REJECT:
        return "rejected"
    return "failed_fix"
```

## Expected Mapping Rules

### Original clip (no accepted fix)

| Portfolio bucket | Typical verdict range | Final bucket |
|------------------|----------------------|--------------|
| Publish Candidate | `STRONG PUBLISH`, `PUBLISH` | `publish_ready` |
| Safe Test | `SAFE TO TEST` | `safe_to_test` |
| Reject | `REJECT` | `rejected` |
| Hold / Source Material | `HOLD`, `HOLD / CLIP FIRST` | `hold_source` |
| Quick Fix, High Upside Rework | `REWORK` (often) | `debug_review` |

`REWORK` does not map to its own final bucket; rework clips land in `debug_review` unless auto-fix later promotes them.

### After auto-fix (fix accepted)

| Fixed final verdict | Final bucket |
|---------------------|--------------|
| `STRONG PUBLISH`, `PUBLISH` | `fixed_publish_ready` |
| `SAFE TO TEST` | `fixed_safe_to_test` |
| `REJECT` | `rejected` |
| `REWORK`, `HOLD`, or insufficient improvement | `failed_fix` |

If the original was already in the Reject portfolio bucket, fixed outputs route to `rejected` regardless of fixed verdict.

## Examples

### Example 1 — Strong original, no fix

- Adjusted score: 91 → `final_verdict`: `STRONG PUBLISH`
- Portfolio bucket: `Publish Candidate`
- **Final bucket:** `publish_ready`

### Example 2 — Rework original, successful fix

- Original: score 58 → `REWORK` → portfolio `Quick Fix` → `debug_review` (pre-fix)
- Auto-fix accepted; fixed score 72 → `SAFE TO TEST`
- **Final bucket:** `fixed_safe_to_test`

### Example 3 — Safe original, fix does not help enough

- Original: `SAFE TO TEST` → `safe_to_test` (if no fix path taken)
- Fix attempted but fixed verdict stays `REWORK`
- **Final bucket:** `failed_fix`

### Example 4 — Rejected source

- Original: score 20 → `REJECT` → `rejected`
- Any fix attempt on rejected source
- **Final bucket:** `rejected`

## Related Documentation

- Batch QC portfolio buckets: `README.md` → Current Capabilities
- Config profiles for orchestrator runs: [`docs/config_profiles.md`](config_profiles.md)
- Cap/consistency audit: [`docs/cap_consistency_audit.md`](cap_consistency_audit.md)
