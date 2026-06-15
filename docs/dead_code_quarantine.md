# Dead Code Quarantine

Ponytail audit candidates are quarantined, not deleted, until v1.2 production validation.

## Candidates

| Module | Current external references |
| --- | --- |
| `modules/auto_fix_v2.py` | None found by `rg`. |
| `modules/background_tasks.py` | None found by `rg`. |
| `modules/storage_manager.py` | Used only by quarantined `modules/background_tasks.py`. |
| `modules/portfolio_center.py` | None found by `rg`. |
| `modules/router.py` | Used by `tools/test_video_factory_os.py` only. |

## Rule

Do not remove these modules before v1.2. Run:

```powershell
py tools\dead_code_audit.py
py tools\dead_code_audit.py --json
```

If production code starts importing a quarantined module, keep it and remove the quarantine marker.
