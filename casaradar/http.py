"""Cliente HTTP educado: user-agent realista, pausas entre pedidos, retries simples."""

from __future__ import annotations

import logging
import os
import random
import time

import httpx

log = logging.getLogger("casaradar.http")

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


class BlockedError(Exception):
    """O site respondeu com um bloqueio (403/429/captcha)."""


class Fetcher:
    def __init__(self, delay: float = 2.0, timeout: float = 30.0, user_agent: str | None = None, retries: int = 2):
        headers = {
            "User-Agent": user_agent or DEFAULT_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
            "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.6",
            "Cache-Control": "no-cache",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Ch-Ua": '"Chromium";v="128", "Google Chrome";v="128", "Not;A=Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
        proxy = os.environ.get("CASARADAR_PROXY")
        self._client = httpx.Client(headers=headers, timeout=timeout, follow_redirects=True, proxy=proxy)
        self.delay = delay
        self.retries = retries
        self._last_request = 0.0

    def _pause(self) -> None:
        elapsed = time.monotonic() - self._last_request
        wait = self.delay + random.uniform(0, self.delay / 2) - elapsed
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, **kwargs) -> str:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            self._pause()
            self._last_request = time.monotonic()
            try:
                resp = self._client.get(url, **kwargs)
            except httpx.HTTPError as exc:
                last_exc = exc
                log.warning("erro de rede em %s (%s), tentativa %d", url, exc, attempt + 1)
                time.sleep(2 ** attempt)
                continue
            if resp.status_code in (403, 429) or _looks_like_captcha(resp.text):
                raise BlockedError(f"{url} -> HTTP {resp.status_code} (bloqueio anti-bot)")
            if resp.status_code >= 500:
                last_exc = httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.text
        raise last_exc or RuntimeError(f"falha ao obter {url}")

    def close(self) -> None:
        self._client.close()


def _looks_like_captcha(body: str) -> bool:
    head = body[:4000].lower()
    return any(marker in head for marker in ("captcha-delivery", "datadome", "cf-chl-", "are you a human", "geo.captcha"))
