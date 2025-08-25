from __future__ import annotations

from typing import List, Dict, Any, AsyncGenerator, Optional, Union
import httpx

from src.app.config import settings

# Reusable async clients to reduce connection overhead
_client: Optional[httpx.AsyncClient] = None
_stream_client: Optional[httpx.AsyncClient] = None


def _get_client(timeout: Optional[float] = None) -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=timeout or settings.GENERATE_TIMEOUT)
    else:
        # update timeout if provided
        if timeout is not None:
            _client.timeout = timeout
    return _client


def _get_stream_client() -> httpx.AsyncClient:
    global _stream_client
    if _stream_client is None:
        # No overall timeout for streaming; per-read uses defaults
        _stream_client = httpx.AsyncClient(timeout=None)
    return _stream_client

async def generate(prompt: str, model: Optional[str] = None, *, timeout: Optional[float] = None, keep_alive: Optional[Union[str, int]] = None, **kwargs) -> Dict[str, Any]:
    url = f"http://{settings.OLLAMA_HOST}:{settings.OLLAMA_PORT}/api/generate"
    keep_alive = keep_alive if keep_alive is not None else settings.OLLAMA_KEEP_ALIVE
    payload = {
        "model": model or getattr(settings, "OLLAMA_MODEL", "llama3"),
        "prompt": prompt,
        "stream": False,
        "keep_alive": keep_alive,
    }
    payload.update(kwargs or {})
    client = _get_client(timeout or settings.GENERATE_TIMEOUT)
    resp = await client.post(url, json=payload)
    resp.raise_for_status()
    return resp.json()


async def embeddings(texts: List[str], model: Optional[str] = None, *, timeout: Optional[float] = None) -> List[List[float]]:
    url = f"http://{settings.OLLAMA_HOST}:{settings.OLLAMA_PORT}/api/embeddings"
    vectors: List[List[float]] = []
    client = _get_client(timeout or settings.EMBED_TIMEOUT)
    for text in texts:
        payload = {
            "model": model or getattr(settings, "OLLAMA_MODEL", "llama3"),
            "prompt": text,
        }
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        vectors.append(data.get("embedding", []))
    return vectors


async def generate_stream(prompt: str, model: Optional[str] = None, *, keep_alive: Optional[Union[str, int]] = None, **kwargs) -> AsyncGenerator[str, None]:
    """Stream tokens from Ollama /api/generate (stream=true) and yield plain text chunks."""
    url = f"http://{settings.OLLAMA_HOST}:{settings.OLLAMA_PORT}/api/generate"
    keep_alive = keep_alive if keep_alive is not None else settings.OLLAMA_KEEP_ALIVE
    payload = {
        "model": model or getattr(settings, "OLLAMA_MODEL", "llama3"),
        "prompt": prompt,
        "stream": True,
        "keep_alive": keep_alive,
    }
    payload.update(kwargs or {})
    client = _get_stream_client()
    async with client.stream("POST", url, json=payload) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if not line:
                continue
            # Each line is a JSON object like {"response": "...", "done": false}
            try:
                import json
                obj = json.loads(line)
                chunk = obj.get("response", "")
                if chunk:
                    yield chunk
            except Exception:
                # Fallback: yield raw line
                yield line


async def generate_stream_raw(prompt: str, model: Optional[str] = None, *, keep_alive: Optional[Union[str, int]] = None, **kwargs) -> AsyncGenerator[str, None]:
    """Pass-through streaming: yield raw JSON-lines from Ollama as-is."""
    url = f"http://{settings.OLLAMA_HOST}:{settings.OLLAMA_PORT}/api/generate"
    keep_alive = keep_alive if keep_alive is not None else settings.OLLAMA_KEEP_ALIVE
    payload = {
        "model": model or getattr(settings, "OLLAMA_MODEL", "llama3"),
        "prompt": prompt,
        "stream": True,
        "keep_alive": keep_alive,
    }
    payload.update(kwargs or {})
    client = _get_stream_client()
    async with client.stream("POST", url, json=payload) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if line:
                yield line + "\n"
