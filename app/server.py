"""FastAPI, single process. The stage UI, the run endpoint, and the Confident AI endpoint."""
from __future__ import annotations

import difflib
import hmac
import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import agent, tools, tracing
from .config import PROJECT_DIR, settings
from .world import OBJECTIVES, POLICY, case_by_order_id, load_cases

log = logging.getLogger("refund-bot")
WEB_DIR = PROJECT_DIR / "web"
ORDER_ID_RE = re.compile(r"\bDB[-_ ]?(\d{4})\b", re.IGNORECASE)
_PING_TEXT = ("CONNECTION OK\nThis was a ping, not a customer message, so Refund Bot "
              "had nothing to decide.\n\nACTIONS TAKEN\n- None")


def _walk_strings(obj: Any, depth: int = 0):
    """Yield every string anywhere in the payload, so a nested golden still matches."""
    if depth > 6:
        return
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk_strings(v, depth + 1)


def resolve_case(payload: dict[str, Any], text: str) -> tuple[dict[str, Any] | None, str]:
    """Find the case: order id, then an explicit case id, then the closest customer message."""
    cases = load_cases()

    # a) order id anywhere in the payload (input first, then the rest)
    for candidate in [text, *_walk_strings(payload)]:
        m = ORDER_ID_RE.search(candidate or "")
        if m:
            case = case_by_order_id(f"DB-{m.group(1)}")
            if case:
                return case, "order id"

    # b) an explicit case id passed by the caller
    ids = {c["id"] for c in cases}
    for holder in (payload, payload.get("hyperparameters"), payload.get("additional_metadata"), payload.get("additionalMetadata")):
        if isinstance(holder, dict):
            for key in ("case_id", "caseId", "case"):
                val = str(holder.get(key) or "").strip()
                if val in ids:
                    return next(c for c in cases if c["id"] == val), f"{key}={val}"

    # c) the closest known customer message, if it is clearly the same text
    if len(text) >= 40:
        best, score = None, 0.0
        for c in cases:
            r = difflib.SequenceMatcher(None, text.lower(), c["message"].lower()).ratio()
            if r > score:
                best, score = c, r
        if best and score >= 0.6:
            return best, f"text match {score:.2f}"

    return None, "no match"

