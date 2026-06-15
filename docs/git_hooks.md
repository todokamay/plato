# Git Hooks (optional)

Plato ships a repo safety checker at `tools/check_repo_safety.py`. You can wire
it into a local `pre-commit` git hook so that forbidden artifacts (videos,
SQLite databases, logs, `__pycache__`, generated `data/`) are rejected before
they ever reach a commit.

This hook is **entirely optional**. Plato never installs it automatically. The
checker is also run as the last step of `py tools\run_full_validation.py`, so
you get the same protection in CI / manual validation even without a hook.

## What the hook blocks

A commit is rejected when the safety checker returns non-zero, which happens if:

- the current working directory is not `C:\Users\User\Documents\plato`,
- HEAD is detached,
- `git status` cannot be read,
- or any forbidden artifact is staged for commit: `data/**`, `*.mp4`, `*.mov`,
  `*.avi`, `*.sqlite`, `*.sqlite3`, `*.log`, `logs/**`, `__pycache__/**`,
  `*.pyc`, `*.pyo`.

Plain untracked files do **not** fail the check — only staged forbidden
artifacts do.

## Setup (first time)

Create the hooks directory and the hook file:

```powershell
cd C:\Users\User\Documents\plato
mkdir .git\hooks 2>NUL
```

Create `.git\hooks\pre-commit` with this content (a plain shell script — git
runs hooks via its bundled bash on Windows, so use forward slashes and `sh`):

```sh
#!/usr/bin/env sh
# Plato pre-commit: fail if the repo safety check fails.
py tools/check_repo_safety.py
```

Mark it executable:

```powershell
git config core.hooksPath .git/hooks
attrib +x .git\hooks\pre-commit
```

> If `py` is not on PATH inside git's hook shell, invoke Python via its full
> path instead, e.g. `"/c/Python311/python.exe" tools/check_repo_safety.py`.

## Enable

The hook is active as soon as the file exists and is executable. Every
`git commit` will now run the checker first.

## Disable

To skip the hook for a single commit:

```powershell
git commit --no-verify -m "your message"
```

To disable it permanently, delete or rename the hook file:

```powershell
del .git\hooks\pre-commit
```

## Expected output

On a clean commit the hook prints the safety report and allows the commit:

```text
Plato Repo Safety Check
  PASS  working_directory
  PASS  git_work_tree
  PASS  git_status_readable
  PASS  not_detached
  PASS  no_forbidden_staged

SAFE
```

If a forbidden artifact is staged, the hook blocks the commit:

```text
Plato Repo Safety Check
  PASS  working_directory
  PASS  git_work_tree
  PASS  git_status_readable
  PASS  not_detached
  FAIL  no_forbidden_staged -- temp_test.mp4 (staged video file)

UNSAFE
```

To recover, unstage or remove the offending file and commit again:

```powershell
git reset HEAD temp_test.mp4
del temp_test.mp4
```

## Notes

- The hook is local to your clone (`.git/hooks` is not tracked by git), so each
  developer opts in independently.
- The checker never modifies the repo and never touches video originals.
- For team-wide enforcement, rely on `py tools\run_full_validation.py` in CI
  rather than on local hooks.
