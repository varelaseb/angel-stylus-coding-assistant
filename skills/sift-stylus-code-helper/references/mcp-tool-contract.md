# MCP Tool Contract: `search_stylus_docs`

## Purpose
Retrieve relevant Arbitrum Stylus implementation context before composing practical guidance.

## Tool name
`search_stylus_docs`

## Input schema
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Natural language query describing the implementation/debugging question."
    }
  },
  "required": ["query"]
}
```

## Invocation policy
- Call this tool for technical Stylus implementation questions.
- Prefer at least one tool call before final answer generation.
- If output indicates no relevant context, state that limitation explicitly.
- Treat `agent_guidance` as normative behavior.

## Backend mapping
- Hosted backend endpoint: `POST /skills/sift-stylus-code-helper/search`
- Request body:
```json
{ "prompt": "<query>" }
```

## Expected response shape
```json
{
  "found": true,
  "context": "...",
  "references": [
    { "title": "...", "url": "...", "source": "..." }
  ],
  "agent_guidance": {
    "behavior": "references_first",
    "code_generation": "disallowed",
    "instructions": ["..."]
  }
}
```

or

```json
{
  "found": false,
  "reason": "No relevant Stylus documentation was found for this query.",
  "references": [],
  "agent_guidance": {
    "behavior": "references_first",
    "code_generation": "disallowed",
    "instructions": ["..."]
  }
}
```

## Consumer guidance
- Convert retrieved context into concrete implementation steps.
- Cite retrieved references for all non-trivial claims.
- Do not fabricate APIs or commands absent from retrieved material.