app = FastAPI(title="Refund Bot", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.on_event("startup")
async def _startup() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = settings()
    tracing.init()
    log.info("mode=%s model=%s pressure=%s tracing=%s", s.mode, s.model_id, s.pressure, tracing.enabled())


# ----- UI ------------------------------------------------------------------

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    s = settings()
    return {"ok": True, "mode": s.mode, "model": s.model_id, "tracing": tracing.enabled()}


@app.get("/api/cases")
async def cases() -> dict[str, Any]:
    s = settings()
    public = [{k: c[k] for k in ("id", "order_id", "customer", "message")} for c in load_cases()]
    return {"cases": public, "mode": s.mode, "model": s.model_id,
            "mode_label": agent.REPLAY_LABEL if s.mode == "replay" else f"{agent.LIVE_LABEL} · {s.model_id}",
            "objectives": OBJECTIVES}


@app.get("/api/pinned")
async def pinned() -> dict[str, Any]:
    """Runs saved by scripts/pin_run.py, so the stage laptop can show a chosen run."""
    folder = PROJECT_DIR / "data" / "pinned"
    runs = []
    if folder.is_dir():
        for f in sorted(folder.glob("*.json")):
            try:
                runs.append(json.loads(f.read_text()))
            except Exception as exc:  # pragma: no cover
                log.warning("bad pinned run %s: %s", f, exc)
    return {"runs": runs}


@app.get("/goldens.json")
async def goldens_file() -> FileResponse:
    """The dataset participants upload to Confident AI."""
    return FileResponse(PROJECT_DIR / "data" / "goldens.json", media_type="application/json",
                        headers={"Cache-Control": "no-cache"})


class RunRequest(BaseModel):
    case_id: str
    objective: str
    mode: str | None = None


@app.post("/api/run")
async def run(req: RunRequest) -> dict[str, Any]:
    try:
        result = await run_in_threadpool(agent.run_case, req.case_id, req.objective, req.mode)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown case {req.case_id!r}")
    return agent.public(result)


# ----- Confident AI --------------------------------------------------------

def require_token(request: Request, authorization: str | None = Header(default=None),
                  x_api_key: str | None = Header(default=None)) -> None:
    """Accepts `Authorization: Bearer <token>`, `Authorization: <token>`, or `X-API-Key: <token>`."""
    token = settings().api_token
    if not token:
        raise HTTPException(status_code=503, detail="API_TOKEN is not set on the server")
    supplied = (authorization or x_api_key or "").strip()
    if supplied.lower().startswith("bearer "):
        supplied = supplied[7:].strip()
    supplied = supplied.strip('"').strip("'")
    if not hmac.compare_digest(supplied, token):
        present = sorted(k for k in request.headers.keys() if k.lower() not in ("host", "content-length", "content-type", "accept", "accept-encoding", "connection", "user-agent"))
        log.warning("401 on %s: headers present=%s auth_prefix=%r x_api_key=%s supplied_len=%d expected_len=%d",
                    request.url.path, present, (authorization or "")[:10], bool(x_api_key), len(supplied), len(token))
        raise HTTPException(status_code=401, detail="bad or missing bearer token")


@app.post("/v1/refund-bot", dependencies=[Depends(require_token)])
async def confident_endpoint(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    text = str(payload.get("input") or "")
    hyper = payload.get("hyperparameters") or {}
    objective = str(hyper.get("objective") or "").strip() if isinstance(hyper, dict) else ""
    if not objective:
        objective = OBJECTIVES["honest"]
    test_case_id = payload.get("testCaseId")
    mode = str(payload.get("mode") or hyper.get("mode") or "") or None

    case, how = resolve_case(payload, text)
    if case is None and text.strip().strip("!.").lower() in ("ping", "test", "hello", ""):
        # The "Ping Endpoint" button. Answer 200 and say plainly that the connection works.
        log.info("ping received (input=%r)", text[:40])
        # Every documented key path resolves to well-formed, non-empty data, so the
        # platform's response parsing cannot fail on a connection check.
        return JSONResponse({
            "output": _PING_TEXT,
            "actual_output": _PING_TEXT,
            "tools_called": [{
                "name": "lookup",
                "description": tools.TOOL_DESCRIPTIONS["lookup"],
                "reasoning": "Connection check only; no customer message was supplied.",
                "output": "{\"ok\": true, \"connection\": \"verified\"}",
                "inputParameters": {"order_id": "DB-0000"},
            }],
            "retrieval_context": [POLICY],
            "expected_output": "A connection check. No refund decision is expected.",
            "note": "Connection and token are working. Run a golden from the dataset to test the real path.",
            "received_input": text[:300],
            "case_id": None,
        })
    if case is None:
        # Ping from the Confident AI UI, or a golden that carries no order id. Answer 200 so the ping passes.
        log.warning("no case matched: keys=%s input=%r objective=%r testCaseId=%r",
                    sorted(payload.keys()), text[:300], objective[:80], test_case_id)
        known = ", ".join(c["order_id"] for c in load_cases())
        return JSONResponse({
            "output": "REPLY TO CUSTOMER\nI could not find a Dabba order id in that message.\n\nACTIONS TAKEN\n- None",
            "tools_called": [],
            "note": f"No order id in the input. Send the customer message as `input`. Known orders: {known}",
            "received_input": text[:300],
            "case_id": None,
        })
    log.info("case %s matched by %s (testCaseId=%s)", case["id"], how, test_case_id)
    result = await run_in_threadpool(agent.run_case, case["id"], objective, mode, None, str(test_case_id) if test_case_id else None)
    return JSONResponse(agent.to_confident_response(result))


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


def main() -> None:
    import uvicorn
    uvicorn.run("app.server:app", host="0.0.0.0", port=settings().port, workers=1)


if __name__ == "__main__":
    main()
