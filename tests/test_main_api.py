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
    assert all(isinstance(item.get("system_prompt"), str) and item["system_prompt"] for item in payload["skills"])
    assert all(item.get("prompt_source", "").endswith("agents/openai.yaml#default_prompt") for item in payload["skills"])
    assert all(item.get("skill_doc_path", "").endswith("/SKILL.md") for item in payload["skills"])
    assert all(len(item.get("behavior_hash", "")) == 64 for item in payload["skills"])


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
    assert payload["answer_contract"]["format"] == "direct_answer_why_links"
    assert payload["quality_signals"]["confidence"] == "low"
    assert isinstance(payload["recommended_answer_outline"]["why"], list)
    assert "as_of_date" in payload


def test_execute_skill_search_success_payload_is_passthrough(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "run_skill_search",
        lambda skill_id, _prompt: {
            "found": True,
            "context": "ok",
            "references": [],
            "skill": skill_id,
            "custom": "value",
        },
    )
    client = TestClient(app_module.app)
    response = client.post("/skills/sift-stylus-research/search", json={"prompt": "latest tooling"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["skill"] == "sift-stylus-research"
    assert payload["custom"] == "value"
    assert "answer_contract" not in payload
    assert "quality_signals" not in payload
    assert "as_of_date" not in payload


def test_porting_audit_alias_uses_porting_skill(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "run_skill_search",
        lambda skill_id, _prompt: {"found": True, "context": "ok", "references": [], "skill": skill_id},
    )
    client = TestClient(app_module.app)
    response = client.post("/stylus-porting-audit", json={"prompt": "test"})

    assert response.status_code == 200
    assert response.json()["skill"] == "sift-stylus-porting-auditor"


def test_porting_audit_internal_error_keeps_minimal_payload(monkeypatch):
    def raise_error(_prompt):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module, "run_skill_search", lambda _skill_id, _prompt: raise_error(_prompt))
    client = TestClient(app_module.app)
    response = client.post("/stylus-porting-audit", json={"prompt": "test"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["found"] is False
    assert payload["skill"] == "sift-stylus-porting-auditor"
    assert "answer_contract" not in payload
    assert "quality_signals" not in payload
    assert "as_of_date" not in payload


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


def test_bootstrap_env_from_files_loads_missing_key(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(app_module, "_iter_env_file_candidates", lambda: [env_file])

    loaded = app_module.bootstrap_env_from_files()

    assert str(env_file) in loaded
    assert app_module.os.getenv("OPENROUTER_API_KEY") == "file-key"


def test_bootstrap_env_from_files_does_not_override_existing(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "runtime-key")
    monkeypatch.setattr(app_module, "_iter_env_file_candidates", lambda: [env_file])

    app_module.bootstrap_env_from_files()

    assert app_module.os.getenv("OPENROUTER_API_KEY") == "runtime-key"
