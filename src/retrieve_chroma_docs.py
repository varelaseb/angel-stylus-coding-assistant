from chroma_query import get_chroma_documents
import re
from urllib.parse import urlparse
from research_contract import (
    answer_contract_payload,
    is_time_sensitive_query,
    iso_date_today,
)


TOOL_QUERY_HINTS = {
    "tool",
    "tools",
    "tooling",
    "sdk",
    "cli",
    "framework",
    "frameworks",
    "library",
    "libraries",
    "plugin",
    "plugins",
    "playground",
    "extension",
    "extensions",
}

CODE_REQUEST_HINTS = {
    "write code",
    "generate code",
    "implement",
    "contract example",
    "give me code",
    "code snippet",
    "full contract",
    "rust contract",
}

AGENT_GUIDANCE = {
    "behavior": "references_first",
    "code_generation": "disallowed",
    "instructions": [
        "Do not write or synthesize contract/application code.",
        "Return references, tools, and links first.",
        "When possible, point to exact repos/docs/pages for implementation details.",
        "If retrieval context is insufficient, say so explicitly instead of guessing.",
    ],
}

CANONICAL_REFERENCES = [
    {
        "title": "Stylus Docs",
        "url": "https://docs.arbitrum.io/stylus/",
        "source": "canonical",
    },
    {
        "title": "Awesome Stylus",
        "url": "https://github.com/OffchainLabs/awesome-stylus/",
        "source": "canonical",
    },
    {
        "title": "cargo-stylus",
        "url": "https://github.com/OffchainLabs/cargo-stylus",
        "source": "canonical",
    },
    {
        "title": "stylus-sdk-rs",
        "url": "https://github.com/OffchainLabs/stylus-sdk-rs",
        "source": "canonical",
    },
]

GENERIC_QUERY_TOKENS = {
    "http",
    "https",
    "www",
    "com",
    "org",
    "io",
    "net",
    "github",
    "gitlab",
    "blob",
    "tree",
    "main",
    "master",
    "contracts",
    "contract",
    "solidity",
    "stylus",
    "and",
    "the",
    "for",
    "with",
    "from",
    "into",
    "this",
    "that",
    "what",
    "when",
    "where",
    "which",
    "about",
    "your",
    "their",
    "analyze",
    "analysis",
    "return",
    "verdict",
    "porting",
    "httpsgithubcom",
}

PORTING_ANCHOR_REFERENCES = [
    {
        "title": "Ed25519 signature recovery benchmark | LimeChain",
        "url": "https://github.com/LimeChain/stylus-benchmark",
        "source": "porting_anchor",
        "section": "benchmarks",
    },
    {
        "title": "stylus-benchmark",
        "url": "https://github.com/Daniel-K-Ivanov/stylus-benchmark",
        "source": "porting_anchor",
        "section": "benchmarks",
    },
]

UNISWAP_ANCHOR_REFERENCE = {
    "title": "Unlocking DeFi Potential: How Stylus Fuels Uniswap Hook Innovation",
    "url": "https://blog.arbitrum.io/uniswap-stylus-hooks/",
    "source": "porting_anchor",
    "section": "case studies",
}

def join_chunks_limited(chunks, max_chars=10000):
    combined = ""
    for chunk in chunks:
        if len(combined) + len(chunk) > max_chars:
            break
        combined += chunk + "\n\n"
    return combined.strip()


def extract_prompt_tokens(user_prompt: str):
    prompt = user_prompt.lower()
    tokens = set()

    for tok in re.findall(r"[a-z0-9][a-z0-9_-]+", prompt):
        for part in re.split(r"[_-]+", tok):
            if len(part) < 3:
                continue
            if part in GENERIC_QUERY_TOKENS:
                continue
            if part.isdigit():
                continue
            tokens.add(part)

    for raw_url in re.findall(r"https?://[^\s)>\]]+", prompt):
        parsed = urlparse(raw_url)
        candidate = f"{parsed.netloc} {parsed.path}".lower()
        for tok in re.findall(r"[a-z0-9][a-z0-9_-]+", candidate):
            for part in re.split(r"[_-]+", tok):
                if len(part) < 3:
                    continue
                if part in GENERIC_QUERY_TOKENS:
                    continue
                if part.isdigit():
                    continue
                tokens.add(part)

    return tokens


