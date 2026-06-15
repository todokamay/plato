# AGENTS.md

Canonical instructions for any coding agent (ZCode / GLM / Codex / Claude / etc.)
working in the **Plato Video Lab** repository. Read this file first, every session.

PONYTAIL MODE IS ALWAYS ON FOR CODEX AND ALL AI AGENTS.

## 1. Working directory (mandatory)

Work only in:

```
C:\Users\User\Documents\plato
```

Never use:

```
C:\Users\User\Desktop\Work\PlatoVideoLab
```

The `Desktop\Work\PlatoVideoLab` path is an **obsolete, out-of-sync copy**. Any
edit made there will be lost, will not be tested, and will not be merged. If the
current working directory is not `C:\Users\User\Documents\plato`, stop and
re-locate before doing anything else. The repo safety checker will fail if the
cwd is wrong — that is intentional.

## 2. Git workflow

The repository remote is: https://github.com/todokamay/plato

Start every task from a clean `main`:

```powershell
git checkout main
git pull origin main
git checkout -b feature/<short-descriptive-name>
```

Do work on the feature branch. Commit in small, reviewable steps with clear
messages. When the task is complete and validation is green, follow the finalize
sequence defined for the task (push branch, merge to `main`, tag if asked).

Rules:

- Never commit directly on `main` unless the task explicitly instructs a merge.
- Never use `git push --force` to `main` or to a shared branch.
- Do not amend or rewrite commits that have already been pushed.
- Keep the working tree clean: stage only the files you changed.

## 3. Test and validation commands

Before declaring work done, run from the repo root:

```powershell
py -m compileall app.py modules tools
py tools\run_tests.py
py tools\run_full_validation.py
py tools\check_repo_safety.py
```

`run_full_validation.py` runs compile, unit tests, an orchestrator dry-run, the
watch dry-run, and the factory smoke check. All steps must pass (or SKIP for
env-only reasons such as a missing `fastapi`/`cv2` install).

## 4. Commit rules

- Stage only files you intentionally changed. Prefer explicit paths over
  `git add .` when the change set is small.
- Run `py tools\check_repo_safety.py` before every commit. A non-zero exit means
  stop and clean up.
- Commit messages should start with a concise summary line, then a blank line,
  then detail if needed. Match the project's existing style.
- One logical change per commit when reasonable.

## 5. Forbidden artifacts (never commit)

The `.gitignore` already blocks these, but the safety checker enforces it at
commit time as a second line of defense. Never stage:

- `data/**` — all generated runtime data (reports, logs, queue, history, DBs).
- Video originals or outputs: `*.mp4`, `*.mov`, `*.avi`, and any other media.
- SQLite databases: `*.sqlite`, `*.sqlite3`, `*.db`.
- Logs: `*.log`, anything under `logs/`.
- Python bytecode: `__pycache__/`, `*.pyc`, `*.pyo`.
- IDE / OS metadata: `.vscode/`, `.idea/`, `Thumbs.db`, `.DS_Store`.

## 6. Safety rules for video originals

Plato's core product guarantee is that source MP4 files are **never** modified,
moved, deleted, or overwritten. As an agent:

- Never write to, rename, `rm`, `del`, or `git rm` any file under an original
  VideoAutoPipeline output folder or any operator input folder.
- Auto-fix outputs are always written as **new** files under run output folders,
  never in place.
- If a task asks you to touch an `.mp4` for any reason other than reading
  metadata, stop and confirm with the operator first.

## 7. Out-of-scope technologies (do not add unless explicitly requested)

Plato is intentionally deterministic and fully local. Do **not** introduce,
wire up, or stub any of the following unless the task explicitly asks for it:

- Machine learning models / neural networks.
- OCR.
- Whisper or any speech-to-text.
- OpenAI, Ollama, or any other LLM / chat API.
- VLM (vision-language models).
- Cloud services or remote calls.
- Auto-publishing to any platform.
- Virality prediction / engagement forecasting.
- DaVinci Resolve automation or scripting.

If a task seems to require one of these, surface the conflict rather than
implementing it.

## 8. No auto-publishing

Plato never publishes anything. Scores and lifts are deterministic formula
estimates, not performance forecasts. Do not add publishing, scheduling, or
distribution logic of any kind.

## 9. No destructive file operations

Do not run, write, or propose commands that destroy data without an explicit
task instruction, including but not limited to:

- `rm -rf`, `del /s /q`, `rmdir /s`, `format`, `git clean -fdx`.
- Recursively deleting directories you did not create.
- Emptying or truncating files you did not open for editing.
- Dropping or recreating the SQLite database (`data/app.sqlite3`) unless asked.

When in doubt, do nothing destructive and ask.

## 10. Where to look

- `README.md` — product overview and current capabilities.
- `docs/developer_quickstart.md` — setup, run, test, and cleanup instructions.
- `docs/git_hooks.md` — optional pre-commit hook using the safety checker.
- `tools/check_repo_safety.py` — the safety checker itself.
- `config.py` and `modules/` — the deterministic scoring / analysis pipeline.

When you finish a task, leave the repo in a state where
`py tools\run_full_validation.py` and `py tools\check_repo_safety.py` both pass.
