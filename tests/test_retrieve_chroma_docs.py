import retrieve_chroma_docs as retrieval
import re


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def assert_research_contract(result):
    assert DATE_RE.match(result["as_of_date"] or "")
    assert result["answer_contract"]["format"] == "direct_answer_why_links"
    assert result["answer_contract"]["length_target_lines"] == "10-20"
    assert result["answer_contract"]["uncertainty_mode"] == "state_uncertainty_plus_best_bet"

    signals = result["quality_signals"]
    assert signals["confidence"] in {"high", "medium", "low"}
    assert isinstance(signals["time_sensitive"], bool)
    profile = signals["evidence_profile"]
    assert isinstance(profile["official_count"], int)
    assert isinstance(profile["community_count"], int)
    assert isinstance(profile["canonical_count"], int)
    assert isinstance(profile["unique_domains"], int)

    outline = result["recommended_answer_outline"]
    assert isinstance(outline["direct_answer"], str) and outline["direct_answer"].strip()
    assert isinstance(outline["why"], list) and len(outline["why"]) >= 1
    assert isinstance(outline["links"], list)
    assert isinstance(outline["caveats"], list)


def test_code_request_returns_policy_and_reference_header(monkeypatch):
    hits = [
        {
            "text": (
                "Source: GitHub README\n"
                "Repo: OffchainLabs/awesome-stylus/\n"
                "Section: Examples\n\n"
                "- [Keccak Looper](https://gist.github.com/cygaar/ee3cf1d1f98a57369717c9d91e076fd1) "
                "- A Rust contract that loops n times and hashes input"
            ),
            "metadata": {
                "source": "github_readme",
                "repo": "OffchainLabs/awesome-stylus/",
                "section": "Examples",
                "title": "Examples",
                "url": "https://github.com/OffchainLabs/awesome-stylus/",
            },
            "distance": 0.1,
        }
    ]
    monkeypatch.setattr(retrieval, "get_chroma_documents", lambda _prompt: hits)

    result = retrieval.retrieve_stylus_context(
        "Write a Rust contract that loops and hashes an input string"
    )

    assert result["found"] is True
    assert result["query_mode"] == "code_request"
    assert result["context"].startswith("Top references:")
    assert "Policy: this query appears to request code generation" in result["context"]
    assert result["agent_guidance"]["behavior"] == "references_first"
    assert result["agent_guidance"]["code_generation"] == "disallowed"
    assert_research_contract(result)
    assert result["quality_signals"]["time_sensitive"] is False
    assert len(result["recommended_answer_outline"]["links"]) >= 1


def test_reference_filter_rejects_local_urls(monkeypatch):
    hits = [
        {
            "text": (
                "- [Local Ref](http://localhost:1234/debug)\n"
                "- [Public Ref](https://github.com/LimeChain/stylus-toolkit)"
            ),
            "metadata": {
                "source": "github_readme",
                "repo": "OffchainLabs/awesome-stylus/",
                "section": "Tools",
                "title": "Tools",
                "url": "https://github.com/OffchainLabs/awesome-stylus/",
            },
            "distance": 0.2,
        }
    ]
    monkeypatch.setattr(retrieval, "get_chroma_documents", lambda _prompt: hits)

    result = retrieval.retrieve_stylus_context("What are the latest Stylus tools available?")
    urls = {ref["url"] for ref in result["references"]}

    assert "http://localhost:1234/debug" not in urls
    assert "https://github.com/LimeChain/stylus-toolkit" in urls
    assert_research_contract(result)
    assert result["quality_signals"]["time_sensitive"] is True
    assert result["context"].startswith("Recency note:")
    assert any("Time-sensitive query detected" in line for line in result["recommended_answer_outline"]["why"])


def test_no_hits_returns_structured_not_found(monkeypatch):
    monkeypatch.setattr(retrieval, "get_chroma_documents", lambda _prompt: [])

    result = retrieval.retrieve_stylus_context("query with no matches")

    assert result["found"] is False
    assert result["context"] == ""
    assert "No relevant Stylus documentation was found" in result["reason"]
    assert result["references"] == []
    assert_research_contract(result)
    assert result["quality_signals"]["confidence"] == "low"
    assert "could not find strong Stylus-specific references" in result["recommended_answer_outline"]["direct_answer"]