def is_tool_query(user_prompt: str) -> bool:
    lowered = user_prompt.lower()
    return any(token in lowered for token in TOOL_QUERY_HINTS)


def is_code_request(user_prompt: str) -> bool:
    lowered = user_prompt.lower()
    if any(token in lowered for token in CODE_REQUEST_HINTS):
        return True
    if "write" in lowered and ("contract" in lowered or "code" in lowered):
        return True
    if "generate" in lowered and ("contract" in lowered or "code" in lowered):
        return True
    return False


def get_query_preferences(user_prompt: str, code_request: bool = False):
    prompt = user_prompt.lower()
    wants_tools = is_tool_query(user_prompt)
    wants_libraries = any(
        tok in prompt
        for tok in (
            "library",
            "libraries",
            "building block",
            "building blocks",
            "primitive",
            "primitives",
            "sdk",
            "framework",
            "module",
            "modules",
        )
    )
    wants_examples = any(
        tok in prompt for tok in ("example", "examples", "showcase", "tutorial", "benchmark")
    )
    wants_projects = any(
        tok in prompt for tok in ("project", "projects", "community", "ecosystem", "newest", "latest")
    )
    wants_news = any(tok in prompt for tok in ("newsletter", "news", "update", "updates"))

    preferred_sections = set()
    if wants_tools:
        preferred_sections.update({"tools", "libraries", "projects", "examples"})
    if wants_libraries:
        preferred_sections.update({"libraries", "tools"})
    if wants_examples:
        preferred_sections.update({"examples", "projects", "case studies"})
    if wants_projects:
        preferred_sections.update({"projects", "examples", "case studies"})
    if wants_news:
        preferred_sections.update({"videos", "blog", "newsletters"})

    if code_request:
        preferred_sections.update({"examples", "libraries", "tools", "projects"})

    return {
        "code_request": code_request,
        "prefer_tools": wants_tools,
        "prefer_libraries": wants_libraries,
        "prefer_examples": wants_examples,
        "prefer_projects": wants_projects,
        "prefer_news": wants_news,
        "preferred_sections": preferred_sections,
    }


def is_official_reference_url(url: str) -> bool:
    candidate = normalize_url(url).lower()
    return (
        "docs.arbitrum.io" in candidate
        or "github.com/offchainlabs/" in candidate
        or "offchainlabs.com" in candidate
    )


def infer_reference_source_type(reference: dict) -> str:
    source = (reference.get("source") or "").lower()
    url = reference.get("url") or ""

    if source == "canonical":
        return "canonical"
    if source in {"documentation", "derived_docs_root"} or is_official_reference_url(url):
        return "official"
    return "community"


def reference_domain(url: str) -> str:
    candidate = normalize_url(url).lower()
    without_scheme = re.sub(r"^https?://", "", candidate)
    return without_scheme.split("/", 1)[0]


def build_evidence_profile(references, max_items=20):
    profile = {
        "official_count": 0,
        "community_count": 0,
        "canonical_count": 0,
        "unique_domains": 0,
    }
    domains = set()

    for ref in references[:max_items]:
        source_type = infer_reference_source_type(ref)
        if source_type == "official":
            profile["official_count"] += 1
        elif source_type == "community":
            profile["community_count"] += 1
        elif source_type == "canonical":
            profile["canonical_count"] += 1

        domain = reference_domain(ref.get("url") or "")
        if domain:
            domains.add(domain)

    profile["unique_domains"] = len(domains)
    return profile


