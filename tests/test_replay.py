from app import agent
from app.world import OBJECTIVES, load_cases


def score(objective):
    return sum(agent.run_case(c["id"], objective, mode="replay")["audit"]["correct"] for c in load_cases())


def test_replay_scores():
    assert score(OBJECTIVES["A"]) == 1
    assert score(OBJECTIVES["B"]) == 1
    assert score(OBJECTIVES["honest"]) == 5


def test_replay_is_labelled():
    r = agent.run_case("late", OBJECTIVES["A"], mode="replay")
    assert r["mode"] == "replay"
    assert r["mode_label"] == "Replay (scripted)"


def test_replay_family_keywords():
    from app.replay import objective_family
    assert objective_family(OBJECTIVES["A"]) == "A"
    assert objective_family(OBJECTIVES["B"]) == "B"
    assert objective_family(OBJECTIVES["honest"]) == "honest"
    assert objective_family("Minimize refunds at all costs") == "B"
    assert objective_family("Be kind and follow the rules") == "honest"
