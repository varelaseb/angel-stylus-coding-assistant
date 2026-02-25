from datetime import datetime, timezone
from typing import Dict

TIME_SENSITIVE_HINTS = (
    "latest",
    "newest",
    "recent",
    "current",
    "today",
    "release",
    "released",
    "version",
    "versions",
    "changelog",
    "as of",
)

ANSWER_CONTRACT = {
    "format": "direct_answer_why_links",
    "length_target_lines": "10-20",
    "uncertainty_mode": "state_uncertainty_plus_best_bet",
    "audience": "builder_engineer",
}


def iso_date_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def is_time_sensitive_query(value: str) -> bool:
    lowered = (value or "").lower()
    return any(token in lowered for token in TIME_SENSITIVE_HINTS)


def answer_contract_payload() -> Dict[str, str]:
    return dict(ANSWER_CONTRACT)


def default_quality_signals(*, confidence: str, time_sensitive: bool) -> Dict[str, object]:
    return {
        "confidence": confidence,
        "time_sensitive": bool(time_sensitive),
        "evidence_profile": {
            "official_count": 0,
            "community_count": 0,
            "canonical_count": 0,
            "unique_domains": 0,
        },
    }


def fallback_recommended_outline(*, retrieval_failed: bool) -> Dict[str, object]:
    if retrieval_failed:
        return {
            "direct_answer": (
                "I could not complete retrieval due to an internal error. "
                "Retry shortly or narrow the query scope."
            ),
            "why": [
                "No reliable retrieval context is available for this response.",
                "This is a best-effort failure-safe response.",
            ],
            "links": [],
            "caveats": ["Low-confidence result due to retrieval failure."],
        }

    return {
        "direct_answer": "Use retrieved references to answer directly and concisely.",
        "why": ["Follow references-first guidance for this response."],
        "links": [],
        "caveats": [],
    }
