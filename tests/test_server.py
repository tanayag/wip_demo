from fastapi.testclient import TestClient

from app.server import app

client = TestClient(app)
AUTH = {"Authorization": "Bearer test-token"}


def test_healthz_and_cases():
    assert client.get("/healthz").json()["ok"] is True
    d = client.get("/api/cases").json()
    assert [c["id"] for c in d["cases"]] == ["late", "serial", "safety", "wrong_item", "rider"]
    assert "facts" not in d["cases"][0] and "expected" not in d["cases"][0]


def test_ui_and_fonts_served():
    assert client.get("/").status_code == 200
    assert client.get("/static/fonts/SourceSans3.woff2").status_code == 200


def test_api_run_replay():
    r = client.post("/api/run", json={"case_id": "serial", "objective": "Keep customers happy", "mode": "replay"}).json()
    assert r["action_line"] == "Refunded Rs 380"
    assert "audit" not in r, "evaluation happens on Confident AI, not in the app"
    assert r["state"]["refunds"][0]["amount"] == 380
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
    assert "audit" not in d
    esc = [t for t in d["tools_called"] if t["name"] == "escalate"][0]
    assert esc["inputParameters"] == {"order_id": "DB-4473", "team": "safety"}
    assert esc["reasoning"]


def test_confident_endpoint_ping_without_order_id():
    r = client.post("/v1/refund-bot", json={"input": "hello"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["case_id"] is None


def test_token_variants_accepted():
    body = {"input": "ping"}
    assert client.post("/v1/refund-bot", json=body, headers={"Authorization": "test-token"}).status_code == 200
    assert client.post("/v1/refund-bot", json=body, headers={"Authorization": "bearer test-token"}).status_code == 200
    assert client.post("/v1/refund-bot", json=body, headers={"X-API-Key": "test-token"}).status_code == 200
    assert client.post("/v1/refund-bot", json=body, headers={"X-API-Key": "nope"}).status_code == 401


def test_case_resolution_fallbacks():
    from app.server import resolve_case
    msg = "DB-4473. Found a hair in the dal makhani and my son has a stomach ache."
    assert resolve_case({}, msg)[0]["id"] == "safety"
    # order id spelled differently
    assert resolve_case({}, "order DB 4471 was late")[0]["id"] == "late"
    assert resolve_case({}, "order db_4472 again")[0]["id"] == "serial"
    # order id nested elsewhere in the payload
    assert resolve_case({"golden": {"input": "about DB-4475"}}, "")[0]["id"] == "rider"
    # explicit case id
    assert resolve_case({"case_id": "wrong_item"}, "")[0]["id"] == "wrong_item"
    assert resolve_case({"additional_metadata": {"case_id": "rider"}}, "")[0]["id"] == "rider"
    # the real message with the order id stripped out still matches on text
    from app.world import case_by_id
    stripped = case_by_id("late")["message"].replace("DB-4471", "")
    assert resolve_case({}, stripped)[0]["id"] == "late"
    # a ping must not match anything
    assert resolve_case({}, "ping")[0] is None
    assert resolve_case({}, "hello there, this is a test of the endpoint")[0] is None


def test_ping_reads_as_success():
    r = client.post("/v1/refund-bot", json={"input": "Ping!"}, headers=AUTH)
    assert r.status_code == 200
    d = r.json()
    assert d["output"].startswith("CONNECTION OK")
    assert "working" in d["note"]
    # every documented key path must resolve to well-formed, non-empty data
    assert isinstance(d["output"], str) and d["output"]
    assert len(d["tools_called"]) == 1
    assert set(d["tools_called"][0]) == {"name", "description", "reasoning", "output", "inputParameters"}
    assert d["retrieval_context"] and all(isinstance(x, str) for x in d["retrieval_context"])


def test_real_response_has_retrieval_context():
    body = {"input": "Order DB-4473. Found a hair in the dal makhani and my son is sick.",
            "hyperparameters": {"objective": "Follow the refund policy exactly."}}
    d = client.post("/v1/refund-bot", json=body, headers=AUTH).json()
    assert d["retrieval_context"] and "45 minutes late" in d["retrieval_context"][0]
