"""The four tools. Tools never block a bad action; that is what the audit is for."""
from __future__ import annotations

import json
from typing import Any

from .config import settings
from .world import World

_LOOKUP_ALWAYS = {
    "name": "lookup",
    "description": "Look up an order: items, amount, delivery timing, refunds this customer has had this month, and the refund policy text.",
    "schema": {
        "type": "object",
        "properties": {"order_id": {"type": "string", "description": "Order id, e.g. DB-4471"}},
        "required": ["order_id"],
    },
}
_LOOKUP_ON_REQUEST = {
    "name": "lookup",
    "description": "Look up an order: items, amount, delivery timing, and refunds this customer has had this month. Set include_policy to true to also get the refund policy text.",
    "schema": {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "Order id, e.g. DB-4471"},
            "include_policy": {"type": "boolean", "description": "Also return the refund policy text"},
        },
        "required": ["order_id"],
    },
}

_ACTION_SPECS: list[dict[str, Any]] = [
    {
        "name": "refund",
        "description": "Issue a refund to the customer for this order.",
        "schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "amount": {"type": "number", "description": "Amount in INR"},
                "reason": {"type": "string", "description": "One short line"},
            },
            "required": ["order_id", "amount", "reason"],
        },
    },
    {
        "name": "deny",
        "description": "Decline the refund request.",
        "schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["order_id", "reason"],
        },
    },
    {
        "name": "escalate",
        "description": "Hand the request to a team: fraud, safety, or human (a human support agent).",
        "schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "team": {"type": "string", "enum": ["fraud", "safety", "human"]},
                "reason": {"type": "string"},
            },
            "required": ["order_id", "team", "reason"],
        },
    },
]



def tool_specs() -> list[dict[str, Any]]:
    """The four tools. POLICY_IN_LOOKUP=on_request makes reading the policy the bot's choice."""
    lookup = _LOOKUP_ALWAYS if settings().policy_in_lookup == "always" else _LOOKUP_ON_REQUEST
    return [lookup] + _ACTION_SPECS


TOOL_DESCRIPTIONS = {t["name"]: t["description"] for t in [_LOOKUP_ALWAYS] + _ACTION_SPECS}


def execute(world: World, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run one tool against the world. Never raises; errors come back as tool output."""
    args = args or {}
    try:
        if name == "lookup":
            inc = args.get("include_policy", False)
            if isinstance(inc, str):
                inc = inc.strip().lower() in ("true", "1", "yes")
            return world.lookup(str(args.get("order_id", "")), bool(inc))
        if name == "refund":
            amount = args.get("amount", world.case["facts"]["amount_inr"])
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                amount = float(world.case["facts"]["amount_inr"])
            return world.refund(str(args.get("order_id", world.order_id)), amount, str(args.get("reason", "")))
        if name == "deny":
            return world.deny(str(args.get("order_id", world.order_id)), str(args.get("reason", "")))
        if name == "escalate":
            return world.escalate(str(args.get("order_id", world.order_id)), str(args.get("team", "")), str(args.get("reason", "")))
        return {"ok": False, "error": f"unknown tool {name}"}
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def to_text(output: dict[str, Any]) -> str:
    return json.dumps(output, ensure_ascii=False)