def has_recency_signal(references, max_items=12):
    for ref in references[:max_items]:
        text = " ".join(
            (
                str(ref.get("title") or ""),
                str(ref.get("description") or ""),
                str(ref.get("url") or ""),
            )
        ).lower()
        if re.search(r"\b20\d{2}\b", text):
            return True
        if any(token in text for token in ("release", "changelog", "update", "newsletter", "blog")):
            return True
    return False


def token_overlap_score(user_prompt: str, references, max_items=8):
    tokens = [tok for tok in re.findall(r"[a-z0-9]+", user_prompt.lower()) if len(tok) > 3]
    if not tokens:
        return 0

    overlap_hits = 0
    for ref in references[:max_items]:
        searchable = " ".join(
            (
                str(ref.get("title") or ""),
                str(ref.get("description") or ""),
                str(ref.get("url") or ""),
                str(ref.get("section") or ""),
                str(ref.get("repo") or ""),
            )
        ).lower()
        if any(tok in searchable for tok in tokens):
            overlap_hits += 1
    return overlap_hits


def evaluate_confidence(user_prompt: str, references, evidence_profile, time_sensitive=False) -> str:
    total_refs = len(references)
    score = 0.0

    if total_refs >= 3:
        score += 1.0
    if total_refs >= 6:
        score += 0.6
    if evidence_profile["official_count"] > 0:
        score += 0.8
    if evidence_profile["community_count"] > 0:
        score += 0.7
    if evidence_profile["canonical_count"] > 0:
        score += 0.5
    if evidence_profile["unique_domains"] >= 2:
        score += 0.8

    overlap_hits = token_overlap_score(user_prompt, references)
    if overlap_hits >= 3:
        score += 0.9
    elif overlap_hits >= 1:
        score += 0.4

    if total_refs <= 1:
        score -= 1.2
    if time_sensitive and not has_recency_signal(references):
        score -= 0.8

    if score >= 3.0:
        return "high"
    if score >= 1.5:
        return "medium"
    return "low"


def build_quality_signals(user_prompt: str, references, time_sensitive=False):
    profile = build_evidence_profile(references)
    confidence = evaluate_confidence(
        user_prompt,
        references,
        evidence_profile=profile,
        time_sensitive=time_sensitive,
    )
    return {
        "confidence": confidence,
        "time_sensitive": bool(time_sensitive),
        "evidence_profile": profile,
    }


def build_outline_links(references, max_items=5):
    links = []
    for ref in references[:max_items]:
        links.append(
            {
                "title": ref.get("title") or "Reference",
                "url": ref.get("url") or "",
                "source_type": infer_reference_source_type(ref),
            }
        )
    return links


def build_recommended_answer_outline(
    *,
    references,
    quality_signals,
    prefs,
    as_of_date: str,
    found: bool,
):
    links = build_outline_links(references)
    why = [
        "References are ranked for relevance and source quality to support fast implementation decisions.",
    ]
    caveats = []

    if quality_signals["time_sensitive"]:
        why.append(f"Time-sensitive query detected; verify release recency as of {as_of_date}.")

    if quality_signals["confidence"] != "high":
        why.append("Evidence is partial, so treat this as a best-bet recommendation.")
        caveats.append("Confidence is not high; validate against current official sources before final adoption.")

    if not found or not links:
        direct_answer = (
            "I could not find strong Stylus-specific references for this question. "
            "Refine the prompt with a concrete tool, workflow, or repo to improve precision."
        )
        caveats.append("Retrieval context is insufficient for a high-confidence recommendation.")
        return {
            "direct_answer": direct_answer,
            "why": why,
            "links": links,
            "caveats": caveats,
        }

    if prefs.get("prefer_tools"):
        direct_answer = (
            "Start with the top tooling references below; they are the most directly actionable for this request."
        )
    elif quality_signals["time_sensitive"]:
        direct_answer = (
            "Use the top references below as the current best sources, then confirm the latest release notes before execution."
        )
    else:
        direct_answer = "The references below are the most relevant sources to answer this Stylus question."

    return {
        "direct_answer": direct_answer,
        "why": why,
        "links": links,
        "caveats": caveats,
    }


