import app.llm as llm_mod
from app import agent
from app.llm import BedrockLLM, parse_prompt_tool_call, clean_text
from app.world import OBJECTIVES


def test_native_loop_runs_tools_and_audits(fake_bedrock, turns):
    native, text = turns
    client = fake_bedrock([
        native("Let me check.", [("lookup", {"order_id": "DB-4471"})]),
        native(None, [("refund", {"order_id": "DB-4471", "amount": 640, "reason": "late"})]),
        text("Sorry Fatima, refunded Rs 640."),
    ])
    llm = BedrockLLM(client, "fake.native")
    r = agent.run_case("late", OBJECTIVES["honest"], mode="live", llm=llm)
    assert r["error"] is None
    assert [a["tool"] for a in r["actions"]] == ["lookup", "refund"]
    assert r["audit"]["correct"] is True
    assert r["reply"] == "Sorry Fatima, refunded Rs 640."
    # tool results went back in Converse shape
    assert "toolResult" in client.calls[1]["messages"][-1]["content"][0]


def test_prompt_fallback_when_model_rejects_tools(fake_bedrock, turns):
    llm_mod._fallback_cache.clear()
    native, text = turns
    client = fake_bedrock([
        text('<think>hmm</think>```json\n{"tool": "lookup", "args": {"order_id": "DB-4475"}}\n```'),
        text('{"tool": "escalate", "args": {"order_id": "DB-4475", "team": "human", "reason": "rider"}}'),
        text("A person will call you today."),
    ], reject_tools=True)
    llm = BedrockLLM(client, "fake.prompt")
    r = agent.run_case("rider", OBJECTIVES["honest"], mode="live", llm=llm)
    assert r["error"] is None
    assert r["protocol"] == "prompt"
    assert llm_mod._fallback_cache["fake.prompt"] is True
    assert [a["tool"] for a in r["actions"]] == ["lookup", "escalate"]
    assert r["audit"]["correct"] is True
    # after the first rejection, no further call sends toolConfig
    assert all("toolConfig" not in c for c in client.calls[1:])
    llm_mod._fallback_cache.clear()


def test_max_steps_stops_the_loop(fake_bedrock, turns):
    native, text = turns
    client = fake_bedrock([native(None, [("lookup", {"order_id": "DB-4471"})])] * 10)
    r = agent.run_case("late", OBJECTIVES["honest"], mode="live", llm=BedrockLLM(client, "fake.loop"))
    assert r["steps"] == 7
    assert r["error"] is None


def test_bedrock_error_is_reported_not_raised(fake_bedrock):
    class Boom(fake_bedrock):
        def converse(self, **kw):
            raise RuntimeError("EndpointConnectionError")
    r = agent.run_case("late", OBJECTIVES["A"], mode="live", llm=BedrockLLM(Boom([]), "fake.boom"))
    assert "EndpointConnectionError" in r["error"]
    assert r["audit"]["correct"] is False


def test_parse_and_clean():
    assert parse_prompt_tool_call('text before {"tool":"deny","args":{"order_id":"x","reason":"y"}} after') == {"tool": "deny", "args": {"order_id": "x", "reason": "y"}}
    assert parse_prompt_tool_call("Sorry, no refund.") is None
    assert clean_text("I'll look it up.\n\n<｜DSML｜function_calls") == "I'll look it up."
    assert clean_text("<think>secret</think>Hello") == "Hello"


def test_reasoning_stripped_from_history():
    from app.llm import strip_reasoning
    msgs = [{"role": "assistant", "content": [{"reasoningContent": {"reasoningText": {"text": "x"}}}, {"text": "hi"}]}]
    assert strip_reasoning(msgs) == [{"role": "assistant", "content": [{"text": "hi"}]}]


def test_pressure_line_toggle():
    assert "performance review" in agent.system_prompt("x", pressure=True)
    assert "performance review" not in agent.system_prompt("x", pressure=False)
