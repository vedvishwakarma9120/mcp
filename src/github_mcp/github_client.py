"""Async GitHub REST API client with friendly errors and a tiny TTL cache."""

from __future__ import annotations

import logging
import time

import httpx
from mcp.server.mcpserver.exceptions import ToolError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class GitHubError(ToolError):
    """Readable GitHub API error. The message is safe to show to the AI."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


def _raise_for_status(response: httpx.Response) -> None:
    """Turn common HTTP errors into GitHubError with one-line messages."""
    code = response.status_code
    if code < 400:
        return
    if code == 401:
        raise GitHubError(401, "Bad credentials – check GITHUB_TOKEN.")
    if code == 404:
        raise GitHubError(404, "Not found – check the owner/repo/number.")
    if code in (403, 429):
        reset = response.headers.get("x-ratelimit-reset", "")
        msg = "GitHub rate limit hit."
        if reset:
            try:
                wait = int(reset) - int(time.time())
                if wait > 0:
                    msg += f" Resets in {wait}s."
            except ValueError:
                pass
        raise GitHubError(code, msg)
    raise GitHubError(code, f"GitHub API error {code}.")


# ---------------------------------------------------------------------------
# TTL cache – GET only, 60 s, in-memory
# shortcut: in-memory, lost on restart, use Redis if it must persist
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, object]] = {}
_TTL = 60.0


def _cache_get(key: str) -> object | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if time.monotonic() - ts > _TTL:
        del _cache[key]
        return None
    return value


def _cache_set(key: str, value: object) -> None:
    _cache[key] = (time.monotonic(), value)


def cache_clear() -> None:
    """Clear the whole cache. Useful in tests."""
    _cache.clear()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

API = "https://api.github.com"


class GitHubClient:
    """Thin async wrapper around the GitHub REST API."""

    def __init__(self, token: str = "") -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(base_url=API, headers=headers, timeout=15.0)

    async def close(self) -> None:
        await self._client.aclose()

    # -- low-level GET with cache ------------------------------------------

    async def _get(self, path: str, params: dict | None = None) -> object:
        """GET *path*, return parsed JSON. Uses the TTL cache."""
        # Build a stable cache key from path + sorted params
        key = path
        if params:
            key += "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))

        cached = _cache_get(key)
        if cached is not None:
            logger.debug("cache hit: %s", key)
            return cached

        resp = await self._client.get(path, params=params)
        _raise_for_status(resp)
        data = resp.json()
        _cache_set(key, data)
        return data

    # -- public methods used by server.py tools ----------------------------

    async def search_repositories(self, query: str, limit: int = 5) -> list[dict]:
        """Search repos and return trimmed results."""
        raw = await self._get("/search/repositories", {"q": query, "per_page": limit})
        return [
            {
                "full_name": r["full_name"],
                "description": r.get("description", ""),
                "stars": r["stargazers_count"],
                "language": r.get("language"),
                "url": r["html_url"],
            }
            for r in raw["items"]  # type: ignore[index]
        ]

    async def list_open_issues(self, owner: str, repo: str, limit: int = 10) -> list[dict]:
        """List open issues (excludes pull requests)."""
        raw = await self._get(
            f"/repos/{owner}/{repo}/issues",
            {"state": "open", "per_page": limit},
        )
        return [
            {
                "number": i["number"],
                "title": i["title"],
                "user": i["user"]["login"],
                "created_at": i["created_at"],
                "labels": [l["name"] for l in i["labels"]],
                "url": i["html_url"],
            }
            for i in raw  # type: ignore[union-attr]
            if "pull_request" not in i  # GitHub issues endpoint includes PRs
        ]

    async def list_pull_requests(
        self, owner: str, repo: str, state: str = "open", limit: int = 10
    ) -> list[dict]:
        """List pull requests."""
        raw = await self._get(
            f"/repos/{owner}/{repo}/pulls",
            {"state": state, "per_page": limit},
        )
        return [
            {
                "number": p["number"],
                "title": p["title"],
                "user": p["user"]["login"],
                "state": p["state"],
                "created_at": p["created_at"],
                "url": p["html_url"],
            }
            for p in raw  # type: ignore[union-attr]
        ]

    async def find_stale_issues(
        self, owner: str, repo: str, days: int = 30
    ) -> list[dict]:
        """Open issues with no activity in *days* days."""
        since_cutoff = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400)
        )
        # Get open issues sorted by last update (ascending = oldest first)
        raw = await self._get(
            f"/repos/{owner}/{repo}/issues",
            {
                "state": "open",
                "sort": "updated",
                "direction": "asc",
                "per_page": 100,
            },
        )
        stale = []
        for i in raw:  # type: ignore[union-attr]
            if "pull_request" in i:
                continue
            if i["updated_at"] < since_cutoff:
                stale.append(
                    {
                        "number": i["number"],
                        "title": i["title"],
                        "updated_at": i["updated_at"],
                        "url": i["html_url"],
                    }
                )
        return stale

    async def get_readme(self, owner: str, repo: str) -> str:
        """Return the decoded README content."""
        import base64

        raw = await self._get(f"/repos/{owner}/{repo}/readme")
        return base64.b64decode(raw["content"]).decode()  # type: ignore[index]

    async def get_issue_details(self, owner: str, repo: str, number: int) -> dict:
        """Return trimmed issue body and up to 10 recent comments."""
        issue = await self._get(f"/repos/{owner}/{repo}/issues/{number}")
        comments = await self._get(
            f"/repos/{owner}/{repo}/issues/{number}/comments",
            {"per_page": 10},
        )
        return {
            "number": issue["number"],  # type: ignore[index]
            "title": issue["title"],  # type: ignore[index]
            "state": issue["state"],  # type: ignore[index]
            "user": issue["user"]["login"],  # type: ignore[index]
            "body": (issue.get("body") or "")[:4000],  # type: ignore[union-attr]
            "labels": [label["name"] for label in issue["labels"]],  # type: ignore[index]
            "comments": [
                {
                    "user": c["user"]["login"],
                    "created_at": c["created_at"],
                    "body": (c.get("body") or "")[:500],
                }
                for c in comments  # type: ignore[union-attr]
            ],
            "url": issue["html_url"],  # type: ignore[index]
        }

    async def get_file_contents(self, owner: str, repo: str, path: str) -> str:
        """Return decoded text content of a file in a repo (max 12,000 chars)."""
        import base64

        clean = path.lstrip("/")
        raw = await self._get(f"/repos/{owner}/{repo}/contents/{clean}")
        if isinstance(raw, list):
            raise GitHubError(400, "Path is a directory – pass a file path.")
        content = raw.get("content", "")  # type: ignore[union-attr]
        return base64.b64decode(content).decode(errors="replace")[:12000]

    async def get_pull_diff(self, owner: str, repo: str, number: int) -> str:
        """Return the diff of a pull request (plain text)."""
        resp = await self._client.get(
            f"/repos/{owner}/{repo}/pulls/{number}",
            headers={"Accept": "application/vnd.github.diff"},
        )
        _raise_for_status(resp)
        return resp.text

    async def get_pull_info(self, owner: str, repo: str, number: int) -> dict:
        """Return trimmed PR metadata."""
        raw = await self._get(f"/repos/{owner}/{repo}/pulls/{number}")
        return {
            "number": raw["number"],  # type: ignore[index]
            "title": raw["title"],  # type: ignore[index]
            "user": raw["user"]["login"],  # type: ignore[index]
            "body": (raw.get("body") or "")[:2000],  # type: ignore[union-attr]
            "changed_files": raw["changed_files"],  # type: ignore[index]
            "additions": raw["additions"],  # type: ignore[index]
            "deletions": raw["deletions"],  # type: ignore[index]
        }

    async def create_issue(self, owner: str, repo: str, title: str, body: str) -> dict:
        """Create a new issue. Returns trimmed result."""
        resp = await self._client.post(
            f"/repos/{owner}/{repo}/issues",
            json={"title": title, "body": body},
        )
        _raise_for_status(resp)
        data = resp.json()
        return {
            "number": data["number"],
            "title": data["title"],
            "url": data["html_url"],
        }
