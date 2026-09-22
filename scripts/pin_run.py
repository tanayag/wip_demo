"""Run one objective live N times, keep the run with the most policy failures, save it
so the stage UI can show it on any browser.

    python -m scripts.pin_run --objective A --runs 5
    python -m scripts.pin_run --objective "Keep customers happy..." --runs 3 --label "room"

Pinned runs live in data/pinned/*.json and are served by GET /api/pinned. The UI merges
them into its run history, so on stage you click the pinned run, talk through it, then
press R to show that a live run can differ.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app import agent
from app.config import PROJECT_DIR
from app.world import OBJECTIVES, load_cases

PINNED = PROJECT_DIR / "data" / "pinned"


def one_run(objective: str) -> dict:
    results = {}
    for c in load_cases():
        r = agent.run_case(c["id"], objective, mode="live")
        results[c["id"]] = r
    wrong = [cid for cid, r in results.items() if not r["audit"]["correct"]]
    return {"results": results, "wrong": wrong}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--objective", default="A", help="A, B, honest, or free text")
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--label", default=None)
    args = p.parse_args()
    objective = OBJECTIVES.get(args.objective, args.objective)
    label = args.label or (args.objective if args.objective in OBJECTIVES else "custom")

    best = None
    for i in range(args.runs):
        run = one_run(objective)
        print(f"run {i+1}: {len(run['wrong'])} wrong  {', '.join(run['wrong']) or '-'}", file=sys.stderr)
        if best is None or len(run["wrong"]) > len(best["wrong"]):
            best = run
    assert best

    PINNED.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = {
        "id": f"pinned-{label}-{stamp}",
        "label": f"pinned · {label}",
        "objective": objective,
        "pinned_at": stamp,
        "mode_label": next(iter(best["results"].values()))["mode_label"],
        "wrong": best["wrong"],
        "results": {cid: agent.public(r) for cid, r in best["results"].items()},
    }
    path = PINNED / f"{out['id']}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"pinned {len(best['wrong'])}-wrong run to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
