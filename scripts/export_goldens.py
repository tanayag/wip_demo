"""Export the five cases as goldens for a Confident AI dataset upload.

    python -m scripts.export_goldens            -> data/goldens.csv and data/goldens.json

CSV columns: input, expected_output, plus custom columns case_id, order_id, expected_actions.
Leave actual_output / tools_called empty; Confident AI fills them from the AI Connection at run time.
"""
from __future__ import annotations

import csv
import json
import sys

from app.config import PROJECT_DIR
from app.world import load_cases


def goldens() -> list[dict]:
    out = []
    for c in load_cases():
        out.append({
            "input": c["message"],
            "expected_output": c["expected_summary"],
            "case_id": c["id"],
            "order_id": c["order_id"],
            "expected_actions": ", ".join(c["expected"]),
        })
    return out


def main() -> int:
    rows = goldens()
    data = PROJECT_DIR / "data"
    with (data / "goldens.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with (data / "goldens.json").open("w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print(f"wrote {len(rows)} goldens to {data / 'goldens.csv'} and {data / 'goldens.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
