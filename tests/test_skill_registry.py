from ast import literal_eval
from pathlib import Path

import skill_registry


def _read_default_prompt(skill_id):
    path = (
        Path(__file__).resolve().parent.parent
        / "skills"
        / skill_id
        / "agents"
        / "openai.yaml"
    )
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("default_prompt:"):
            return str(literal_eval(line.split("default_prompt:", 1)[1].strip()))
    raise AssertionError(f"default_prompt not found in {path}")


def test_research_skill_enables_research_contract(monkeypatch):
    captured = {}

    def fake_retrieve(prompt, include_research_contract=True, max_chars=10000):
        captured["prompt"] = prompt
        captured["include_research_contract"] = include_research_contract
        captured["max_chars"] = max_chars
        return {"found": True}

    monkeypatch.setattr(skill_registry, "retrieve_stylus_context", fake_retrieve)

    payload = skill_registry.run_skill_search(
        skill_registry.SKILL_ID_RESEARCH,
        "latest tools",
    )

    assert payload["skill"] == skill_registry.SKILL_ID_RESEARCH
    assert isinstance(payload["skill_system_prompt"], str)
    assert payload["skill_system_prompt"]
    assert len(payload["skill_behavior_hash"]) == 64
    assert captured["prompt"] == "latest tools"
    assert captured["include_research_contract"] is True


def test_porting_skill_disables_research_contract(monkeypatch):
    captured = {}

    def fake_retrieve(prompt, include_research_contract=True, max_chars=10000):
        captured["prompt"] = prompt
        captured["include_research_contract"] = include_research_contract
        captured["max_chars"] = max_chars
        return {"found": True}

    monkeypatch.setattr(skill_registry, "retrieve_stylus_context", fake_retrieve)

    payload = skill_registry.run_skill_search(
        skill_registry.SKILL_ID_PORTING_AUDITOR,
        "candidate analysis",
    )

    assert payload["skill"] == skill_registry.SKILL_ID_PORTING_AUDITOR
    assert isinstance(payload["skill_system_prompt"], str)
    assert payload["skill_system_prompt"]
    assert len(payload["skill_behavior_hash"]) == 64
    assert captured["prompt"] == "candidate analysis"
    assert captured["include_research_contract"] is False


def test_code_helper_skill_enables_research_contract(monkeypatch):
    captured = {}

    def fake_retrieve(prompt, include_research_contract=True, max_chars=10000):
        captured["prompt"] = prompt
        captured["include_research_contract"] = include_research_contract
        captured["max_chars"] = max_chars
        return {"found": True}

    monkeypatch.setattr(skill_registry, "retrieve_stylus_context", fake_retrieve)

    payload = skill_registry.run_skill_search(
        skill_registry.SKILL_ID_CODE_HELPER,
        "debug failing Stylus call",
    )

    assert payload["skill"] == skill_registry.SKILL_ID_CODE_HELPER
    assert isinstance(payload["skill_system_prompt"], str)
    assert payload["skill_system_prompt"]
    assert len(payload["skill_behavior_hash"]) == 64
    assert captured["prompt"] == "debug failing Stylus call"
    assert captured["include_research_contract"] is True


def test_published_prompt_is_source_of_truth():
    research = skill_registry.get_skill(skill_registry.SKILL_ID_RESEARCH)
    porting = skill_registry.get_skill(skill_registry.SKILL_ID_PORTING_AUDITOR)
    code_helper = skill_registry.get_skill(skill_registry.SKILL_ID_CODE_HELPER)

    assert research is not None
    assert porting is not None
    assert code_helper is not None

    assert research.system_prompt == _read_default_prompt(skill_registry.SKILL_ID_RESEARCH)
    assert porting.system_prompt == _read_default_prompt(skill_registry.SKILL_ID_PORTING_AUDITOR)
    assert code_helper.system_prompt == _read_default_prompt(skill_registry.SKILL_ID_CODE_HELPER)
    assert "analysis_action_paths" in porting.system_prompt
    assert "llm_augmentation_contract" in porting.system_prompt
    assert "upside-first recommendation" in porting.system_prompt


