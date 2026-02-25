from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
import uvicorn
import time
import os
from pathlib import Path
import requests

from basic_logs import write_request_log
from research_contract import (
    answer_contract_payload,
    default_quality_signals,
    fallback_recommended_outline,
    is_time_sensitive_query,
    iso_date_today,
)
from skill_registry import (
    SKILL_ID_PORTING_AUDITOR,
    SKILL_ID_RESEARCH,
    get_skill,
    list_skills,
    run_skill_search,
)

app = FastAPI()
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_AGENT_GUIDANCE = {
    "behavior": "references_first",
    "code_generation": "disallowed",
    "instructions": [
        "Do not write or synthesize contract/application code.",
        "Return references, tools, and links first.",
        "When possible, point to exact repos/docs/pages for implementation details.",
        "If retrieval context is insufficient, say so explicitly instead of guessing.",
    ],
}


def _iter_env_file_candidates():
    repo_root = Path(__file__).resolve().parent.parent
    candidates = [
        repo_root / ".env",
        repo_root / ".env.local",
        Path.cwd() / ".env",
        Path.cwd() / ".env.local",
    ]

    for ancestor in [repo_root.parent, repo_root.parent.parent, repo_root.parent.parent.parent]:
        candidates.extend(
            [
                ancestor / ".env",
                ancestor / ".env.local",
                ancestor / "backend" / ".env",
                ancestor / "backend" / ".env.local",
                ancestor / "frontend" / ".env",
                ancestor / "frontend" / ".env.local",
            ]
        )

        worktrees_dir = ancestor / "worktrees"
        if worktrees_dir.exists() and worktrees_dir.is_dir():
            for entry in sorted(worktrees_dir.iterdir()):
                if not entry.is_dir():
                    continue
                candidates.append(entry / ".env")
                candidates.append(entry / ".env.local")

    seen = set()
    unique = []
    for path in candidates:
        resolved = str(path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def _parse_env_line(raw_line: str):
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None, None

    if line.startswith("export "):
        line = line[len("export ") :].strip()
    if "=" not in line:
        return None, None

    key, raw_value = line.split("=", 1)
    key = key.strip()
    if not key:
        return None, None

    value = raw_value.strip()
    if value and value[0] in {"'", '"'} and value[-1] == value[0]:
        value = value[1:-1]
    return key, value


def _load_env_file(path: Path):
    loaded = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return loaded

    for raw_line in lines:
        key, value = _parse_env_line(raw_line)
        if not key:
            continue
        if key in os.environ:
            continue
        os.environ[key] = value
        loaded += 1
    return loaded


def bootstrap_env_from_files():
    loaded_files = []
    for path in _iter_env_file_candidates():
        if not path.exists() or not path.is_file():
            continue
        count = _load_env_file(path)
        if count > 0:
            loaded_files.append(str(path))
    return loaded_files


# Allow local runs to pick up .env files without requiring manual export.
bootstrap_env_from_files()


def parse_cors_origins() -> list:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StylusRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


def prompt_preview(value: str, max_chars: int = 180) -> str:
    return (value or "").replace("\n", " ").strip()[:max_chars]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/skills")
def skills_index():
    return {"skills": list_skills()}


def execute_skill_search(skill_id: str, request: StylusRequest):
    preview = prompt_preview(request.prompt)
    write_request_log(f"User started a skill request | skill={skill_id} | Prompt preview: {preview}")
    start_time = time.time()
    as_of_date = iso_date_today()
    time_sensitive = is_time_sensitive_query(request.prompt)

    try:
        result = run_skill_search(skill_id, request.prompt)
    except Exception as exc:
        write_request_log(f"[error] Skill retrieval failed | skill={skill_id} | {type(exc).__name__}: {exc}")
        result = {
            "found": False,
            "context": "",
            "reason": "Retrieval failed due to an internal error.",
            "agent_guidance": DEFAULT_AGENT_GUIDANCE,
            "references": [],
            "skill": skill_id,
        }

        if skill_id == SKILL_ID_RESEARCH:
            result["as_of_date"] = as_of_date
            result["quality_signals"] = default_quality_signals(
                confidence="low",
                time_sensitive=time_sensitive,
            )
            result["answer_contract"] = answer_contract_payload()
            result["recommended_answer_outline"] = fallback_recommended_outline(
                retrieval_failed=True,
            )

    duration = round(time.time() - start_time, 2)
    preview = (result.get("context") or result.get("reason") or "")[:80]
    write_request_log(f"✅ Finished skill retrieval | skill={skill_id} | Time: {duration}s | Preview: {preview}...")

    # Return retrieval payload (MCP/IDE/LLM will decide what to do with it)
    return result


@app.post("/skills/{skill_id}/search")
def skill_search(skill_id: str, request: StylusRequest):
    if not get_skill(skill_id):
        raise HTTPException(status_code=404, detail=f"Unsupported skill '{skill_id}'.")
    return execute_skill_search(skill_id, request)


@app.post("/stylus-chat")
def stylus_chat(request: StylusRequest):
    return execute_skill_search(SKILL_ID_RESEARCH, request)


@app.post("/stylus-porting-audit")
def stylus_porting_audit(request: StylusRequest):
    return execute_skill_search(SKILL_ID_PORTING_AUDITOR, request)


@app.post("/openrouter/chat/completions")
def openrouter_chat_completions(payload: dict):
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="OPENROUTER_API_KEY is not configured on the backend.",
        )

    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Payload must be a JSON object.")

    proxy_payload = dict(payload)
    proxy_payload["stream"] = False

    try:
        upstream = requests.post(
            OPENROUTER_CHAT_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=proxy_payload,
            timeout=45,
        )
    except requests.RequestException as exc:
        write_request_log(f"[error] OpenRouter proxy request failed | {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail="OpenRouter proxy request failed.") from exc

    content_type = upstream.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            return JSONResponse(status_code=upstream.status_code, content=upstream.json())
        except ValueError:
            return PlainTextResponse(status_code=upstream.status_code, content=upstream.text)
    return PlainTextResponse(status_code=upstream.status_code, content=upstream.text)


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8001"))
    uvicorn.run("main:app", host=host, port=port)