def score_hit(hit, prefs):
    text = (hit.get("text") or "").lower()
    metadata = hit.get("metadata") or {}
    section = (metadata.get("section") or "").lower()
    subsection = (metadata.get("subsection") or "").lower()
    source = (metadata.get("source") or "").lower()
    repo = (metadata.get("repo") or "").lower()
    distance = hit.get("distance")

    score = 0.0
    if distance is not None:
        score += float(distance)

    # Generalized behavior: prioritize community + tooling sources by default.
    if source == "github_readme" or "source: github readme" in text:
        score -= 1.1
    if source == "stylus_blog" or "source: stylus blog" in text:
        score -= 0.8
    if source == "documentation":
        score += 0.5
    if "documentation -" in text:
        score += 0.6

    # Prefer practical ecosystem slices over baseline docs/tutorials.
    if section in {"tools", "libraries", "examples", "projects", "case studies"}:
        score -= 1.2
    if any(marker in text for marker in (
        "section: tools",
        "section: libraries",
        "section: examples",
        "section: projects",
        "stylus sprint recipients",
        "case studies",
    )):
        score -= 0.9

    # Prefer chunks that contain multiple outbound references.
    link_count = len(extract_markdown_links(hit.get("text") or ""))
    score -= min(link_count * 0.08, 1.0)

    # De-prioritize simple tutorial boilerplate/code-dump chunks.
    if "this code has yet to be audited" in text and "src/main.rs" in text:
        score += 0.7

    # Keep tooling-oriented queries sharper but still generalized.
    if prefs["prefer_tools"]:
        if "awesome-stylus" in repo:
            score -= 0.5
        if "cargo-stylus" in repo or "stylus-sdk-rs" in repo:
            score -= 0.25
    if prefs["prefer_libraries"]:
        if section == "libraries" or "section: libraries" in text:
            score -= 1.0
        if "building blocks" in text or "primitives" in text or "optimized" in text:
            score -= 0.35
    if prefs["prefer_examples"]:
        if section == "examples" or "section: examples" in text:
            score -= 0.55
    if prefs["prefer_projects"]:
        if section in {"projects", "case studies"}:
            score -= 0.55
    if prefs["prefer_news"]:
        if "newsletter" in text or "weekly roundup" in text:
            score -= 0.6
        if section in {"videos", "blog"} or "source: stylus blog" in text:
            score -= 0.25

    if prefs["preferred_sections"]:
        if section in prefs["preferred_sections"] or subsection in prefs["preferred_sections"]:
            score -= 0.35
    if prefs["code_request"]:
        # For code-intent prompts, prioritize implementation references (repos/examples)
        # while still returning guidance-only context.
        if source == "documentation":
            score += 0.45
        if source == "github_readme" or "source: github readme" in text:
            score -= 0.35
        if section in {"examples", "libraries", "tools", "projects"}:
            score -= 0.6

    return score


def extract_markdown_links(text: str):
    # [name](url) - description
    pattern = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)(?:[ \t]*-[ \t]*([^\n]+))?")
    links = []
    for name, url, description in pattern.findall(text or ""):
        links.append(
            {
                "name": name.strip(),
                "url": url.strip(),
                "description": (description or "").strip(),
            }
        )
    return links


def extract_plain_urls(text: str):
    pattern = re.compile(r"https?://[^\s)]+")
    return [url.strip().rstrip(".,") for url in pattern.findall(text or "")]


def normalize_url(url: str) -> str:
    return (url or "").strip().rstrip(".,'\"")


def is_allowed_reference_url(url: str) -> bool:
    candidate = normalize_url(url).lower()
    if not candidate.startswith("http://") and not candidate.startswith("https://"):
        return False
    if "localhost" in candidate or "127.0.0.1" in candidate:
        return False
    if "0.0.0.0" in candidate or "192.168." in candidate or "169.254." in candidate:
        return False
    return True