def test_porting_skill_enriches_payload_with_codebase_analysis(monkeypatch):
    def fake_retrieve(prompt, include_research_contract=True, max_chars=10000):
        return {
            "found": True,
            "context": "Top references:\n1. [Existing](https://example.com/existing)",
            "references": [
                {
                    "title": "Existing",
                    "url": "https://example.com/existing",
                    "source": "existing",
                }
            ],
        }

    monkeypatch.setattr(skill_registry, "retrieve_stylus_context", fake_retrieve)
    monkeypatch.setattr(
        skill_registry,
        "analyze_contract_target",
        lambda _prompt: {
            "mode": "github_repo",
            "target": "https://github.com/example/repo",
            "aggregate": {
                "files": 2,
                "contracts": 2,
                "hints": {"final": 67},
            },
            "high_targets": [
                {
                    "path": "contracts/A.sol",
                    "hint_score": 82,
                    "positive_drivers": ["compute-heavy paths"],
                    "risk_drivers": [],
                }
            ],
            "low_targets": [
                {
                    "path": "contracts/B.sol",
                    "hint_score": 33,
                    "positive_drivers": [],
                    "risk_drivers": ["high integration coupling"],
                }
            ],
            "driver_totals": {
                "positive": [{"driver": "compute-heavy paths", "count": 1}],
                "risk": [{"driver": "high integration coupling", "count": 1}],
            },
            "summary": "Static contract analysis summary.",
            "references": [
                {
                    "title": "Source Repo",
                    "url": "https://github.com/example/repo",
                    "source": "analysis",
                }
            ],
        },
    )

    payload = skill_registry.run_skill_search(
        skill_registry.SKILL_ID_PORTING_AUDITOR,
        "Analyze https://github.com/example/repo",
    )

    assert payload["skill"] == skill_registry.SKILL_ID_PORTING_AUDITOR
    assert payload["analysis_brief"].startswith("Porting analysis brief:")
    assert isinstance(payload["analysis_action_paths"], list)
    assert len(payload["analysis_action_paths"]) >= 3
    assert payload["context"].startswith("Porting analysis brief:")
    assert "Porting action paths:" in payload["context"]
    assert "LLM augmentation contract:" in payload["context"]
    assert "Static contract analysis summary." in payload["context"]
    assert payload["llm_augmentation_contract"]["mode"] == "bounded_second_pass"
    assert payload["llm_augmentation_contract"]["validation_rules"]["drop_uncited_items"] is True
    assert payload["codebase_analysis"]["mode"] == "github_repo"
    assert payload["references"][0]["url"] == "https://github.com/example/repo"
    assert "References:" in payload["references_markdown"]


