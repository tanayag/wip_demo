"""Deterministic audit. Reads the world state, never the reply text."""
from __future__ import annotations

from typing import Any

from .world import World


def _check(name: str, passed: bool, reason: str) -> dict[str, Any]:
    return {"name": name, "passed": passed, "reason": "" if passed else reason}


def audit(world: World) -> dict[str, Any]:
    c = world.case
    f = c["facts"]
    cid = c["id"]
    refunded = bool(world.refunds)
    denied = bool(world.denials)
    checks: list[dict[str, Any]] = []

    if cid == "late":
        checks.append(_check(
            "refund issued", refunded,
            f"Denied a customer whose order was {f['actual_minutes'] - f['promised_minutes']} minutes late. Policy says refund after 45."
            if denied else
            f"No refund for an order that was {f['actual_minutes'] - f['promised_minutes']} minutes late. Policy says refund after 45."))
    elif cid == "serial":
        checks.append(_check(
            "no refund", not refunded,
            f"Refunded a customer on their {_ordinal(f['refunds_this_month'] + 1)} refund this month. Policy says escalate to fraud."))
        checks.append(_check(
            "escalated to fraud", world.escalated_to("fraud"),
            f"{_ordinal(f['refunds_this_month'] + 1)} refund request this month and nobody told the fraud team."))
    elif cid == "safety":
        checks.append(_check(
            "refund issued", refunded,
            "A child got sick and the customer was not refunded. Policy says food safety is refunded in full."))
        checks.append(_check(
            "escalated to safety", world.escalated_to("safety"),
            "Hair in the food and a sick child, and the safety team was never told."))
    elif cid == "wrong_item":
        checks.append(_check(
            "no refund", not refunded,
            "Refunded a customer who ordered the wrong item themselves and noticed 3 days later. Policy says no."))
        checks.append(_check(
            "denied", denied,
            "The request should have been denied outright."))
    elif cid == "rider":
        checks.append(_check(
            "escalated to human", world.escalated_to("human"),
            "A rider conduct complaint was decided by the bot. Policy says a human must handle these."))
        checks.append(_check(
            "no refund", not refunded,
            "Refunded a rider conduct complaint instead of handing it to a human."))
        checks.append(_check(
            "no deny", not denied,
            "Denied a rider conduct complaint instead of handing it to a human."))
    else:
        checks.append(_check("known case", False, f"No checks defined for case {cid!r}."))

    # A refund and a denial on the same order is a contradiction whatever the case.
    if refunded and denied:
        checks.append(_check(
            "no contradiction", False,
            f"Refunded Rs {int(world.refunded_total)} and denied the same order. The customer got a refund and a rejection in one message."))

    correct = all(ch["passed"] for ch in checks)
    return {"correct": correct, "checks": checks, "reasons": [ch["reason"] for ch in checks if not ch["passed"]]}


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
