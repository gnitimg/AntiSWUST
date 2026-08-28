from __future__ import annotations

from typing import Any

import httpx

from app.config import settings
from app.core.cookie_store import cookie_store


class SwustClient:
    """教务系统 HTTP 客户端。

    每次请求根据 session_id 从本地 cookie 存储加载 cookie，
    请求结束后将响应中更新的 cookie 回写存储以续期。
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=settings.http_timeout,
            follow_redirects=True,
            verify=False,
            trust_env=False,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Referer": settings.swust_dean_base_url,
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _load_flat_cookies(self, session_id: str) -> dict[str, str]:
        store = cookie_store.get_cookies(session_id)
        flat: dict[str, str] = {}
        if not store:
            return flat
        for domain_cookies in store.values():
            if isinstance(domain_cookies, dict):
                for name, meta in domain_cookies.items():
                    if isinstance(meta, dict):
                        flat[name] = meta.get("value", "")
                    else:
                        flat[name] = str(meta)
        return flat

    def _merge_response_cookies(self, session_id: str, resp: httpx.Response) -> None:
        new: dict[str, dict[str, Any]] = {}
        for cookie in resp.cookies.jar:
            domain = cookie.domain or ""
            new.setdefault(domain, {})[cookie.name] = {
                "value": cookie.value,
                "domain": domain,
                "path": cookie.path or "/",
            }
        if new:
            cookie_store.update_cookies(session_id, new)

    async def get(self, session_id: str, url: str, **kwargs: Any) -> httpx.Response:
        cookies = self._load_flat_cookies(session_id)
        resp = await self._client.get(url, cookies=cookies, **kwargs)
        self._merge_response_cookies(session_id, resp)
        return resp

    async def post(self, session_id: str, url: str, **kwargs: Any) -> httpx.Response:
        cookies = self._load_flat_cookies(session_id)
        resp = await self._client.post(url, cookies=cookies, **kwargs)
        self._merge_response_cookies(session_id, resp)
        return resp

    async def get_json(self, session_id: str, url: str, **kwargs: Any) -> Any:
        resp = await self.get(session_id, url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def post_json(self, session_id: str, url: str, **kwargs: Any) -> Any:
        resp = await self.post(session_id, url, **kwargs)
        resp.raise_for_status()
        return resp.json()


swust_client = SwustClient()