def test_retrieval_can_disable_research_contract_fields(monkeypatch):
    hits = [
        {
            "text": "- [Public Ref](https://github.com/LimeChain/stylus-toolkit)",
            "metadata": {
                "source": "github_readme",
                "repo": "OffchainLabs/awesome-stylus/",
                "section": "Tools",
                "title": "Tools",
                "url": "https://github.com/OffchainLabs/awesome-stylus/",
            },
            "distance": 0.2,
        }
    ]
    monkeypatch.setattr(retrieval, "get_chroma_documents", lambda _prompt: hits)

    result = retrieval.retrieve_stylus_context(
        "What are the latest Stylus tools available?",
        include_research_contract=False,
    )

    assert result["found"] is True
    assert "as_of_date" not in result
    assert "quality_signals" not in result
    assert "answer_contract" not in result
    assert "recommended_answer_outline" not in result
    assert not result["context"].startswith("Recency note:")


def test_no_hits_without_research_contract_returns_legacy_shape(monkeypatch):
    monkeypatch.setattr(retrieval, "get_chroma_documents", lambda _prompt: [])

    result = retrieval.retrieve_stylus_context(
        "query with no matches",
        include_research_contract=False,
    )

    assert result["found"] is False
    assert "as_of_date" not in result
    assert "quality_signals" not in result
    assert "answer_contract" not in result
    assert "recommended_answer_outline" not in result


def test_porting_mode_promotes_benchmark_and_uniswap_case_study(monkeypatch):
    hits = [
        {
            "text": (
                "Source: GitHub README\n"
                "Repo: OpenZeppelin/rust-contracts-stylus\n"
                "Section: Testing\n\n"
                "- [Unit Testing | Open Zepplin](https://github.com/OpenZeppelin/rust-contracts-stylus/blob/main/lib/motsu/README.md)\n"
                "- [E2E Testing | Open Zepplin](https://github.com/OpenZeppelin/rust-contracts-stylus/blob/main/lib/e2e/README.md)"
            ),
            "metadata": {
                "source": "github_readme",
                "repo": "OpenZeppelin/rust-contracts-stylus",
                "section": "Testing",
                "title": "Testing",
                "url": "https://github.com/OpenZeppelin/rust-contracts-stylus",
            },
            "distance": 0.05,
        },
        {
            "text": (
                "Source: GitHub README\n"
                "Repo: OffchainLabs/awesome-stylus/\n"
                "Section: Examples\n\n"
                "- [Ed25519 signature recovery benchmark | LimeChain](https://github.com/LimeChain/stylus-benchmark)\n"
                "- [stylus-benchmark](https://github.com/Daniel-K-Ivanov/stylus-benchmark)"
            ),
            "metadata": {
                "source": "github_readme",
                "repo": "OffchainLabs/awesome-stylus/",
                "section": "Examples",
                "title": "Examples",
                "url": "https://github.com/OffchainLabs/awesome-stylus/",
            },
            "distance": 0.25,
        },
        {
            "text": (
                "Source: Stylus Blog\n"
                "URL: https://blog.arbitrum.io/uniswap-stylus-hooks/\n"
                "Published: 2025-02-03\n\n"
                "Unlocking DeFi Potential: How Stylus Fuels Uniswap Hook Innovation"
            ),
            "metadata": {
                "source": "stylus_blog",
                "section": "Case Studies",
                "title": "Unlocking DeFi Potential: How Stylus Fuels Uniswap Hook Innovation",
                "url": "https://blog.arbitrum.io/uniswap-stylus-hooks/",
            },
            "distance": 0.3,
        },
    ]
    monkeypatch.setattr(retrieval, "get_chroma_documents", lambda _prompt: hits)

    result = retrieval.retrieve_stylus_context(
        "Analyze https://github.com/Uniswap/v3-core/blob/main/contracts/UniswapV3Pool.sol and return a porting verdict.",
        include_research_contract=False,
    )

    top_urls = [ref["url"] for ref in result["references"][:12]]
    assert any("stylus-benchmark" in url.lower() for url in top_urls)
    assert any("limechain/stylus-benchmark" in url.lower() for url in top_urls)
    assert any("uniswap-stylus-hooks" in url.lower() for url in top_urls)
