"""Optional LLM helper – one OpenAI-compatible chat completion call."""

from __future__ import annotations

import os

import httpx
from mcp.server.mcpserver.exceptions import ToolError


class LLMError(ToolError):
    """Readable AI provider error without leaking headers or keys."""


async def complete(system: str, user: str) -> str:
    """Send a chat completion request to any OpenAI-compatible endpoint."""
    base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
    except httpx.TimeoutException as exc:
        raise LLMError("AI provider timed out – try again.") from exc
    except httpx.HTTPError as exc:
        raise LLMError("Could not reach AI provider – check LLM_BASE_URL.") from exc

    if resp.status_code == 401:
        raise LLMError("AI provider rejected credentials – check LLM_API_KEY.")
    if resp.status_code == 429:
        raise LLMError("AI provider rate limit hit – wait and retry.")
    if resp.status_code >= 400:
        raise LLMError(f"AI provider error {resp.status_code}.")
    return resp.json()["choices"][0]["message"]["content"]
