from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import settings
from app.core.cookie_store import cookie_store


class SwustClient:
    """教务系统 HTTP 客户端。

    每次请求根据 session_id 从本地 cookie 存储加载 cookie，
    请求结束后将响应中更新的 cookie 回写存储以续期。

    用同步 Client + asyncio.to_thread：httpx AsyncClient 的 async TLS 在 atrust 下握手失败。
    """

    def __init__(self) -> None:
        self._client = httpx.Client(
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
        # 已用门户首页初始化过 matrix CFM 应用会话的 session（见 prime）
        self._primed: set[str] = set()

    async def prime(self, session_id: str) -> None:
        """访问学生门户首页一次，初始化 matrix.dean 的 CFM 应用会话。

        实测：带教务 SSO 冷启动直接请求 chooseCourse 事件，matrix 会返回
        「应用程序出错」页（HTTP 200 但无课程容器）；先用同一客户端打开门户
        首页建立应用会话后，选课事件才返回正常内容。每个 session 预热一次。
        """
        if session_id not in self._primed:
            try:
                portal_url = f"{settings.swust_dean_base_url}?event={settings.swust_dean_portal_event}"
                await self.get(session_id, portal_url)
                self._primed.add(session_id)
            except httpx.HTTPError:
                pass

    def unprime(self, session_id: str) -> None:
        """清除预热标记，下次请求重新初始化会话（用于会话失效后重试）。"""
        self._primed.discard(session_id)

    async def refresh_dean_session(self, session_id: str) -> bool:
        """教务 SSO 会话短命，过期后 matrix 会把请求踢回 CAS。用 session 里仍有效的
        CAS TGC 重新走一次 login?service=教务门户，换取新的教务票据并回写教务 cookie。

        返回是否成功拿到教务域 cookie（成功即可重试原请求，无需用户重新扫码）。
        """
        dean_service = f"{settings.swust_dean_base_url}?event={settings.swust_dean_portal_event}"
        try:
            await self.get(session_id, settings.swust_cas_login_url, params={"service": dean_service})
        except httpx.HTTPError:
            return False
        # 续期后教务域应有新 cookie；重新预热
        self._primed.discard(session_id)
        cookies = cookie_store.get_cookies(session_id) or {}
        return any("dean.swust.edu.cn" in d for d in cookies)

    async def aclose(self) -> None:
        await asyncio.to_thread(self._client.close)

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
        resp = await asyncio.to_thread(self._client.get, url, cookies=cookies, **kwargs)
        self._merge_response_cookies(session_id, resp)
        return resp

    async def post(self, session_id: str, url: str, **kwargs: Any) -> httpx.Response:
        cookies = self._load_flat_cookies(session_id)
        resp = await asyncio.to_thread(self._client.post, url, cookies=cookies, **kwargs)
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
