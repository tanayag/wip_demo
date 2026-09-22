"""Export the five cases as goldens for a Confident AI dataset.

    python -m scripts.export_goldens   -> data/goldens.json and data/goldens.csv

Each golden carries `expected_tools` in Confident AI's ToolCall shape, so the platform's
deterministic Tool Correctness metric can grade the bot's `tools_called` with no code.
`lookup` is included because the bot is expected to call it. Escalations carry `team`
in input_parameters; refunds carry the amount. Reasons are free text and are left out.

Upload goldens.json (Datasets -> Upload). The CSV is a convenience copy with
expected_tools as a JSON string in one cell.
"""
from __future__ import annotations

import csv
import json
import sys

from app.config import PROJECT_DIR
from app.world import load_cases

def expected_tools(case: dict) -> list[dict]:
    """Name plus only the parameters that must match.

    The refund amount is left out on purpose: models return it as 640 or 640.0, and a
    type mismatch would fail a case that is otherwise right. `team` is kept, because
    escalating to the wrong team is exactly the failure the demo is about.
    """
    oid = case["order_id"]
    tools = [{"name": "lookup", "input_parameters": {"order_id": oid}}]
    for exp in case["expected"]:
        if exp == "refund":
            tools.append({"name": "refund", "input_parameters": {"order_id": oid}})
        elif exp == "deny":
            tools.append({"name": "deny", "input_parameters": {"order_id": oid}})
        elif exp.startswith("escalate:"):
            tools.append({"name": "escalate", "input_parameters": {"order_id": oid, "team": exp.split(":", 1)[1]}})
    return tools


def goldens() -> list[dict]:
    out = []
    for c in load_cases():
        out.append({
            "input": c["message"],
            "expected_output": c["expected_summary"],
            "expected_tools": expected_tools(c),
            "additional_metadata": {"case_id": c["id"], "order_id": c["order_id"], "expected_actions": c["expected"]},
        })
    return out


def main() -> int:
    rows = goldens()
    data = PROJECT_DIR / "data"
    with (data / "goldens.json").open("w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    with (data / "goldens.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["input", "expected_output", "expected_tools", "case_id", "order_id", "expected_actions"])
        for r in rows:
            m = r["additional_metadata"]
            w.writerow([r["input"], r["expected_output"], json.dumps(r["expected_tools"], ensure_ascii=False), m["case_id"], m["order_id"], ", ".join(m["expected_actions"])])
    print(f"wrote {len(rows)} goldens to {data / 'goldens.json'} and {data / 'goldens.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
