from ast import literal_eval
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Callable, Dict, List, Optional

from augmentation_contract import (
    build_porting_augmentation_contract,
    compare_porting_analysis_with_augmentation,
    render_porting_augmentation_contract,
    validate_porting_augmentation,
)
from contract_analysis import analyze_contract_target
from retrieve_chroma_docs import retrieve_stylus_context

SKILL_ID_RESEARCH = "sift-stylus-research"
SKILL_ID_PORTING_AUDITOR = "sift-stylus-porting-auditor"
SKILL_ID_CODE_HELPER = "sift-stylus-code-helper"
DEFAULT_GENERIC_SYSTEM_PROMPT = (
    "You are Sifter. Use the selected skill's retrieval tool before final answers when evidence is needed. "
    "Prefer concrete references and state uncertainty clearly when evidence is limited."
)


@dataclass(frozen=True)
class SkillDefinition:
    skill_id: str
    label: str
    description: str
    system_prompt: str
    behavior_hash: str
    search_handler: Callable[[str], dict]


def _skill_prompt_path(skill_id: str) -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "skills" / skill_id / "agents" / "openai.yaml"


def _skill_doc_path(skill_id: str) -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "skills" / skill_id / "SKILL.md"


def _skill_output_schema_path(skill_id: str) -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "skills" / skill_id / "references" / "output-schema.md"


def _compute_behavior_hash(skill_id: str) -> str:
    hasher = hashlib.sha256()
    paths = [
        _skill_doc_path(skill_id),
        _skill_prompt_path(skill_id),
        _skill_output_schema_path(skill_id),
    ]

    for path in paths:
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue

        hasher.update(str(path.name).encode("utf-8"))
        hasher.update(b"\n")
        hasher.update(content.encode("utf-8"))
        hasher.update(b"\n")

    digest = hasher.hexdigest()
    return digest if digest else "0" * 64


def _load_skill_system_prompt(skill_id: str) -> str:
    path = _skill_prompt_path(skill_id)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_GENERIC_SYSTEM_PROMPT

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line.startswith("default_prompt:"):
            continue

        prompt_literal = line.split("default_prompt:", 1)[1].strip()
        if not prompt_literal:
            break
        try:
            if prompt_literal[0] in ("'", '"'):
                return str(literal_eval(prompt_literal))
        except Exception:
            return prompt_literal
        return prompt_literal

    return DEFAULT_GENERIC_SYSTEM_PROMPT


def _run_shared_retrieval(prompt: str) -> dict:
    return retrieve_stylus_context(prompt, include_research_contract=True)


def _run_porting_retrieval(prompt: str) -> dict:
    return retrieve_stylus_context(prompt, include_research_contract=False)


def _driver_list(values, max_items: int = 3) -> str:
    if not isinstance(values, list):
        return ""
    items = [str(item).strip() for item in values if str(item).strip()]
    return ", ".join(items[:max_items])


def _build_analysis_brief(analysis: dict) -> str:
    if not isinstance(analysis, dict):
        return ""

    mode = str(analysis.get("mode") or "").strip()
    target = str(analysis.get("target") or "").strip()
    aggregate = analysis.get("aggregate") or {}
    hints = aggregate.get("hints") or {}
    high_targets = analysis.get("high_targets") or []
    low_targets = analysis.get("low_targets") or []
    driver_totals = analysis.get("driver_totals") or {}

    lines = ["Porting analysis brief:"]
    if mode or target:
        descriptor = " | ".join(item for item in [f"mode={mode}" if mode else "", target] if item)
        if descriptor:
            lines.append(f"- Target: {descriptor}")

    files = aggregate.get("files")
    contracts = aggregate.get("contracts")
    final = hints.get("final")
    if files is not None and contracts is not None and final is not None:
        lines.append(f"- Coverage: files={files}, contracts={contracts}, final_hint={final}")

    if high_targets:
        top = high_targets[0]
        lines.append(
            (
                f"- Top high-benefit candidate: {top.get('path')} "
                f"(score={top.get('hint_score')}, drivers={_driver_list(top.get('positive_drivers'))})"
            )
        )
    if low_targets:
        top = low_targets[0]
        lines.append(
            (
                f"- Top low-impact candidate: {top.get('path')} "
                f"(score={top.get('hint_score')}, risks={_driver_list(top.get('risk_drivers'))})"
            )
        )

    positive_totals = driver_totals.get("positive") or []
    risk_totals = driver_totals.get("risk") or []
    if positive_totals and isinstance(positive_totals, list):
        top = positive_totals[0]
        if isinstance(top, dict):
            lines.append(f"- Most common positive driver: {top.get('driver')} ({top.get('count')})")
    if risk_totals and isinstance(risk_totals, list):
        top = risk_totals[0]
        if isinstance(top, dict):
            lines.append(f"- Most common risk driver: {top.get('driver')} ({top.get('count')})")

    return "\n".join(lines)


