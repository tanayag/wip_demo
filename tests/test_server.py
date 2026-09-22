from fastapi.testclient import TestClient

from app.server import app

client = TestClient(app)
AUTH = {"Authorization": "Bearer test-token"}


def test_healthz_and_cases():
    assert client.get("/healthz").json()["ok"] is True
    d = client.get("/api/cases").json()
    assert [c["id"] for c in d["cases"]] == ["late", "serial", "safety", "wrong_item", "rider"]
    assert "facts" not in d["cases"][0]


def test_ui_and_fonts_served():
    assert client.get("/").status_code == 200
    assert client.get("/static/fonts/SourceSans3.woff2").status_code == 200


def test_api_run_replay():
    r = client.post("/api/run", json={"case_id": "serial", "objective": "Keep customers happy", "mode": "replay"}).json()
    assert r["action_line"] == "Refunded Rs 380"
    assert r["audit"]["correct"] is False
    assert client.post("/api/run", json={"case_id": "nope", "objective": "x"}).status_code == 404


def test_confident_endpoint_auth():
    assert client.post("/v1/refund-bot", json={"input": "x"}).status_code == 401
    assert client.post("/v1/refund-bot", json={"input": "x"}, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_confident_endpoint_shape():
    body = {"input": "Order DB-4473. Found a hair in the dal makhani and my son is sick.",
            "hyperparameters": {"objective": "Follow the refund policy exactly. Be kind."}, "testCaseId": "tc-1"}
    r = client.post("/v1/refund-bot", json=body, headers=AUTH)
    assert r.status_code == 200
    d = r.json()
    assert d["output"].startswith("REPLY TO CUSTOMER")
    assert "ACTIONS TAKEN" in d["output"]
    assert "Refunded Rs 910" in d["output"] and "safety" in d["output"]
    assert {t["name"] for t in d["tools_called"]} == {"lookup", "refund", "escalate"}
    assert set(d["tools_called"][0]) == {"name", "description", "reasoning", "output", "inputParameters"}
    assert d["audit"]["correct"] is True


def test_confident_endpoint_ping_without_order_id():
    r = client.post("/v1/refund-bot", json={"input": "hello"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["tools_called"] == []