def test_research_skill_does_not_run_codebase_analysis(monkeypatch):
    monkeypatch.setattr(
        skill_registry,
        "analyze_contract_target",
        lambda _prompt: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    monkeypatch.setattr(
        skill_registry,
        "retrieve_stylus_context",
        lambda _prompt, include_research_contract=True, max_chars=10000: {"found": True},
    )

    payload = skill_registry.run_skill_search(
        skill_registry.SKILL_ID_RESEARCH,
        "latest stylus tools",
    )

    assert payload["skill"] == skill_registry.SKILL_ID_RESEARCH


def test_build_analysis_action_paths_handles_missing_analysis():
    paths = skill_registry._build_analysis_action_paths({})
    assert isinstance(paths, list)
    assert len(paths) >= 3
    assert any(item.get("id") == "upside_first_framing" for item in paths)
    assert "Porting action paths:" in skill_registry._render_analysis_action_paths(paths)
    assert skill_registry._render_analysis_action_paths([]) == ""


def test_porting_skill_adds_augmentation_contract_without_analysis(monkeypatch):
    monkeypatch.setattr(
        skill_registry,
        "retrieve_stylus_context",
        lambda _prompt, include_research_contract=True, max_chars=10000: {"found": True},
    )
    monkeypatch.setattr(skill_registry, "analyze_contract_target", lambda _prompt: None)

    payload = skill_registry.run_skill_search(
        skill_registry.SKILL_ID_PORTING_AUDITOR,
        "Analyze this repo",
    )

    assert "codebase_analysis" not in payload
    assert payload["llm_augmentation_contract"]["schema_version"] == "1.0"
    assert payload["context"].startswith("LLM augmentation contract:")


def test_llm_augmentation_contract_shape_and_rendering():
    contract = skill_registry._build_llm_augmentation_contract()
    rendered = skill_registry._render_llm_augmentation_contract(contract)

    assert contract["mode"] == "bounded_second_pass"
    assert "recommended_carveouts" in contract["required_output"]
    assert contract["validation_rules"]["on_validation_failure"] == "fallback_static_only"
    assert "LLM augmentation contract:" in rendered


def test_porting_skill_applies_augmentation_and_returns_augmented_analysis(monkeypatch):
    monkeypatch.setattr(
        skill_registry,
        "retrieve_stylus_context",
        lambda _prompt, include_research_contract=True, max_chars=10000: {"found": True},
    )
    monkeypatch.setattr(
        skill_registry,
        "analyze_contract_target",
        lambda _prompt: {
            "mode": "local_path",
            "target": "./contracts",
            "aggregate": {"files": 2, "contracts": 2, "hints": {"final": 60}},
            "high_targets": [{"path": "contracts/ComputeHeavy.sol", "hint_score": 81}],
            "low_targets": [{"path": "contracts/Router.sol", "hint_score": 39}],
            "summary": "summary",
            "references": [],
        },
    )

    payload = skill_registry.run_skill_search(
        skill_registry.SKILL_ID_PORTING_AUDITOR,
        "Analyze ./contracts",
        augmentation={
            "additional_good_fit_signals": [
                {
                    "contract": "contracts/Router.sol",
                    "signal": "compute-heavy subpath identified",
                    "confidence": "medium",
                    "citations": ["https://example.com/router"],
                }
            ],
            "additional_bad_fit_signals": [],
            "recommended_carveouts": [],
            "confidence": "medium",
            "citations": ["https://example.com/summary"],
        },
    )

    assert payload["llm_augmentation"]["mode"] == "bounded_second_pass"
    assert payload["augmentation_comparison"]["mode"] == "bounded_second_pass"
    assert payload["augmentation_comparison"]["quality_delta"]["promotions"] == 1

    augmented_paths = [
        str(item.get("path") or "")
        for item in payload["codebase_analysis_augmented"]["high_targets"]
    ]
    assert "contracts/Router.sol" in augmented_paths
    assert "Augmentation application: promotions=1, demotions=0" in payload["context"]


def test_porting_skill_augmentation_fallback_keeps_static_analysis(monkeypatch):
    monkeypatch.setattr(
        skill_registry,
        "retrieve_stylus_context",
        lambda _prompt, include_research_contract=True, max_chars=10000: {"found": True},
    )
    monkeypatch.setattr(
        skill_registry,
        "analyze_contract_target",
        lambda _prompt: {
            "mode": "local_path",
            "target": "./contracts",
            "aggregate": {"files": 1, "contracts": 1, "hints": {"final": 62}},
            "high_targets": [{"path": "contracts/ComputeHeavy.sol", "hint_score": 81}],
            "low_targets": [],
            "summary": "summary",
            "references": [],
        },
    )

    payload = skill_registry.run_skill_search(
        skill_registry.SKILL_ID_PORTING_AUDITOR,
        "Analyze ./contracts",
        augmentation="invalid-augmentation",
    )

    assert payload["llm_augmentation"]["mode"] == "static_only_fallback"
    assert payload["augmentation_comparison"]["mode"] == "static_only"
    assert "codebase_analysis_augmented" not in payload
    assert "static-only fallback" in payload["context"]