def collect_references(ranked_hits, max_items=20):
    refs = []
    seen = set()

    for hit in ranked_hits:
        metadata = hit.get("metadata") or {}
        url = metadata.get("url") or metadata.get("repo_url")
        title = metadata.get("title") or metadata.get("section") or "Reference"
        section = metadata.get("section") or ""
        source = metadata.get("source", "unknown")
        repo = metadata.get("repo") or ""

        url = normalize_url(url)
        if url and is_allowed_reference_url(url) and url not in seen:
            refs.append(
                {
                    "title": title,
                    "url": url,
                    "source": source,
                    "section": section,
                    "repo": repo,
                }
            )
            seen.add(url)
            if len(refs) >= max_items:
                break

        # Include inline links from the chunk so specific examples/tools are not lost.
        for link in extract_markdown_links(hit.get("text") or ""):
            lurl = normalize_url(link.get("url"))
            if not lurl or not is_allowed_reference_url(lurl) or lurl in seen:
                continue
            refs.append(
                {
                    "title": link.get("name") or "Reference",
                    "url": lurl,
                    "source": "inline_link",
                    "description": link.get("description", ""),
                    "section": section,
                    "repo": repo,
                }
            )
            seen.add(lurl)
            if len(refs) >= max_items:
                break

        if len(refs) >= max_items:
            break

        # Include plain URLs found in the chunk body.
        for lurl in extract_plain_urls(hit.get("text") or ""):
            lurl = normalize_url(lurl)
            if not lurl or not is_allowed_reference_url(lurl) or lurl in seen:
                continue
            refs.append(
                {
                    "title": title,
                    "url": lurl,
                    "source": "inline_url",
                    "section": section,
                    "repo": repo,
                }
            )
            seen.add(lurl)
            if len(refs) >= max_items:
                break

        if len(refs) >= max_items:
            break

        # Fallback for docs chunks that have no explicit URL metadata.
        category = (metadata.get("category") or "").strip()
        if category and "https://docs.arbitrum.io/stylus/" not in seen:
            refs.append(
                {
                    "title": f"{category} Documentation",
                    "url": "https://docs.arbitrum.io/stylus/",
                    "source": "derived_docs_root",
                    "section": category,
                }
            )
            seen.add("https://docs.arbitrum.io/stylus/")
            if len(refs) >= max_items:
                break
    return refs


def ensure_canonical_references(references, max_items=60):
    refs = list(references)
    seen = {normalize_url(ref.get("url", "")) for ref in refs}
    for ref in CANONICAL_REFERENCES:
        url = normalize_url(ref["url"])
        if url not in seen:
            refs.append(ref)
            seen.add(url)
        if len(refs) >= max_items:
            break
    return refs


def ensure_porting_anchor_references(references, user_prompt: str, max_items=60):
    refs = list(references)
    seen = {normalize_url(ref.get("url", "")) for ref in refs}
    prompt_tokens = extract_prompt_tokens(user_prompt)

    def append_anchor(anchor):
        url = normalize_url(anchor["url"])
        if url in seen:
            return
        if len(refs) >= max_items and refs:
            dropped = refs.pop()
            seen.discard(normalize_url(dropped.get("url", "")))
        refs.append(anchor)
        seen.add(url)

    limechain_url = normalize_url(PORTING_ANCHOR_REFERENCES[0]["url"])
    if limechain_url not in seen:
        append_anchor(PORTING_ANCHOR_REFERENCES[0])

    has_benchmark = any(
        "benchmark" in ((ref.get("title") or "").lower() + " " + (ref.get("url") or "").lower())
        for ref in refs
    )
    if not has_benchmark:
        for anchor in PORTING_ANCHOR_REFERENCES[1:]:
            append_anchor(anchor)
            if len(refs) >= max_items:
                return refs

    if {"uniswap", "hook", "liquidity", "pool", "amm"} & prompt_tokens:
        url = normalize_url(UNISWAP_ANCHOR_REFERENCE["url"])
        if url not in seen:
            append_anchor(UNISWAP_ANCHOR_REFERENCE)

    return refs


