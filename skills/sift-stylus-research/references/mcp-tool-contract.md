# MCP Tool Contract: `search_stylus_docs`

## Purpose
Retrieve relevant Arbitrum Stylus documentation context before composing technical answers.

## Tool name
`search_stylus_docs`

## Input schema
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Natural language query describing the technical Stylus question."
    }
  },
  "required": ["query"]
}
```

## Invocation policy
- Call this tool for technical Stylus questions.
- Prefer at least one tool call before final answer generation.
- If output indicates no relevant context, state that limitation explicitly.
- Treat `agent_guidance` as normative behavior.
- Default behavior is references-first and code-generation-disallowed.

## Backend mapping
- Hosted backend endpoint: `POST /skills/sift-stylus-research/search`
- Request body:
```json
{ "prompt": "<query>" }
```

## Expected response shape
```json
{
  "found": true,
  "as_of_date": "2026-02-25",
  "context": "...",
  "chunks_used": 4,
  "query_mode": "tooling",
  "quality_signals": {
    "confidence": "high",
    "time_sensitive": false,
    "evidence_profile": {
      "official_count": 2,
      "community_count": 4,
      "canonical_count": 1,
      "unique_domains": 3
    }
  },
  "answer_contract": {
    "format": "direct_answer_why_links",
    "length_target_lines": "10-20",
    "uncertainty_mode": "state_uncertainty_plus_best_bet",
    "audience": "builder_engineer"
  },
  "recommended_answer_outline": {
    "direct_answer": "...",
    "why": ["..."],
    "links": [{ "title": "...", "url": "...", "source_type": "official" }],
    "caveats": []
  },
  "agent_guidance": {
    "behavior": "references_first",
    "code_generation": "disallowed",
    "instructions": ["..."]
  },
  "references": [
    { "title": "...", "url": "...", "source": "..." }
  ]
}
```

or

```json
{
  "found": false,
  "as_of_date": "2026-02-25",
  "context": "",
  "reason": "No relevant Stylus documentation was found for this query.",
  "quality_signals": {
    "confidence": "low",
    "time_sensitive": true,
    "evidence_profile": {
      "official_count": 0,
      "community_count": 0,
      "canonical_count": 0,
      "unique_domains": 0
    }
  },
  "answer_contract": {
    "format": "direct_answer_why_links",
    "length_target_lines": "10-20",
    "uncertainty_mode": "state_uncertainty_plus_best_bet",
    "audience": "builder_engineer"
  },
  "recommended_answer_outline": {
    "direct_answer": "...",
    "why": ["..."],
    "links": [],
    "caveats": ["..."]
  },
  "agent_guidance": {
    "behavior": "references_first",
    "code_generation": "disallowed",
    "instructions": ["..."]
  },
  "references": []
}
```

## Consumer guidance
- Treat `context` as source material.
- Cite retrieved details in answers.
- Treat `quality_signals.confidence` as the reliability hint for recommendation strength.
- Use `as_of_date` and `quality_signals.time_sensitive` for recency caveats on "latest/newest/current" queries.
- Use `recommended_answer_outline` as a client-agnostic scaffold for concise answers.
- Do not fabricate APIs not in tool output.
- Do not generate contract/app code unless explicitly overridden by user intent.
