---
name: sift-stylus-code-helper
description: Provide implementation-focused Stylus guidance using backend retrieval context, with practical debugging and architecture advice and no full code generation unless explicitly requested.
---

# Skill: sift-stylus-code-helper

Use this skill when users need practical Stylus implementation help (debugging, architecture, integration patterns, and troubleshooting) grounded in retrieved sources.

## What this skill does
- Calls `search_stylus_docs` before final answers when evidence is needed.
- Prioritizes practical implementation guidance over high-level ecosystem summaries.
- Returns references-first answers with explicit caveats when retrieval is incomplete.
- Avoids full contract/application code generation unless the user explicitly asks for it.

## Trigger conditions
Use this skill for:
- Stylus debugging and error triage.
- Project structure and architecture questions.
- Integration guidance (tooling, deployment, verification, testing, CI workflows).
- Practical tradeoff questions when implementing Stylus systems.

Do not use this skill for non-Stylus topics.

## Required workflow
1. Call `search_stylus_docs` with the user question (or a refined implementation query).
2. Read `found`, `context`, `references`, and `agent_guidance` from the retrieval result.
3. If `found=false`, provide conservative best-effort guidance and clearly state uncertainty.
4. If `found=true`, answer in this order:
- Direct recommendation.
- Why this recommendation fits the retrieved evidence.
- Links from `references`.
5. Respect `agent_guidance` and avoid fabricating APIs, flags, or commands.

## Output style
- Lead with concrete next steps.
- Include a `References` section with URLs from retrieval output.
- Explicitly call out assumptions and unknowns.
- Keep answers concise and implementation-oriented.

## Backend contract
See `references/mcp-tool-contract.md` for request/response expectations.

## Endpoint mapping (remote-first)
- Tool name: `search_stylus_docs`
- Backend endpoint: `POST /skills/sift-stylus-code-helper/search`
- Expected deployment: hosted remote MCP/retrieval backend managed by your team.
- Local fallback for debugging only: `http://localhost:8001/skills/sift-stylus-code-helper/search`
- Request body:
```json
{ "prompt": "<query>" }
```
