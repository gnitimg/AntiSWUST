from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.core.auth_adapter import auth_adapter
from app.core.cookie_store import cookie_store

router = APIRouter(prefix="/api/login", tags=["login"])


class QRCodeResponse(BaseModel):
    session_id: str
    ticket: str
    image_base64: str
    expire_at: float


class StatusResponse(BaseModel):
    status: str
    session_id: str
    user: dict = {}
    detail: str = ""


@router.get("/qrcode", response_model=QRCodeResponse)
async def get_qrcode() -> QRCodeResponse:
    try:
        info = await auth_adapter.get_qrcode()
    except Exception as e:
        print(f"[get_qrcode] 获取二维码异常: {type(e).__name__}: {e}", flush=True)
        raise HTTPException(status_code=503, detail="暂时无法连接微信登录服务，请稍后重试") from e
    if not info.ticket or not info.image_base64:
        raise HTTPException(status_code=502, detail="微信登录服务未返回有效二维码，请稍后重试")
    session_id = cookie_store.create_session()
    return QRCodeResponse(
        session_id=session_id,
        ticket=info.ticket,
        image_base64=info.image_base64,
        expire_at=info.expire_at,
    )


@router.get("/status", response_model=StatusResponse)
async def login_status(session_id: str, ticket: str) -> StatusResponse:
    # aTrust 切换网卡时浏览器可能丢掉后端已经发出的成功响应；下一次轮询直接恢复结果。
    existing = cookie_store.load(session_id)
    if existing is not None:
        return StatusResponse(
            status="success",
            session_id=session_id,
            user=existing.get("user") or {},
        )

    try:
        result = await auth_adapter.poll_status(ticket)
        if result.success:
            cookie_store.save(session_id, result.cookies, result.user)
            return StatusResponse(status="success", session_id=session_id, user=result.user)
    except Exception as e:
        print(f"[login_status] poll_status 异常: {type(e).__name__}: {e}", flush=True)
        return StatusResponse(status="waiting", session_id=session_id)
    if result.message in ("expired", "scanned", "network_error"):
        return StatusResponse(status=result.message, session_id=session_id, detail=result.detail)
    return StatusResponse(status="waiting", session_id=session_id)


@router.get("/wx-debug")
async def wx_debug() -> dict:
    """诊断端点：返回微信二维码页真实解析结果，供本地验证选择器是否过时。"""
    import httpx
    from parsel import Selector

    redirect = settings.swust_cas_callback_url
    params = {
        "appid": settings.wx_open_appid,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": "snsapi_login",
    }
    async with httpx.AsyncClient(timeout=15.0, verify=False, follow_redirects=True, trust_env=False) as c:
        try:
            resp = await c.get(settings.wx_qrconnect_url, params=params)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    sel = Selector(text=resp.text)
    img_src = sel.css(".js_qrcode_img::attr(src)").get()
    return {
        "ok": True,
        "status_code": resp.status_code,
        "url": str(resp.url),
        "html_length": len(resp.text),
        "js_qrcode_img_src": img_src,
        "uuid_extracted": (settings.wx_open_base + img_src).rstrip("/").split("/")[-1] if img_src else None,
        "has_qrcode_div": bool(sel.css(".qrcode").get()),
        "img_tags": sel.css("img::attr(src)").getall()[:10],
        "html_head": resp.text[:800],
    }


@router.get("/wx-poll-debug")
async def wx_poll_debug(uuid: str) -> dict:
    """诊断端点：返回微信长轮询接口真实响应，供本地验证 wx_errcode/wx_code 格式。"""
    import httpx

    async with httpx.AsyncClient(timeout=65.0, verify=False, follow_redirects=True, trust_env=False) as c:
        try:
            resp = await c.get(settings.wx_qrconnect_poll_url, params={"uuid": uuid})
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    errcode = re.search(r"wx_errcode=(\d+)", resp.text)
    wx_code = re.search(r"wx_code='(.*)'", resp.text)
    return {
        "ok": True,
        "status_code": resp.status_code,
        "response_text": resp.text[:500],
        "wx_errcode": errcode.group(1) if errcode else None,
        "wx_code": wx_code.group(1) if wx_code else None,
    }


@router.get("/check")
async def check_session(session_id: str) -> dict:
    if not cookie_store.is_valid(session_id):
        raise HTTPException(status_code=401, detail="session expired or invalid")
    user = cookie_store.get_user(session_id) or {}
    return {"session_id": session_id, "user": user}


@router.post("/logout")
async def logout(session_id: str) -> dict:
    cookie_store.delete(session_id)
    return {"ok": True}
