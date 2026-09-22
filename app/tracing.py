"""confident-trace wrapper. One trace per request, one tool span per tool call.
No-op without CONFIDENT_API_KEY. Never lets tracing raise."""
from __future__ import annotations

import contextlib
import json
import logging
from typing import Any

from .config import settings

log = logging.getLogger("refund-bot.tracing")
_state = {"initialised": False, "enabled": False}


def enabled() -> bool:
    return _state["enabled"]


def init() -> bool:
    if _state["initialised"]:
        return _state["enabled"]
    _state["initialised"] = True
    key = settings().confident_api_key
    if not key:
        return False
    try:
        import confident_trace
        confident_trace.init(api_key=key, instrumentations=())
        _state["enabled"] = True
    except Exception as exc:  # pragma: no cover
        log.warning("tracing disabled: %s", exc)
        _state["enabled"] = False
    return _state["enabled"]


class _Trace:
    def __init__(self) -> None:
        self.finished = False

    def finish(self, result: dict[str, Any]) -> None:
        if not enabled():
            return
        try:
            from confident_trace import update_trace
            update_trace(output=result.get("reply") or "", expected_output=result.get("expected_summary") or "", metadata={
                "case_id": result.get("case_id"),
                "action_line": result.get("action_line"),
                "correct": result.get("audit", {}).get("correct"),
                "mode": result.get("mode_label"),
                "model": result.get("model"),
            })
        except Exception as exc:  # pragma: no cover
            log.debug("trace finish failed: %s", exc)


@contextlib.contextmanager
def request_trace(case_id: str, objective: str, message: str, test_case_id: str | None = None):
    tr = _Trace()
    if not init():
        yield tr
        return
    try:
        from confident_trace import span, update_trace
        cm = span(f"refund-bot:{case_id}", type="agent")
    except Exception as exc:  # pragma: no cover
        log.debug("trace start failed: %s", exc)
        yield tr
        return
    try:
        with cm:
            try:
                fields: dict[str, Any] = {"input": message, "tags": [case_id]}
                if test_case_id:
                    fields["test_case_id"] = str(test_case_id)
                update_trace(**fields)
            except Exception as exc:  # pragma: no cover
                log.debug("trace fields failed: %s", exc)
            yield tr
    except Exception as exc:  # pragma: no cover
        log.debug("trace span failed: %s", exc)
        if not tr.finished:
            yield tr


def tool_span(name: str, args: dict[str, Any], output_text: str) -> None:
    if not enabled():
        return
    try:
        from confident_trace import span
        with span(name, type="tool", input=json.dumps(args, ensure_ascii=False), output=output_text):
            pass
    except Exception as exc:  # pragma: no cover
        log.debug("tool span failed: %s", exc)


def flush() -> None:
    if not enabled():
        return
    try:
        from confident_trace import flush as _flush
        _flush(timeout_millis=5000)
    except Exception:  # pragma: no cover
        pass
