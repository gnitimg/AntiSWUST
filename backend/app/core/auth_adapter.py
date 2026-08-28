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
        # 注意：用同步 Client 而非 AsyncClient——httpx AsyncClient 的 async TLS backend
        # 在 atrust VPN 环境下握手失败（ConnectError at start_tls），同步 Client 正常。
        # 请求通过 asyncio.to_thread 包装为异步。
        self._client = httpx.Client(
            timeout=settings.http_timeout,
            follow_redirects=True,
            verify=False,
            trust_env=False,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            },
        )
        self._last_wx_code: str = ""

    async def aclose(self) -> None:
        await asyncio.to_thread(self._client.close)

    async def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await asyncio.to_thread(self._client.get, url, **kwargs)

    async def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await asyncio.to_thread(self._client.post, url, **kwargs)

    async def get_qrcode(self) -> QRCodeInfo:
        """获取微信扫码登录二维码。

        必须先访问 CAS 登录页获取 session cookie（route + SESSION），
        否则后续 callback 请求无法被 CAS 识别，返回 200 空页面不设 cookie。
        """
        dean_service_url = (
            f"{settings.swust_dean_base_url}?event={settings.swust_dean_portal_event}"
        )
        await self._get(
            settings.swust_cas_login_url,
            params={"service": dean_service_url},
        )

        params = {
            "appid": settings.wx_open_appid,
            "redirect_uri": settings.swust_cas_callback_url,
            "response_type": "code",
            "scope": "snsapi_login",
        }
        resp = await self._get(settings.wx_qrconnect_url, params=params)
        sel = Selector(text=resp.text)
        img_src = sel.css(".js_qrcode_img::attr(src)").get()
        if not img_src:
            return QRCodeInfo(ticket="", image_base64="", expire_at=time.time())
        img_url = settings.wx_open_base + img_src
        uuid = img_url.rstrip("/").split("/")[-1]
        img_resp = await self._get(img_url)
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
            resp = await self._get(
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

        if not wx_code:
            if errcode == "404":
                return LoginResult(False, message="scanned")
            return LoginResult(False, message="waiting")

        if wx_code == self._last_wx_code:
            return LoginResult(False, message="waiting")
        self._last_wx_code = wx_code

        # 已确认，后续需访问校内服务器（cas / matrix），未连校园网/atrust 会失败
        import traceback as _tb
        _dbg = open("/tmp/auth_debug.log", "a", encoding="utf-8")
        def _d(msg: str) -> None:
            line = f"[{time.strftime('%H:%M:%S')}] {msg}"
            print(line, flush=True)
            _dbg.write(line + "\n"); _dbg.flush()
        try:
            dean_service_url = (
                f"{settings.swust_dean_base_url}?event={settings.swust_dean_portal_event}"
            )

            # 请求 CAS 回调换取认证 cookie
            callback_url = f"{settings.swust_cas_callback_url}?code={wx_code}&store="
            _d(f"step1 请求 callback: {callback_url[:80]}")
            _d(f"  client jar cookies: {list(self._client.cookies.jar)}")
            cb_resp = await self._get(
                callback_url,
                headers={
                    "Referer": "https://open.weixin.qq.com/",
                    "Upgrade-Insecure-Requests": "1",
                },
            )
            _d(f"step1 done status={cb_resp.status_code} url={str(cb_resp.url)[:80]}")
            _d(f"  history: {[str(r.url)[:60] for r in cb_resp.history]}")
            _d(f"  resp.cookies: {dict(cb_resp.cookies)}")
            _d(f"  body head 300: {cb_resp.text[:300]}")

            # 访问教务门户，用 service 参数触发 CAS 票据换发，换取教务 cookie
            _d(f"step2 请求 dean_login: {settings.swust_cas_login_url}")
            dean_resp = await self._get(
                settings.swust_cas_login_url,
                params={"service": dean_service_url},
            )
            _d(f"step2 done status={dean_resp.status_code} url={str(dean_resp.url)[:80]}")
            _d(f"  history: {[str(r.url)[:60] for r in dean_resp.history]}")
            _d(f"  resp.cookies: {dict(dean_resp.cookies)}")

            # 从整个 client cookie jar 提取（包含重定向链中所有 302 设置的 cookie）
            all_cookies = self._extract_all_cookies()
            _d(f"  all_cookies domains: {list(all_cookies.keys())}")

            # 若被重定向到教务首页，再抓一次确保拿到教务 cookie
            if "matrix.dean.swust.edu.cn" in str(dean_resp.url):
                home_url = f"{settings.swust_dean_base_url}?event={settings.swust_dean_portal_event}"
                _d(f"step3 请求 home: {home_url[:80]}")
                home_resp = await self._get(home_url)
                _d(f"step3 done status={home_resp.status_code} resp.cookies: {dict(home_resp.cookies)}")
                all_cookies = self._extract_all_cookies()
                _d(f"  all_cookies domains: {list(all_cookies.keys())}")
            else:
                _d("step3 跳过（dean_resp 未到 matrix）")

            if not all_cookies:
                _d("!! all_cookies 为空，登录失败")
                return LoginResult(False, message="network_error")

            user = await self._fetch_user_profile(all_cookies)
            _d(f"完成 user={user} cookie域数={len(all_cookies)}")
            return LoginResult(True, all_cookies, user)
        except httpx.ConnectError as e:
            _d(f"ConnectError: {e}\n{_tb.format_exc()}")
            return LoginResult(False, message="network_error")
        except httpx.HTTPError as e:
            _d(f"HTTPError {type(e).__name__}: {e}\n{_tb.format_exc()}")
            return LoginResult(False, message="network_error")
        except Exception as e:
            _d(f"意外异常 {type(e).__name__}: {e}\n{_tb.format_exc()}")
            return LoginResult(False, message="network_error")
        finally:
            _dbg.close()

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
            resp = await self._get(settings.swust_student_info_url, cookies=flat)
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

    def _extract_all_cookies(self) -> dict[str, dict[str, Any]]:
        """从 client cookie jar 提取所有累积 cookie（含重定向链中 302 设置的 cookie）。"""
        out: dict[str, dict[str, Any]] = {}
        for cookie in self._client.cookies.jar:
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
