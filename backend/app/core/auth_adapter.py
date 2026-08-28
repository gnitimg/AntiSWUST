from __future__ import annotations

import asyncio
import base64
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from parsel import Selector

from app.config import settings


@dataclass
class QRCodeInfo:
    ticket: str
    image_base64: str
    expire_at: float


@dataclass
class LoginResult:
    success: bool
    cookies: dict[str, dict[str, Any]] = field(default_factory=dict)
    user: dict[str, Any] = field(default_factory=dict)
    message: str = ""


class AuthAdapter:
    """西南科技大学统一身份认证（微信扫码）适配层。

    真实流程（来源：YDHusky/SWUST-Tools/wx_login_test.py 抓包验证）：
    1. 请求微信开放平台二维码页 open.weixin.qq.com/connect/qrconnect
       appid=wx3e5a3c590b52de4d, redirect_uri=cas.swust.edu.cn/authserver/callback
    2. 从返回 HTML 解析 .js_qrcode_img 的 src，拼接图片 URL，其末段即 uuid
    3. 轮询 open.weixin.qq.com/connect/l/qrconnect?uuid={uuid}
       用正则 wx_code='(.*)' 提取；非空即扫码确认
    4. 用 wx_code 请求回调 cas.swust.edu.cn/authserver/callback?code={wx_code}&store=
       该步 Set-Cookie 写入 CAS 认证 cookie
    5. 访问教务系统门户换取教务 cookie 并抓取用户信息
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=settings.http_timeout,
            follow_redirects=True,
            verify=False,
            trust_env=False,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_qrcode(self) -> QRCodeInfo:
        """获取微信扫码登录二维码。"""
        params = {
            "appid": settings.wx_open_appid,
            "redirect_uri": settings.swust_cas_callback_url,
            "response_type": "code",
            "scope": "snsapi_login",
        }
        resp = await self._client.get(settings.wx_qrconnect_url, params=params)
        sel = Selector(text=resp.text)
        img_src = sel.css(".js_qrcode_img::attr(src)").get()
        if not img_src:
            return QRCodeInfo(ticket="", image_base64="", expire_at=time.time())
        img_url = settings.wx_open_base + img_src
        uuid = img_url.rstrip("/").split("/")[-1]
        img_resp = await self._client.get(img_url)
        image_base64 = base64.b64encode(img_resp.content).decode()
        expire_at = time.time() + settings.swust_qrcode_timeout
        return QRCodeInfo(ticket=uuid, image_base64=image_base64, expire_at=expire_at)

    async def poll_status(self, ticket: str) -> LoginResult:
        """轮询微信扫码状态。ticket 即 uuid。

        微信 open.weixin.qq.com/connect/l/qrconnect 为长轮询，hold 约 25-35s，
        返回内容含 wx_errcode：408 未扫码 / 404 已扫码待确认 / 405 已确认(带 wx_code)。
        """
        uuid = ticket
        try:
            resp = await self._client.get(
                settings.wx_qrconnect_poll_url,
                params={"uuid": uuid},
                timeout=httpx.Timeout(60.0, connect=5.0),
            )
        except httpx.HTTPError:
            return LoginResult(False, message="waiting")

        errcode_match = re.search(r"wx_errcode=(\d+)", resp.text)
        errcode = errcode_match.group(1) if errcode_match else ""
        code_match = re.search(r"wx_code='(.*)'", resp.text)
        wx_code = code_match.group(1) if code_match else ""
        print(f"[wx-poll] errcode={errcode} wx_code={wx_code!r} len={len(resp.text)}", flush=True)

        if not wx_code:
            if errcode == "404":
                return LoginResult(False, message="scanned")
            return LoginResult(False, message="waiting")

        # 已确认，后续需访问校内服务器（cas / matrix），未连校园网/atrust 会失败
        try:
            # 请求 CAS 回调换取认证 cookie
            callback_url = f"{settings.swust_cas_callback_url}?code={wx_code}&store="
            cb_resp = await self._client.get(
                callback_url,
                headers={
                    "Referer": "https://open.weixin.qq.com/",
                    "Upgrade-Insecure-Requests": "1",
                },
            )
            auth_cookies = self._extract_cookies(cb_resp)

            # 访问教务门户，用 service 参数触发 CAS 票据换发，换取教务 cookie
            dean_login_url = f"{settings.swust_cas_login_url}?service={settings.swust_dean_base_url}?event={settings.swust_dean_portal_event}"
            dean_resp = await self._client.get(dean_login_url)
            dean_cookies = self._extract_cookies(dean_resp)
            # 若被重定向到教务首页，再抓一次
            if "matrix.dean.swust.edu.cn" in str(dean_resp.url):
                home_resp = await self._client.get(
                    f"{settings.swust_dean_base_url}?event={settings.swust_dean_portal_event}"
                )
                dean_cookies.update(self._extract_cookies(home_resp))
        except httpx.ConnectError:
            return LoginResult(False, message="network_error")
        except httpx.HTTPError:
            return LoginResult(False, message="network_error")

        all_cookies = {**auth_cookies, **dean_cookies}
        user = await self._fetch_user_profile(all_cookies)
        return LoginResult(True, all_cookies, user)

    async def wait_for_login(self, ticket: str, timeout: int | None = None) -> LoginResult:
        timeout = timeout or settings.swust_qrcode_timeout
        deadline = time.time() + timeout
        interval = settings.swust_qrcode_poll_interval
        while time.time() < deadline:
            result = await self.poll_status(ticket)
            if result.success or result.message == "expired":
                return result
            await asyncio.sleep(interval)
        return LoginResult(False, message="timeout")

    async def _fetch_user_profile(self, cookies: dict[str, Any]) -> dict[str, Any]:
        """抓取当前登录用户信息（姓名、学号）。"""
        flat = self._to_httpx_cookies(cookies)
        try:
            resp = await self._client.get(settings.swust_student_info_url, cookies=flat)
            data = resp.json()
            return {
                "name": data.get("xm") or data.get("name", ""),
                "student_id": data.get("xh") or data.get("studentId", ""),
                "raw": data,
            }
        except Exception:
            return {}

    @staticmethod
    def _extract_cookies(resp: httpx.Response) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for cookie in resp.cookies.jar:
            domain = cookie.domain or ""
            out.setdefault(domain, {})[cookie.name] = {
                "value": cookie.value,
                "domain": domain,
                "path": cookie.path or "/",
            }
        return out

    @staticmethod
    def _to_httpx_cookies(store: dict[str, Any]) -> dict[str, str]:
        flat: dict[str, str] = {}
        for domain_cookies in store.values():
            if isinstance(domain_cookies, dict):
                for name, meta in domain_cookies.items():
                    if isinstance(meta, dict):
                        flat[name] = meta.get("value", "")
                    else:
                        flat[name] = str(meta)
        return flat


auth_adapter = AuthAdapter()