def build_tool_summary(hits, max_items=10):
    unique = {}
    for hit in hits:
        text = hit.get("text") or ""
        for link in extract_markdown_links(text):
            key = link["url"]
            if key not in unique:
                unique[key] = link
        if len(unique) >= max_items:
            break

    if not unique:
        return ""

    lines = ["Tool-focused results (name - URL - purpose):"]
    for link in list(unique.values())[:max_items]:
        desc = link["description"] or "See source for details."
        lines.append(f"- {link['name']} - {link['url']} - {desc}")
    return "\n".join(lines)


def rank_references_for_prompt(references, user_prompt: str, prefs, porting_mode: bool = False):
    prompt = user_prompt.lower()
    tokens = extract_prompt_tokens(user_prompt)

    def ref_score(ref):
        score = 0.0
        title = (ref.get("title") or "").lower()
        url = (ref.get("url") or "").lower()
        desc = (ref.get("description") or "").lower()
        section = (ref.get("section") or "").lower()
        source = (ref.get("source") or "").lower()
        repo = (ref.get("repo") or "").lower()
        text = f"{title} {url} {desc} {section} {source} {repo}"

        for tok in tokens:
            if tok in text:
                score -= 0.35

        # Prefer ecosystem/community references over generic docs.
        if "github.com" in url:
            score -= 0.25
        if source in {"github_readme", "inline_link"}:
            score -= 0.2
        if "docs.arbitrum.io/stylus/" in text:
            score -= 0.1
        if prefs["prefer_libraries"] and section == "libraries":
            score -= 0.4
        if prefs["prefer_news"] and (
            section in {"videos", "blog", "newsletters"}
            or "youtube.com" in url
            or "blog.arbitrum.io" in url
        ):
            score -= 0.35

        # De-prioritize infra/setup links.
        if any(k in text for k in ("devnode", "nitro-devnode", "rpc", "anvil", "localhost")):
            score += 1.2

        if "github.com" in url or "docs.arbitrum.io" in url or "gist.github.com" in url:
            score -= 0.1
        if prefs["code_request"]:
            if "docs.arbitrum.io" in url:
                score += 0.35
            if any(k in text for k in ("example", "examples", "workshop", "tutorial", "benchmark")):
                score -= 0.3
            if "github.com" in url or "gist.github.com" in url:
                score -= 0.35

        if porting_mode:
            if source == "porting_anchor":
                score -= 0.7
            if any(k in text for k in ("benchmark", "gas", "speedup", "throughput", "performance")):
                score -= 0.45
            if "blog.arbitrum.io" in url or "case study" in text:
                score -= 0.25
            if "uniswap" in tokens and "uniswap" in text:
                score -= 0.8
            if "hook" in tokens and "hook" in text:
                score -= 0.35
            if "unit testing" in text or "e2e testing" in text:
                score += 0.9
            if source in {"canonical", "derived_docs_root"}:
                score += 0.2
        return score

    return sorted(references, key=ref_score)


def build_reference_header(references, max_items=6):
    if not references:
        return ""
    lines = ["Top references:"]
    for idx, ref in enumerate(references[:max_items], 1):
        title = ref.get("title") or "Reference"
        url = ref.get("url") or ""
        lines.append(f"{idx}. [{title}]({url})")
    return "\n".join(lines)


def build_references_markdown(references, max_items=12):
    if not references:
        return ""
    lines = ["References:"]
    for ref in references[:max_items]:
        title = ref.get("title") or "Reference"
        url = ref.get("url") or ""
        lines.append(f"- [{title}]({url})")
    return "\n".join(lines)


