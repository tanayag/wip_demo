"""Checks .env, STS identity, one Converse call, and the native tool probe.

    python -m scripts.doctor
"""
from __future__ import annotations

import sys

from app.config import PROJECT_DIR, settings
from app.llm import BedrockLLM, make_bedrock_client


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'ok' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
    return ok


def main() -> int:
    s = settings()
    good = True
    good &= check(".env found", (PROJECT_DIR / ".env").is_file() or (PROJECT_DIR.parent / ".env").is_file(), str(PROJECT_DIR / ".env"))
    good &= check("MODEL_ID", bool(s.model_id), s.model_id)
    good &= check("API_TOKEN set", bool(s.api_token), "(needed for /v1/refund-bot)")
    check("CONFIDENT_API_KEY set", bool(s.confident_api_key), "optional; tracing is off without it")
    check("MODE", True, s.mode)
    check("PRESSURE", True, "on" if s.pressure else "off")

    try:
        import boto3
        ident = boto3.client("sts", region_name=s.aws_region).get_caller_identity()
        good &= check("STS identity", True, ident["Arn"])
    except Exception as exc:
        good &= check("STS identity", False, f"{type(exc).__name__}: {exc}")
        return 1

    client = make_bedrock_client(s.aws_region)
    try:
        r = client.converse(modelId=s.model_id, messages=[{"role": "user", "content": [{"text": "Reply with the single word: ready"}]}],
                            inferenceConfig={"maxTokens": 20})
        text = "".join(b.get("text", "") for b in r["output"]["message"]["content"])
        good &= check("Converse call", True, f"{s.model_id} said {text.strip()[:40]!r}")
    except Exception as exc:
        good &= check("Converse call", False, f"{type(exc).__name__}: {str(exc)[:200]}")
        return 1

    llm = BedrockLLM(client, s.model_id, temperature=0)
    try:
        step = llm.step("You help with orders. Always use the lookup tool first.",
                        [{"role": "user", "content": [{"text": "Please look up order DB-4471."}]}])
        called = [tc.name for tc in step.tool_calls]
        check("Tool protocol", True, f"{step.protocol} (called {called or 'nothing'})")
        if step.protocol == "native" and not called:
            print("     note: the model answered without calling a tool; fine for a probe, watch it in rehearsal")
    except Exception as exc:
        good &= check("Tool protocol", False, f"{type(exc).__name__}: {str(exc)[:200]}")

    print("\nall good" if good else "\nsomething is off, see FAIL lines")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