def _build_analysis_action_paths(analysis: dict) -> list:
    if not isinstance(analysis, dict):
        return []

    high_targets = analysis.get("high_targets") or []
    low_targets = analysis.get("low_targets") or []
    target = str(analysis.get("target") or "").strip()

    action_paths = [
        {
            "id": "upside_first_framing",
            "instruction": (
                "Lead with concrete Stylus upside opportunities first (compute hotspots, directional "
                "percent gains, and pilot carveouts), then cover risks as mitigation items."
            ),
            "evidence": "high_targets + driver_totals.positive",
        },
        {
            "id": "source_scope",
            "instruction": (
                "Confirm scope from the analyzed target and treat static findings as directional, "
                "not as runtime proof."
            ),
            "evidence": target or "target_not_provided",
        },
        {
            "id": "candidate_selection",
            "instruction": (
                "Prioritize high-benefit candidates from codebase_analysis.high_targets, and explicitly "
                "label low-impact/defer candidates from codebase_analysis.low_targets."
            ),
            "evidence": f"high={len(high_targets)}, low={len(low_targets)}",
        },
        {
            "id": "boundary_risk_check",
            "instruction": (
                "Use risk drivers and low-impact selections to call out boundary/interface risks that should "
                "remain in Solidity unless mitigated, and pair each risk with a concrete mitigation path."
            ),
            "evidence": "risk_drivers + low_targets",
        },
        {
            "id": "evidence_citation",
            "instruction": (
                "Tie each recommendation to references from analysis and retrieval payload; avoid uncited claims."
            ),
            "evidence": "references",
        },
    ]
    return action_paths


