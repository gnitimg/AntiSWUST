from __future__ import annotations

import asyncio
import base64
import json
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
    detail: str = ""


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
        self._load_jar()

    async def aclose(self) -> None:
        await asyncio.to_thread(self._client.close)

    def _save_jar(self) -> None:
        """把当前 cookie jar 持久化到文件，uvicorn --reload/重启后恢复，避免已扫码用户重新登录。"""
        try:
            cookies = [
                {"name": c.name, "value": c.value or "", "domain": c.domain or "", "path": c.path or "/"}
                for c in self._client.cookies.jar
            ]
            tmp = settings.auth_jar_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")
            tmp.replace(settings.auth_jar_path)
        except OSError:
            pass

    def _load_jar(self) -> None:
        try:
            cookies = json.loads(settings.auth_jar_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return
        for c in cookies:
            try:
                self._client.cookies.set(c.get("name", ""), c.get("value", ""),
                                         domain=c.get("domain") or "", path=c.get("path") or "/")
            except Exception:
                continue

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
        try:
            await self._get(
                settings.swust_cas_login_url,
                params={"service": dean_service_url},
                timeout=httpx.Timeout(30.0, connect=5.0),
            )
        except httpx.HTTPError:
            # 预访问失败不中断：session cookie 可能仍可用（jar 持久化/上次登录残留）
            pass

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
        self._save_jar()
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

        # 已确认，后续需访问校内服务器（cas / matrix），未连校园网/atrust 会失败。
        # 注意：教务门户页渲染很慢（实测 >15s 会 ReadTimeout），但此时 SSO cookie 已随
        # 重定向链写入 jar——门户页抓取一律 best-effort，成功判据是 jar 里有教务域 cookie。
        dean_service_url = (
            f"{settings.swust_dean_base_url}?event={settings.swust_dean_portal_event}"
        )
        home_url = dean_service_url
        step_timeout = httpx.Timeout(30.0, connect=5.0)
        detail = ""

        try:
            # step1: CAS 回调换取认证 cookie（TGC）。
            # 该请求会 302 到 soa 门户并可能返回 403 页面，属正常；票据一次性，失败不可重试。
            try:
                await self._get(
                    f"{settings.swust_cas_callback_url}?code={wx_code}&store=",
                    headers={
                        "Referer": "https://open.weixin.qq.com/",
                        "Upgrade-Insecure-Requests": "1",
                    },
                    timeout=step_timeout,
                )
            except httpx.HTTPError as e:
                detail = f"CAS 回调失败: {type(e).__name__}"
                print(f"[auth] {detail}（继续，TGC 可能已随重定向写入 jar）", flush=True)

            # step2: 用 TGC 换教务票据 + 教务 SSO cookie（重定向到 matrix 门户，页面慢）
            try:
                dean_resp = await self._get(
                    settings.swust_cas_login_url,
                    params={"service": dean_service_url},
                    timeout=step_timeout,
                )
            except httpx.HTTPError as e:
                dean_resp = None
                detail = detail or f"教务门户跳转失败: {type(e).__name__}"
                print(f"[auth] 教务门户跳转异常: {type(e).__name__}: {e}（继续，检查 jar）", flush=True)

            # step3: 若已到教务首页，再抓一次确保教务 cookie 齐全（best-effort，超时不影响）
            if dean_resp is not None and "matrix.dean.swust.edu.cn" in str(dean_resp.url):
                try:
                    await self._get(home_url, timeout=step_timeout)
                except httpx.HTTPError:
                    pass

            # 成功判据：jar 中存在教务系统域的 cookie（SSO，domain=.dean.swust.edu.cn）
            all_cookies = self._extract_all_cookies()
            dean_cookies = {d: c for d, c in all_cookies.items() if "dean.swust.edu.cn" in d}
            if not dean_cookies:
                detail = detail or "未获取到教务系统会话 cookie"
                print(f"[auth] 登录失败: {detail}", flush=True)
                return LoginResult(False, message="network_error", detail=detail)

            # 登录成功，持久化 cookie jar（--reload/重启后无需重新扫码）
            self._save_jar()
            user = await self._fetch_user_profile(all_cookies)
            print(f"[auth] 登录成功 user={user.get('name', '')} cookie域数={len(all_cookies)}", flush=True)
            return LoginResult(True, all_cookies, user)
        except Exception as e:
            detail = detail or f"{type(e).__name__}: {e}"
            print(f"[auth] 登录意外异常 {type(e).__name__}: {e}", flush=True)
            return LoginResult(False, message="network_error", detail=detail)

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