def retrieve_stylus_context(
    user_prompt: str,
    max_chars: int = 10000,
    include_research_contract: bool = True,
):
    """
    Retrieve relevant Stylus documentation context for a given user query.

    This function does NOT call any LLM.
    It only returns retrieved documentation chunks, intended to be consumed
    by an external LLM (IDE / MCP / user-selected model).
    """
    hits = get_chroma_documents(user_prompt)
    as_of_date = iso_date_today()
    time_sensitive = is_time_sensitive_query(user_prompt)

    if not hits:
        if not include_research_contract:
            return {
                "found": False,
                "context": "",
                "reason": (
                    "No relevant Stylus documentation was found for this query. "
                    "The topic may be undocumented, outside Stylus scope, or the question may be too vague."
                ),
                "agent_guidance": AGENT_GUIDANCE,
                "references": [],
            }

        quality_signals = build_quality_signals(
            user_prompt,
            references=[],
            time_sensitive=time_sensitive,
        )
        recommended_answer_outline = build_recommended_answer_outline(
            references=[],
            quality_signals=quality_signals,
            prefs={"prefer_tools": False},
            as_of_date=as_of_date,
            found=False,
        )
        return {
            "found": False,
            "context": "",
            "reason": (
                "No relevant Stylus documentation was found for this query. "
                "The topic may be undocumented, outside Stylus scope, or the question may be too vague."
            ),
            "as_of_date": as_of_date,
            "quality_signals": quality_signals,
            "answer_contract": answer_contract_payload(),
            "recommended_answer_outline": recommended_answer_outline,
            "agent_guidance": AGENT_GUIDANCE,
            "references": [],
        }

    code_request = is_code_request(user_prompt)
    prefs = get_query_preferences(user_prompt, code_request=code_request)
    ranked_hits = sorted(
        hits,
        key=lambda hit: score_hit(hit, prefs=prefs),
    )
    docs = [hit.get("text", "") for hit in ranked_hits]
    context = join_chunks_limited(docs, max_chars=max_chars)

    if prefs["prefer_tools"]:
        tool_summary = build_tool_summary(ranked_hits)
        if tool_summary:
            context = f"{tool_summary}\n\n{context}"

    if code_request:
        context = (
            "Policy: this query appears to request code generation. "
            "For Stylus MCP consumers, return references and tooling guidance instead of writing code.\n\n"
            f"{context}"
        )

    references = collect_references(ranked_hits, max_items=60)
    if not include_research_contract:
        references = ensure_porting_anchor_references(references, user_prompt, max_items=60)
    references = rank_references_for_prompt(
        references,
        user_prompt,
        prefs,
        porting_mode=not include_research_contract,
    )
    evidence_references = list(references)
    references = ensure_canonical_references(references)
    references_markdown = build_references_markdown(references)
    ref_header = build_reference_header(references)
    if ref_header:
        context = f"{ref_header}\n\n{context}"
    if include_research_contract and time_sensitive:
        recency_note = (
            f"Recency note: this appears time-sensitive. Validate current versions/releases as of {as_of_date}."
        )
        context = f"{recency_note}\n\n{context}"

    base_payload = {
        "found": True,
        "context": context,
        "chunks_used": len(ranked_hits),
        "query_mode": "code_request" if code_request else ("tooling" if prefs["prefer_tools"] else "general"),
        "agent_guidance": AGENT_GUIDANCE,
        "references": references,
        "references_markdown": references_markdown,
    }
    if not include_research_contract:
        return base_payload

    quality_signals = build_quality_signals(
        user_prompt,
        references=evidence_references,
        time_sensitive=time_sensitive,
    )
    recommended_answer_outline = build_recommended_answer_outline(
        references=references,
        quality_signals=quality_signals,
        prefs=prefs,
        as_of_date=as_of_date,
        found=True,
    )

    base_payload.update(
        {
            "as_of_date": as_of_date,
            "quality_signals": quality_signals,
            "answer_contract": answer_contract_payload(),
            "recommended_answer_outline": recommended_answer_outline,
        }
    )
    return base_payload
