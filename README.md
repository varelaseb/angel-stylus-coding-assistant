# Stylus Retrieval Backend

Retrieval-only backend for Arbitrum Stylus ecosystem research.

It indexes official docs, Stylus blog posts, and curated community repos, then returns
`context + references + agent_guidance` to downstream LLM consumers (MCP, IDE tools, web chat).

## Behavior Contract

- Returns references-first context for Stylus questions.
- Emits `agent_guidance` that sets `code_generation=disallowed`.
- Does not synthesize contract/application code.
- For porting-auditor requests with a GitHub target URL, performs static Solidity signal extraction on the target repository/files and injects those findings into the returned context.

## API

- `GET /health`
- `GET /skills`
- `POST /skills/{skill_id}/search`
- `POST /openrouter/chat/completions` (server-side OpenRouter proxy; keeps API key off the frontend)

Skill metadata contract (`GET /skills`):
- `system_prompt`: canonical prompt loaded from `skills/<id>/agents/openai.yaml#default_prompt`
- `prompt_source`: explicit source path for traceability
- `skill_doc_path`: path to the published skill instructions (`SKILL.md`)
- `behavior_hash`: SHA-256 fingerprint over the published skill behavior files

Consumers should use `system_prompt` from `/skills` (instead of frontend-local prompt text) to keep behavior consistent with published skills.

Compatibility aliases:
- `POST /stylus-chat` -> research skill
- `POST /stylus-porting-audit` -> porting auditor skill

Request:

```json
{ "prompt": "What tooling is current for Stylus testing?" }
```

Response (example):

```json
{
  "found": true,
  "as_of_date": "2026-02-25",
  "context": "Top references:\n1. ...",
  "chunks_used": 25,
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
    "code_generation": "disallowed"
  },
  "references": [{ "title": "...", "url": "..." }]
}
```

Note: the extended quality fields in this example are produced by
`/skills/sift-stylus-research/search`. Other skill endpoints may return only the core fields.

OpenRouter proxy request (example):

```json
{
  "model": "openai/gpt-4o-mini",
  "messages": [{ "role": "user", "content": "What are the newest Stylus tools?" }],
  "tools": [],
  "tool_choice": "auto"
}
```

## Local Run

```bash
source .venv/bin/activate
python src/run_all_data_ingestions.py
uvicorn main:app --app-dir src --host 0.0.0.0 --port 8001
```

To enable the LLM proxy endpoint:

```bash
export OPENROUTER_API_KEY=...
```

## Environment

`.env.example` documents the runtime contract:

- `HOST` / `PORT` for API bind address
- `CORS_ORIGINS` for allowed frontend origins
- `OPENROUTER_API_KEY` for server-side LLM proxying

Runtime note:
- On startup, backend auto-loads missing env vars from `.env` candidates (current backend repo/worktree, workspace root, and sibling `backend`/`frontend` repos/worktrees) without overriding already-exported shell variables.

## QA

Repo-level checks:

```bash
python -m pytest
```

`pytest` now runs with coverage reporting and an `80%` fail-under gate for backend runtime modules (configured via `pytest.ini` + `.coveragerc`).

Workspace-level check (if using paired workspace scripts):

```bash
./scripts/qa-backend.sh setup-dev-env 8001
```

This runs:

- Python compile check
- `pytest` suite
- health probe
- `/skills/{skill_id}/search` smoke request

## Docker

Run directly from this repo:

```bash
docker network create stylus-dev-net 2>/dev/null || true
docker compose up -d --build
```

Stop:

```bash
docker compose down --remove-orphans
```

Health checks:

```bash
curl http://localhost:8001/health
curl -X POST http://localhost:8001/openrouter/chat/completions \
  -H "content-type: application/json" \
  -d '{"model":"openai/gpt-4o-mini","messages":[{"role":"user","content":"ping"}]}'
```

## Notes

- `src/run_all_data_ingestions.py` now rebuilds Chroma after ingestion.
- `src/debug_chroma_query.py` is a manual utility, not a pytest module.

## Codex Skills

This repo contains Codex skills under `skills/`:

- `sift-stylus-porting-auditor`
- `sift-stylus-research`
- `sift-stylus-code-helper`

Install all from one CLI command:

```bash
npx sift-stylus \
  --repo getFairAI/angel-stylus-coding-assistant
```

Install one skill only:

```bash
npx sift-stylus \
  --repo getFairAI/angel-stylus-coding-assistant \
  --skills sift-stylus-research
```

Installer package source:

- `tools/sift-stylus-skills-installer/`

## Additional Docs

- `docs/deployment-and-proxy.md` for architecture, security model, and deployment flow.
