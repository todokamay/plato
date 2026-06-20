from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.delivery_decision_explainer import explain_delivery_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain why a Plato delivery summary was approved or blocked.")
    parser.add_argument("delivery_summary", help="Path to delivery_summary.json")
    args = parser.parse_args()
    print(json.dumps(explain_delivery_summary(args.delivery_summary), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
