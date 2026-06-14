# Plato Video Lab

Deterministic local MVP for short-form video investment analysis.

## Run

```powershell
cd C:\Users\User\Desktop\Work\PlatoVideoLab
py tools\init_db.py
py app.py
```

Open:

- http://127.0.0.1:8000/
- http://127.0.0.1:8000/upload
- http://127.0.0.1:8000/clips

## CLI

```powershell
py tools\analyze_clip.py path\to\video.mp4
```

The CLI imports the source file into `data/uploads`, runs the same pipeline as the web UI, then writes JSON and HTML reports into `data/reports`.

## Scoring

Investment Score =

```text
0.25 * OpeningScore
+ 0.25 * RetentionScore
+ 0.20 * TechnicalScore
+ 0.15 * AudioScore
+ 0.15 * FormatScore
- CriticalPenalty
```

Estimated lifts are deterministic formula lifts. They are not historical performance predictions.

v0.1.1 also applies deterministic verdict caps. Low bitrate, weak opening, high/critical issues, source-format mismatch, or weak active-content area can cap a high raw score to a lower final verdict. Reports show the cap reasons and Strong Publish blockers.

Active content detection is heuristic: it estimates the meaningful visual region from sampled frames and flags pillarbox, letterbox, or small centered content without OCR or ML.

v0.2 adds a deterministic Edit Point Timeline. Each edit point includes timestamps, priority, severity, action, recommended edit, detected-by sources, and formula-based expected lift. Reports also include audio energy windows, rhythm/dead-time metrics, and before/after estimates for P0/P1 fixes.

## Limits

- No ML in v0.1.
- No OCR or subtitle safe-zone detection in v0.1.
- Credits-like/static text-card detection is heuristic.
- No automatic editing or publishing.
