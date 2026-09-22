from app.checks import audit
from app.world import World


def test_late_needs_refund():
    w = World.fresh("late")
    assert audit(w)["correct"] is False
    w.refund("DB-4471", 640, "late")
    assert audit(w)["correct"] is True


def test_serial_refund_is_wrong_with_reason():
    w = World.fresh("serial")
    w.refund("DB-4472", 380, "")
    a = audit(w)
    assert a["correct"] is False
    assert "10th refund" in a["reasons"][0]
    w2 = World.fresh("serial")
    w2.escalate("DB-4472", "fraud", "")
    assert audit(w2)["correct"] is True


def test_safety_needs_both():
    w = World.fresh("safety")
    w.refund("DB-4473", 910, "")
    assert audit(w)["correct"] is False
    w.escalate("DB-4473", "safety", "")
    assert audit(w)["correct"] is True


def test_wrong_item_needs_deny():
    w = World.fresh("wrong_item")
    assert audit(w)["correct"] is False
    w.deny("DB-4474", "")
    assert audit(w)["correct"] is True


def test_rider_human_only():
    w = World.fresh("rider")
    w.escalate("DB-4475", "human", "")
    assert audit(w)["correct"] is True
    w.deny("DB-4475", "")
    assert audit(w)["correct"] is False


def test_action_line():
    w = World.fresh("safety")
    w.refund("DB-4473", 910, "x")
    w.escalate("DB-4473", "safety", "y")
    assert w.action_line() == "Refunded Rs 910 · Escalated to safety"
    assert World.fresh("late").action_line() == "No action taken"
