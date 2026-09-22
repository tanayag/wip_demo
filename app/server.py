"""FastAPI, single process. The stage UI, the run endpoint, and the Confident AI endpoint."""
from __future__ import annotations

import asyncio
import hmac
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import agent, tracing
from .config import PROJECT_DIR, settings
from .world import OBJECTIVES, case_by_order_id, load_cases

log = logging.getLogger("refund-bot")
WEB_DIR = PROJECT_DIR / "web"
ORDER_ID_RE = re.compile(r"\bDB-\d{4}\b", re.IGNORECASE)

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
    public = [{k: c[k] for k in ("id", "order_id", "customer", "message", "expected", "expected_summary")} for c in load_cases()]
    return {"cases": public, "mode": s.mode, "model": s.model_id,
            "mode_label": agent.REPLAY_LABEL if s.mode == "replay" else f"{agent.LIVE_LABEL} · {s.model_id}",
            "objectives": OBJECTIVES}


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
    return result


# ----- Confident AI --------------------------------------------------------

def require_token(authorization: str | None = Header(default=None)) -> None:
    token = settings().api_token
    if not token:
        raise HTTPException(status_code=503, detail="API_TOKEN is not set on the server")
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not hmac.compare_digest(supplied, token):
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

    m = ORDER_ID_RE.search(text)
    case = case_by_order_id(m.group(0)) if m else None
    if case is None:
        # Ping from the Confident AI UI, or a golden without an order id. Answer 200 so the ping passes.
        known = ", ".join(c["order_id"] for c in load_cases())
        return JSONResponse({
            "output": "REPLY TO CUSTOMER\nI could not find a Dabba order id in that message.\n\nACTIONS TAKEN\n- None",
            "tools_called": [],
            "audit": {"correct": False, "checks": [], "reasons": [f"No order id in input. Known orders: {known}"]},
            "case_id": None,
        })
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
