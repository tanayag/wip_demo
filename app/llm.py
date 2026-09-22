"""DeepSeek on AWS Bedrock via the Converse API.

Native tool use first. If Bedrock rejects tools for this model (ValidationException
mentioning tools), fall back to a prompt-based protocol where the model emits one
JSON object {"tool": ..., "args": {...}} per turn. The fallback decision is cached
per model id. Reasoning blocks are stripped from history before it goes back out.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .tools import tool_specs

_THINK_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.DOTALL | re.IGNORECASE)
_STRAY_TAG_RE = re.compile(r"</?(think|thinking|reasoning|reply|response|answer|message)>", re.IGNORECASE)
_SPEAKER_RE = re.compile(r"^\s*(You|Bot|Assistant|Refund Bot)\s*:\s*", re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
# DeepSeek v3.2 sometimes leaks the start of its private tool-call markup into the text block.
_DSML_RE = re.compile(r"<[｜|]DSML[｜|][^\n]*", re.IGNORECASE)

_fallback_cache: dict[str, bool] = {}


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class StepResult:
    text: str
    tool_calls: list[ToolCall]
    assistant_message: dict[str, Any]   # Converse-shaped, ready to append to history
    usage: dict[str, Any] = field(default_factory=dict)
    stop_reason: str = ""
    protocol: str = "native"           # "native" | "prompt"


def clean_text(text: str) -> str:
    text = _THINK_RE.sub("", text or "")
    text = _DSML_RE.sub("", text)
    text = _STRAY_TAG_RE.sub("", text)
    text = _SPEAKER_RE.sub("", text.strip())
    return text.strip().strip('"').strip()


def strip_reasoning(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for m in messages:
        content = [c for c in m.get("content", []) if "reasoningContent" not in c]
        if not content:
            content = [{"text": "(no content)"}]
        out.append({"role": m["role"], "content": content})
    return out


def native_tool_config() -> dict[str, Any]:
    return {"tools": [{"toolSpec": {"name": t["name"], "description": t["description"], "inputSchema": {"json": t["schema"]}}} for t in tool_specs()]}


def prompt_protocol_text() -> str:
    lines = ["You have these tools. To call one, reply with ONLY a single JSON object on its own, nothing else:",
             '{"tool": "<name>", "args": {...}}',
             "You will get the tool's result in the next message. When you are done with tools, reply with the plain-text message for the customer (no JSON).",
             "", "Tools:"]
    for t in tool_specs():
        lines.append(f"- {t['name']}: {t['description']} args schema: {json.dumps(t['schema'])}")
    return "\n".join(lines)


def parse_prompt_tool_call(text: str) -> dict[str, Any] | None:
    """Find a {"tool": ..., "args": {...}} object in free text. Returns None if there isn't one."""
    text = clean_text(text)
    candidates = [m.group(1) for m in _FENCE_RE.finditer(text)] or []
    candidates.append(text)
    for cand in candidates:
        cand = cand.strip()
        start = cand.find("{")
        while start != -1:
            depth = 0
            for i in range(start, len(cand)):
                if cand[i] == "{":
                    depth += 1
                elif cand[i] == "}":
                    depth -= 1
                    if depth == 0:
                        chunk = cand[start:i + 1]
                        try:
                            obj = json.loads(chunk)
                        except json.JSONDecodeError:
                            break
                        if isinstance(obj, dict) and isinstance(obj.get("tool"), str):
                            return {"tool": obj["tool"], "args": obj.get("args") or {}}
                        break
            start = cand.find("{", start + 1)
    return None


def _is_tool_validation_error(exc: Exception) -> bool:
    name = type(exc).__name__
    msg = str(exc).lower()
    code = ""
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        code = str(resp.get("Error", {}).get("Code", ""))
    return ("ValidationException" in (name, code) or "validationexception" in msg) and "tool" in msg


class BedrockLLM:
    def __init__(self, client: Any, model_id: str, temperature: float = 0.7, max_tokens: int = 1200):
        self.client = client
        self.model_id = model_id
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def uses_prompt_protocol(self) -> bool:
        return _fallback_cache.get(self.model_id, False)

    # ----- one model call --------------------------------------------------

    def step(self, system: str, messages: list[dict[str, Any]]) -> StepResult:
        messages = strip_reasoning(messages)
        if not self.uses_prompt_protocol:
            try:
                return self._native(system, messages)
            except Exception as exc:
                if not _is_tool_validation_error(exc):
                    raise
                _fallback_cache[self.model_id] = True
        return self._prompt(system, messages)

    def _native(self, system: str, messages: list[dict[str, Any]]) -> StepResult:
        resp = self.client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=messages,
            toolConfig=native_tool_config(),
            inferenceConfig={"temperature": self.temperature, "maxTokens": self.max_tokens},
        )
        msg = resp["output"]["message"]
        text_parts, calls, kept = [], [], []
        for block in msg.get("content", []):
            if "text" in block:
                t = clean_text(block["text"])
                if t:
                    text_parts.append(t)
                    kept.append({"text": t})
            elif "toolUse" in block:
                tu = block["toolUse"]
                calls.append(ToolCall(id=tu["toolUseId"], name=tu["name"], input=tu.get("input") or {}))
                kept.append(block)
        if not kept:
            kept = [{"text": "(no reply)"}]
        return StepResult(
            text="\n".join(text_parts).strip(),
            tool_calls=calls,
            assistant_message={"role": "assistant", "content": kept},
            usage=resp.get("usage", {}),
            stop_reason=resp.get("stopReason", ""),
            protocol="native",
        )

    def _prompt(self, system: str, messages: list[dict[str, Any]]) -> StepResult:
        resp = self.client.converse(
            modelId=self.model_id,
            system=[{"text": system + "\n\n" + prompt_protocol_text()}],
            messages=messages,
            inferenceConfig={"temperature": self.temperature, "maxTokens": self.max_tokens},
        )
        msg = resp["output"]["message"]
        raw = "\n".join(b.get("text", "") for b in msg.get("content", []) if "text" in b)
        text = clean_text(raw)
        call = parse_prompt_tool_call(text)
        calls = [ToolCall(id=f"call_{len(messages)}", name=call["tool"], input=call["args"])] if call else []
        return StepResult(
            text="" if call else text,
            tool_calls=calls,
            assistant_message={"role": "assistant", "content": [{"text": text or "(no reply)"}]},
            usage=resp.get("usage", {}),
            stop_reason=resp.get("stopReason", ""),
            protocol="prompt",
        )

    # ----- message builders ------------------------------------------------

    def tool_results_message(self, results: list[tuple[ToolCall, str]]) -> dict[str, Any]:
        if self.uses_prompt_protocol:
            text = "\n\n".join(f"TOOL RESULT for {tc.name}:\n{out}" for tc, out in results)
            return {"role": "user", "content": [{"text": text}]}
        return {"role": "user", "content": [
            {"toolResult": {"toolUseId": tc.id, "content": [{"text": out}], "status": "success"}} for tc, out in results
        ]}


def make_bedrock_client(region: str) -> Any:
    import boto3
    from botocore.config import Config
    return boto3.client("bedrock-runtime", region_name=region, config=Config(read_timeout=90, connect_timeout=10, retries={"max_attempts": 2}))
