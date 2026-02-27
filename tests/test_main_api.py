from fastapi.testclient import TestClient

import main as app_module


def test_health_endpoint():
    client = TestClient(app_module.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_stylus_chat_validates_empty_prompt():
    client = TestClient(app_module.app)
    response = client.post("/stylus-chat", json={"prompt": ""})
    assert response.status_code == 422


def test_skills_index_lists_supported_skills():
    client = TestClient(app_module.app)
    response = client.get("/skills")

    assert response.status_code == 200
    payload = response.json()
    assert "skills" in payload
    assert any(item["id"] == "sift-stylus-research" for item in payload["skills"])
    assert any(item["id"] == "sift-stylus-porting-auditor" for item in payload["skills"])
    assert any(item["id"] == "sift-stylus-code-helper" for item in payload["skills"])


def test_skill_search_rejects_unsupported_skill():
    client = TestClient(app_module.app)
    response = client.post("/skills/not-a-skill/search", json={"prompt": "hello"})

    assert response.status_code == 404
    assert "Unsupported skill" in response.json()["detail"]


def test_stylus_chat_handles_internal_error_with_safe_response(monkeypatch):
    def raise_error(_prompt):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module, "run_skill_search", lambda _skill_id, _prompt: raise_error(_prompt))
    client = TestClient(app_module.app)
    response = client.post("/stylus-chat", json={"prompt": "test"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["found"] is False
    assert payload["reason"] == "Retrieval failed due to an internal error."
    assert payload["references"] == []
    assert payload["agent_guidance"]["behavior"] == "references_first"
    assert payload["skill"] == "sift-stylus-research"


def test_porting_audit_alias_uses_porting_skill(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "run_skill_search",
        lambda skill_id, _prompt, _augmentation=None: {
            "found": True,
            "context": "ok",
            "references": [],
            "skill": skill_id,
        },
    )
    client = TestClient(app_module.app)
    response = client.post(
        "/stylus-porting-audit",
        json={
            "prompt": "test",
            "augmentation": {
                "additional_good_fit_signals": [],
                "additional_bad_fit_signals": [],
                "recommended_carveouts": [],
                "confidence": "low",
                "citations": ["https://example.com/summary"],
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["skill"] == "sift-stylus-porting-auditor"


def test_porting_audit_passes_required_augmentation_to_skill_search(monkeypatch):
    captured = {}

    def fake_run(skill_id, prompt, augmentation=None):
        captured["skill_id"] = skill_id
        captured["prompt"] = prompt
        captured["augmentation"] = augmentation
        return {"found": True, "context": "ok", "references": [], "skill": skill_id}

    monkeypatch.setattr(app_module, "run_skill_search", fake_run)
    client = TestClient(app_module.app)
    response = client.post(
        "/stylus-porting-audit",
        json={
            "prompt": "Analyze ./contracts",
            "augmentation": {
                "additional_good_fit_signals": [],
                "additional_bad_fit_signals": [],
                "recommended_carveouts": [],
                "confidence": "low",
                "citations": ["https://example.com"],
            },
        },
    )

    assert response.status_code == 200
    assert captured["skill_id"] == "sift-stylus-porting-auditor"
    assert captured["prompt"] == "Analyze ./contracts"
    assert isinstance(captured["augmentation"], dict)


def test_porting_skill_search_rejects_missing_augmentation():
    client = TestClient(app_module.app)
    response = client.post(
        "/skills/sift-stylus-porting-auditor/search",
        json={"prompt": "Analyze ./contracts"},
    )

    assert response.status_code == 422
    assert "requires an 'augmentation' payload object" in response.json()["detail"]


def test_validate_porting_augmentation_endpoint_fallback():
    client = TestClient(app_module.app)
    response = client.post(
        "/skills/sift-stylus-porting-auditor/validate-augmentation",
        json={"augmentation": "not-an-object"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["skill"] == "sift-stylus-porting-auditor"
    assert payload["llm_augmentation_contract"]["mode"] == "bounded_second_pass"
    assert payload["llm_augmentation"]["mode"] == "static_only_fallback"
    assert payload["llm_augmentation"]["validation"]["reason"] == "augmentation_payload_must_be_object"


def test_validate_porting_augmentation_endpoint_success():
    client = TestClient(app_module.app)
    response = client.post(
        "/skills/sift-stylus-porting-auditor/validate-augmentation",
        json={
            "augmentation": {
                "additional_good_fit_signals": [
                    {
                        "contract": "contracts/ComputeHeavy.sol",
                        "signal": "hash-heavy critical path",
                        "confidence": "high",
                        "citations": ["https://example.com/bench"],
                    }
                ],
                "additional_bad_fit_signals": [],
                "recommended_carveouts": [],
                "confidence": "medium",
                "citations": ["https://example.com/summary"],
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["skill"] == "sift-stylus-porting-auditor"
    assert payload["llm_augmentation"]["mode"] == "bounded_second_pass"
    assert payload["llm_augmentation"]["additional_good_fit_signals"][0]["contract"] == (
        "contracts/ComputeHeavy.sol"
    )
    assert payload["llm_augmentation"]["validation"]["status"] == "valid"


def test_compare_porting_augmentation_endpoint_returns_quality_delta(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "run_skill_search",
        lambda _skill_id, _prompt: {
            "skill": "sift-stylus-porting-auditor",
            "codebase_analysis": {
                "high_targets": [{"path": "contracts/ComputeHeavy.sol", "hint_score": 81}],
                "low_targets": [{"path": "contracts/Router.sol", "hint_score": 39}],
            },
        },
    )
    client = TestClient(app_module.app)
    response = client.post(
        "/skills/sift-stylus-porting-auditor/compare-augmentation",
        json={
            "prompt": "Analyze ./contracts",
            "augmentation": {
                "additional_good_fit_signals": [
                    {
                        "contract": "contracts/Router.sol",
                        "signal": "compute-heavy route path",
                        "confidence": "high",
                        "citations": ["https://example.com/router"],
                    }
                ],
                "additional_bad_fit_signals": [],
                "recommended_carveouts": [],
                "confidence": "medium",
                "citations": ["https://example.com/summary"],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    comparison = payload["augmentation_comparison"]
    assert comparison["mode"] == "bounded_second_pass"
    assert comparison["quality_delta"]["promotions"] == 1
    assert "contracts/Router.sol" in comparison["quality_delta"]["high_targets_added"]


def test_compare_porting_augmentation_endpoint_keeps_static_on_invalid_augmentation(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "run_skill_search",
        lambda _skill_id, _prompt: {
            "skill": "sift-stylus-porting-auditor",
            "codebase_analysis": {
                "high_targets": [{"path": "contracts/ComputeHeavy.sol", "hint_score": 81}],
                "low_targets": [{"path": "contracts/Router.sol", "hint_score": 39}],
            },
        },
    )
    client = TestClient(app_module.app)
    response = client.post(
        "/skills/sift-stylus-porting-auditor/compare-augmentation",
        json={
            "prompt": "Analyze ./contracts",
            "augmentation": "not-a-valid-object",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    comparison = payload["augmentation_comparison"]
    assert comparison["mode"] == "static_only"
    assert comparison["quality_delta"]["promotions"] == 0


def test_openrouter_proxy_requires_backend_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = TestClient(app_module.app)
    response = client.post(
        "/openrouter/chat/completions",
        json={"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "OPENROUTER_API_KEY is not configured on the backend."


def test_openrouter_proxy_passthrough_success(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return {"id": "ok", "choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(app_module.requests, "post", fake_post)

    client = TestClient(app_module.app)
    payload = {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "hello"}]}
    response = client.post("/openrouter/chat/completions", json=payload)

    assert response.status_code == 200
    assert response.json()["id"] == "ok"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == "openai/gpt-4o-mini"
    assert captured["json"]["messages"][0]["content"] == "hello"
