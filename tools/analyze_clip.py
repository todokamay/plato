import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.pipeline import analyze_clip, import_clip_file


def main() -> int:
    if len(sys.argv) != 2:
        print(r"Usage: py tools\analyze_clip.py path\to\video.mp4")
        return 2

    source = Path(sys.argv[1])
    clip = import_clip_file(source)
    result = analyze_clip(clip["id"])
    print(f"Clip: {clip['original_filename']}")
    print(f"Status: {result['status']}")
    print(f"Investment Score: {result['score']}/100")
    print(f"Verdict: {result['verdict']}")
    print(f"JSON report: {result['report_json_path']}")
    print(f"HTML report: {result['report_html_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
