"""通过 Chrome DevTools Protocol (CDP) 实时抓取 Chrome 内教务系统请求。

前置：Chrome 需以 --remote-debugging-port=9222 --remote-allow-origins=* 启动。
用法：python3 scripts/cdp_capture.py
实时打印教务相关请求摘要，并落盘 JSON 到 captures/。
按 Ctrl+C 停止。
"""
from __future__ import annotations

import json
import os
import sys
import time
import threading
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import websocket  # websocket-client

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222

TARGET_HOSTS = (
    "matrix.dean.swust.edu.cn",
    "cas.swust.edu.cn",
    "myo.swust.edu.cn",
    "soa.swust.edu.cn",
    "open.weixin.qq.com",
)

OUT = Path(__file__).resolve().parent.parent / "captures"
OUT.mkdir(exist_ok=True)

C_TAG = {
    "选课列表": "\033[36m",
    "教学班详情": "\033[33m",
    "选课提交": "\033[31m",
    "课表": "\033[35m",
    "学生信息": "\033[34m",
    "登录认证": "\033[32m",
}
C_RST = "\033[0m"
C_SYS = "\033[33m"

MAX_BODY = 20000

_lock = threading.Lock()
_count = 0
_seen_targets: set[str] = set()


def _tag(url: str) -> str:
    if "chooseCourse" in url:
        if "apiChoose" in url:
            return "选课提交"
        if "api" in url and "Table" in url:
            return "教学班详情"
        return "选课列表"
    if "courseTable" in url:
        return "课表"
    if "courseMark" in url or "studentMark" in url:
        return "成绩"
    if "studentInfo" in url:
        return "学生信息"
    if "login" in url or "callback" in url or "qrconnect" in url or "authserver" in url:
        return "登录认证"
    return "其他"


def _log(msg: str, color: str = C_SYS) -> None:
    with _lock:
        print(f"{color}{msg}{C_RST}", flush=True)


def _list_targets() -> list[dict]:
    try:
        with urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=3) as r:
            return json.load(r)
    except Exception as e:
        _log(f"[cdp] 枚举 targets 失败: {e}")
        return []


def _save(record: dict) -> None:
    global _count
    with _lock:
        _count += 1
        n = _count
    tag = record["tag"].replace("/", "_")
    fname = f"{n:04d}_{tag}_{time.strftime('%H%M%S')}.json"
    (OUT / fname).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    color = C_TAG.get(record["tag"], "")
    body_len = len(record.get("resp_body", ""))
    _log(
        f"#{n} [{record['tag']}] {record['method']} {record['url']} "
        f"-> {record['status']} req={len(record.get('req_body', ''))}B resp={body_len}B "
        f"({record['time']})",
        color,
    )


class TabWatcher(threading.Thread):
    def __init__(self, target: dict) -> None:
        super().__init__(daemon=True)
        self.target = target
        self.ws_url = target["webSocketDebuggerUrl"]
        self.ws: websocket.WebSocket | None = None
        self._mid = 0
        self._req: dict[str, dict] = {}
        self._resp: dict[str, dict] = {}

    def _send(self, method: str, params: dict | None = None) -> int:
        self._mid += 1
        msg = {"id": self._mid, "method": method}
        if params:
            msg["params"] = params
        assert self.ws is not None
        self.ws.send(json.dumps(msg))
        return self._mid

    def run(self) -> None:
        try:
            self.ws = websocket.create_connection(self.ws_url, timeout=10)
        except Exception as e:
            _log(f"[cdp] 连接 tab 失败: {e}")
            return
        self._send("Network.enable", {"maxPostDataSize": 65536})
        _log(f"[cdp] 已 attach tab: {self.target.get('url', '?')[:80]}")
        while True:
            try:
                assert self.ws is not None
                raw = self.ws.recv()
            except Exception as e:
                _log(f"[cdp] tab ws 断开: {e}")
                return
            if not raw:
                return
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            self._handle(msg)

    def _handle(self, msg: dict) -> None:
        m = msg.get("method", "")
        params = msg.get("params", {})
        rid = params.get("requestId")
        if m == "Network.requestWillBeSent":
            req = params.get("request", {})
            url = req.get("url", "")
            host = urlparse(url).hostname or ""
            if not any(t in host for t in TARGET_HOSTS):
                return
            self._req[rid] = {
                "url": url,
                "method": req.get("method", ""),
                "headers": req.get("headers", {}),
                "post_data": req.get("postData", ""),
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "frame_id": params.get("frameId"),
            }
        elif m == "Network.responseReceived":
            if rid not in self._req:
                return
            resp = params.get("response", {})
            self._resp[rid] = {
                "status": resp.get("status", 0),
                "mime": resp.get("mimeType", ""),
                "headers": resp.get("headers", {}),
            }
        elif m == "Network.loadingFinished":
            self._finish(rid)
        elif m == "Network.loadingFailed":
            if rid in self._req:
                self._req.pop(rid, None)
                self._resp.pop(rid, None)

    def _finish(self, rid: str) -> None:
        req = self._req.pop(rid, None)
        if not req:
            return
        resp = self._resp.pop(rid, {})
        body = ""
        try:
            assert self.ws is not None
            self._send("Network.getResponseBody", {"requestId": rid})
            while True:
                raw = self.ws.recv()
                msg = json.loads(raw)
                if msg.get("id") == self._mid and "result" in msg:
                    body = msg["result"].get("body", "")
                    break
        except Exception:
            pass
        record = {
            "time": req["time"],
            "tag": _tag(req["url"]),
            "method": req["method"],
            "url": req["url"],
            "req_headers": req["headers"],
            "req_body": req["post_data"][:MAX_BODY],
            "status": resp.get("status", 0),
            "resp_mime": resp.get("mime", ""),
            "resp_headers": resp.get("headers", {}),
            "resp_body": body[:MAX_BODY],
            "resp_body_truncated": len(body) > MAX_BODY,
        }
        _save(record)


def main() -> None:
    _log(f"[cdp] 抓包脚本启动，输出目录: {OUT}")
    _log(f"[cdp] 监听域名: {', '.join(TARGET_HOSTS)}")
    while True:
        targets = _list_targets()
        pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        new = [t for t in pages if t["id"] not in _seen_targets]
        for t in new:
            _seen_targets.add(t["id"])
            TabWatcher(t).start()
        if not pages:
            _log("[cdp] 未发现任何 page tab，请确认 Chrome 已打开且有标签页")
        time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _log("[cdp] 已停止")
        sys.exit(0)
