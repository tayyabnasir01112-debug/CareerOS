import asyncio
import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


class CollectorRequestError(RuntimeError):
    pass


def safe_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


class ResilientHttpClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_retries: int,
        backoff_seconds: float,
        max_concurrency: int,
        max_response_bytes: int = 5_000_000,
    ) -> None:
        self.client = client
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.max_response_bytes = max_response_bytes

    async def get_json(self, url: str, *, params: dict[str, str] | None = None) -> Any:
        async with self.semaphore:
            return await self._get_json_with_retries(url, params=params)

    async def _get_json_with_retries(self, url: str, *, params: dict[str, str] | None) -> Any:
        for attempt in range(self.max_retries + 1):
            try:
                async with self.client.stream("GET", url, params=params) as response:
                    if response.status_code == 429 or response.status_code >= 500:
                        response.raise_for_status()
                    if response.is_error:
                        raise CollectorRequestError(
                            f"Public endpoint returned HTTP {response.status_code}: {safe_url(url)}"
                        )
                    declared_length = response.headers.get("Content-Length")
                    if declared_length is not None and declared_length.isdigit():
                        if int(declared_length) > self.max_response_bytes:
                            raise CollectorRequestError(
                                "Public endpoint response exceeded "
                                f"{self.max_response_bytes} bytes: "
                                f"{safe_url(url)}"
                            )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.max_response_bytes:
                            raise CollectorRequestError(
                                "Public endpoint response exceeded "
                                f"{self.max_response_bytes} bytes: "
                                f"{safe_url(url)}"
                            )
                try:
                    return json.loads(body)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise CollectorRequestError(
                        f"Public endpoint returned invalid JSON: {safe_url(url)}"
                    ) from exc
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                if attempt >= self.max_retries:
                    raise CollectorRequestError(
                        f"Public endpoint failed after {attempt + 1} attempts: {safe_url(url)} "
                        f"({type(exc).__name__})"
                    ) from exc
                await asyncio.sleep(self.backoff_seconds * (2**attempt))
        raise AssertionError("retry loop terminated unexpectedly")
