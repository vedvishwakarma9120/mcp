"""Tests for github_client: success, 404, rate-limit, and cache hit."""

from __future__ import annotations

import time

import httpx
import pytest
import respx

from github_mcp.github_client import GitHubClient, GitHubError, cache_clear
from github_mcp.llm import LLMError, complete

BASE = "https://api.github.com"


@pytest.fixture()
def client():
    c = GitHubClient(token="test-token")
    cache_clear()
    return c


# -- Success path ----------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_search_repositories_success(client: GitHubClient):
    respx.get(f"{BASE}/search/repositories").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "full_name": "owner/repo",
                        "description": "A repo",
                        "stargazers_count": 42,
                        "language": "Python",
                        "html_url": "https://github.com/owner/repo",
                    }
                ]
            },
        )
    )

    result = await client.search_repositories("test")
    assert len(result) == 1
    assert result[0]["full_name"] == "owner/repo"
    assert result[0]["stars"] == 42


# -- 404 message -----------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_404_raises_readable_error(client: GitHubClient):
    respx.get(f"{BASE}/repos/owner/nope/issues").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    with pytest.raises(GitHubError, match="Not found"):
        await client.list_open_issues("owner", "nope")


# -- Rate-limit message ----------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_rate_limit_raises_with_reset(client: GitHubClient):
    reset_time = str(int(time.time()) + 60)
    respx.get(f"{BASE}/repos/owner/repo/pulls").mock(
        return_value=httpx.Response(
            429,
            headers={"x-ratelimit-reset": reset_time},
            json={"message": "rate limit"},
        )
    )

    with pytest.raises(GitHubError, match="rate limit hit") as exc_info:
        await client.list_pull_requests("owner", "repo")
    assert exc_info.value.status == 429


# -- Cache hit (second call makes no HTTP request) -------------------------

@respx.mock
@pytest.mark.asyncio
async def test_cache_hit_skips_http(client: GitHubClient):
    route = respx.get(f"{BASE}/search/repositories").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "full_name": "owner/repo",
                        "description": "A repo",
                        "stargazers_count": 1,
                        "language": "Python",
                        "html_url": "https://github.com/owner/repo",
                    }
                ]
            },
        )
    )

    # First call – hits the API
    r1 = await client.search_repositories("cached-query")
    assert route.call_count == 1

    # Second call – should come from cache, no new HTTP request
    r2 = await client.search_repositories("cached-query")
    assert route.call_count == 1  # still 1
    assert r1 == r2


# -- Issue details & file contents -----------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_get_issue_details(client: GitHubClient):
    respx.get(f"{BASE}/repos/owner/repo/issues/5").mock(
        return_value=httpx.Response(
            200,
            json={
                "number": 5,
                "title": "Crash on start",
                "state": "open",
                "user": {"login": "alice"},
                "body": "Steps to repro",
                "labels": [{"name": "bug"}],
                "html_url": "https://github.com/owner/repo/issues/5",
            },
        )
    )
    respx.get(f"{BASE}/repos/owner/repo/issues/5/comments").mock(
        return_value=httpx.Response(
            200,
            json=[{"user": {"login": "bob"}, "created_at": "2026-01-01", "body": "Same here"}],
        )
    )

    detail = await client.get_issue_details("owner", "repo", 5)
    assert detail["title"] == "Crash on start"
    assert detail["comments"][0]["user"] == "bob"


@respx.mock
@pytest.mark.asyncio
async def test_get_file_contents_and_directory_error(client: GitHubClient):
    import base64

    encoded = base64.b64encode(b"print('hi')").decode()
    respx.get(f"{BASE}/repos/owner/repo/contents/src/app.py").mock(
        return_value=httpx.Response(200, json={"content": encoded})
    )
    respx.get(f"{BASE}/repos/owner/repo/contents/src").mock(
        return_value=httpx.Response(200, json=[{"name": "app.py"}])
    )

    assert await client.get_file_contents("owner", "repo", "/src/app.py") == "print('hi')"
    with pytest.raises(GitHubError, match="directory"):
        await client.get_file_contents("owner", "repo", "src")


# -- LLM error handling ----------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_llm_rate_limit_raises_readable_error(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": "rate limit"})
    )

    with pytest.raises(LLMError, match="rate limit"):
        await complete("sys", "usr")


def test_empty_token_omits_auth_header():
    c = GitHubClient("")
    assert "Authorization" not in c._client.headers
