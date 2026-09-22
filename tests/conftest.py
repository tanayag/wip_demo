import os

import pytest

os.environ.setdefault("API_TOKEN", "test-token")
os.environ.setdefault("MODE", "replay")
os.environ.setdefault("MODEL_ID", "fake.model")
os.environ.pop("CONFIDENT_API_KEY", None)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    import app.agent as agent_mod
    monkeypatch.setattr(agent_mod.time, "sleep", lambda s: None)


class FakeValidationException(Exception):
    def __init__(self, msg):
        super().__init__(msg)
        self.response = {"Error": {"Code": "ValidationException", "Message": msg}}


class FakeBedrock:
    """Scripted Converse client. `turns` is a list of assistant messages to return in order."""

    def __init__(self, turns, reject_tools=False):
        self.turns = list(turns)
        self.reject_tools = reject_tools
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.reject_tools and "toolConfig" in kwargs:
            raise FakeValidationException("This model doesn't support tool use in converse API")
        if not self.turns:
            msg = {"role": "assistant", "content": [{"text": "Thanks, all sorted."}]}
        else:
            msg = self.turns.pop(0)
        return {"output": {"message": msg}, "stopReason": "tool_use" if any("toolUse" in c for c in msg["content"]) else "end_turn",
                "usage": {"inputTokens": 1, "outputTokens": 1}}


def native_turn(text=None, tool_uses=()):
    content = []
    if text:
        content.append({"text": text})
    for i, (name, inp) in enumerate(tool_uses):
        content.append({"toolUse": {"toolUseId": f"t{i}", "name": name, "input": inp}})
    return {"role": "assistant", "content": content}


def text_turn(text):
    return {"role": "assistant", "content": [{"text": text}]}


@pytest.fixture
def fake_bedrock():
    return FakeBedrock


@pytest.fixture
def turns():
    return native_turn, text_turn