def _render_analysis_action_paths(action_paths: list) -> str:
    if not isinstance(action_paths, list) or not action_paths:
        return ""
    lines = ["Porting action paths:"]
    for item in action_paths:
        if not isinstance(item, dict):
            continue
        instruction = str(item.get("instruction") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        if not instruction:
            continue
        if evidence:
            lines.append(f"- {instruction} (signal: {evidence})")
        else:
            lines.append(f"- {instruction}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _build_augmentation_summary(validated: dict, comparison: dict) -> str:
    if not isinstance(validated, dict):
        return ""

    mode = str(validated.get("mode") or "").strip()
    if mode != "bounded_second_pass":
        validation = validated.get("validation") or {}
        reason = str(validation.get("reason") or "augmentation_not_applied").strip()
        return f"Augmentation application: static-only fallback ({reason})."

    delta = comparison.get("quality_delta") if isinstance(comparison, dict) else {}
    promotions = int(delta.get("promotions") or 0)
    demotions = int(delta.get("demotions") or 0)
    added = delta.get("high_targets_added") or []
    added_items = [str(item).strip() for item in added if str(item).strip()] if isinstance(added, list) else []

    line = f"Augmentation application: promotions={promotions}, demotions={demotions}"
    if added_items:
        line += f", added_high_targets={', '.join(added_items[:3])}"
    return line


def _build_llm_augmentation_contract() -> dict:
    return build_porting_augmentation_contract()


def _render_llm_augmentation_contract(contract: dict) -> str:
    return render_porting_augmentation_contract(contract)


SKILL_REGISTRY: Dict[str, SkillDefinition] = {
    SKILL_ID_RESEARCH: SkillDefinition(
        skill_id=SKILL_ID_RESEARCH,
        label="Stylus Research",
        description="References-first research for Arbitrum Stylus tooling and ecosystem questions.",
        system_prompt=_load_skill_system_prompt(SKILL_ID_RESEARCH),
        behavior_hash=_compute_behavior_hash(SKILL_ID_RESEARCH),
        search_handler=_run_shared_retrieval,
    ),
    SKILL_ID_PORTING_AUDITOR: SkillDefinition(
        skill_id=SKILL_ID_PORTING_AUDITOR,
        label="Porting Auditor",
        description=(
            "Impact-focused candidacy checks for hybrid Solidity and Stylus architectures."
        ),
        system_prompt=_load_skill_system_prompt(SKILL_ID_PORTING_AUDITOR),
        behavior_hash=_compute_behavior_hash(SKILL_ID_PORTING_AUDITOR),
        search_handler=_run_porting_retrieval,
    ),
    SKILL_ID_CODE_HELPER: SkillDefinition(
        skill_id=SKILL_ID_CODE_HELPER,
        label="Stylus Code Helper",
        description=(
            "Implementation-focused Stylus guidance for debugging, architecture, and integration."
        ),
        system_prompt=_load_skill_system_prompt(SKILL_ID_CODE_HELPER),
        behavior_hash=_compute_behavior_hash(SKILL_ID_CODE_HELPER),
        search_handler=_run_shared_retrieval,
    ),
}


def get_skill(skill_id: str) -> Optional[SkillDefinition]:
    return SKILL_REGISTRY.get(skill_id)


def list_skills() -> List[dict]:
    return [
        {
            "id": item.skill_id,
            "label": item.label,
            "description": item.description,
            "system_prompt": item.system_prompt,
            "prompt_source": f"skills/{item.skill_id}/agents/openai.yaml#default_prompt",
            "skill_doc_path": f"skills/{item.skill_id}/SKILL.md",
            "behavior_hash": item.behavior_hash,
            "search_path": f"/skills/{item.skill_id}/search",
        }
        for item in SKILL_REGISTRY.values()
    ]


def run_skill_search(skill_id: str, prompt: str, augmentation: object = None) -> dict:
    skill = get_skill(skill_id)
    if skill is None:
        raise KeyError(skill_id)

    payload = skill.search_handler(prompt)
    if isinstance(payload, dict):
        payload.setdefault("skill", skill_id)
        payload.setdefault("skill_system_prompt", skill.system_prompt)
        payload.setdefault("skill_behavior_hash", skill.behavior_hash)

        if skill_id == SKILL_ID_PORTING_AUDITOR:
            augmentation_contract = _build_llm_augmentation_contract()
            payload["llm_augmentation_contract"] = augmentation_contract
            augmentation_text = _render_llm_augmentation_contract(augmentation_contract)

            analysis = analyze_contract_target(prompt)
            brief = ""
            action_paths_text = ""
            summary = ""
            augmentation_summary = ""
            if isinstance(analysis, dict):
                payload["codebase_analysis"] = analysis
                brief = _build_analysis_brief(analysis)
                action_paths = _build_analysis_action_paths(analysis)
                if action_paths:
                    payload["analysis_action_paths"] = action_paths
                action_paths_text = _render_analysis_action_paths(action_paths)
                if brief:
                    payload["analysis_brief"] = brief

                summary = str(analysis.get("summary") or "").strip()

                analysis_refs = analysis.get("references") or []
                if isinstance(analysis_refs, list) and analysis_refs:
                    existing_refs = payload.get("references") or []
                    if isinstance(existing_refs, list):
                        merged = []
                        seen_urls = set()
                        for ref in [*analysis_refs, *existing_refs]:
                            url = str(ref.get("url") or "").strip()
                            if not url.startswith("http"):
                                continue
                            if url in seen_urls:
                                continue
                            seen_urls.add(url)
                            merged.append(
                                {
                                    "title": str(ref.get("title") or "Reference").strip(),
                                    "url": url,
                                    "source": str(ref.get("source") or "analysis"),
                                }
                            )
                        if merged:
                            payload["references"] = merged
                            lines = ["References:"]
                            for ref in merged[:12]:
                                lines.append(f"- [{ref['title']}]({ref['url']})")
                            payload["references_markdown"] = "\n".join(lines)

            if augmentation is not None:
                validated_augmentation = validate_porting_augmentation(
                    augmentation,
                    contract=augmentation_contract,
                )
                payload["llm_augmentation"] = validated_augmentation
                augmentation_comparison = compare_porting_analysis_with_augmentation(
                    analysis,
                    validated_augmentation,
                    contract=augmentation_contract,
                )
                payload["augmentation_comparison"] = augmentation_comparison
                augmentation_summary = _build_augmentation_summary(
                    validated_augmentation,
                    augmentation_comparison,
                )

                if isinstance(analysis, dict) and isinstance(augmentation_comparison, dict):
                    if str(augmentation_comparison.get("mode") or "") == "bounded_second_pass":
                        augmented_section = augmentation_comparison.get("augmented") or {}
                        if isinstance(augmented_section, dict):
                            augmented_analysis = dict(analysis)
                            high_targets = augmented_section.get("high_targets")
                            low_targets = augmented_section.get("low_targets")
                            if isinstance(high_targets, list):
                                augmented_analysis["high_targets"] = high_targets
                            if isinstance(low_targets, list):
                                augmented_analysis["low_targets"] = low_targets
                            augmented_analysis["augmentation_quality_delta"] = (
                                augmentation_comparison.get("quality_delta") or {}
                            )
                            augmented_analysis["augmentation_warnings"] = list(
                                augmented_section.get("warnings") or []
                            )
                            payload["codebase_analysis_augmented"] = augmented_analysis

            analysis_context = "\n\n".join(
                part for part in [brief, action_paths_text, augmentation_text, augmentation_summary, summary] if part
            ).strip()
            if analysis_context:
                base_context = str(payload.get("context") or "").strip()
                payload["context"] = (
                    f"{analysis_context}\n\n{base_context}" if base_context else analysis_context
                )
    return payload
