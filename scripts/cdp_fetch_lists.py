"""通过 CDP 主动抓取教务系统选课列表页 HTML。

1. 找到 matrix.dean.swust.edu.cn 的 tab
2. 抓当前页 HTML，提取所有 chooseCourse 入口
3. 对每个入口 URL 依次导航，抓响应 HTML 落盘
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import websocket

CDP = "http://127.0.0.1:9222"
OUT = Path(__file__).resolve().parent.parent / "captures"
OUT.mkdir(exist_ok=True)


def find_matrix_tab() -> dict:
    with urllib.request.urlopen(CDP + "/json", timeout=5) as r:
        tabs = json.load(r)
    for t in tabs:
        if t.get("type") == "page" and "matrix.dean.swust.edu.cn" in t.get("url", ""):
            return t
    raise SystemExit("未找到 matrix.dean.swust.edu.cn 的 tab")


class Cdp:
    def __init__(self, tab: dict) -> None:
        self.ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=15)
        self.ws.settimeout(None)
        self.mid = 0
        self._pending_main: str | None = None
        self._main_body: str | None = None
        self._nav_done = False

    def send(self, method: str, params: dict | None = None) -> int:
        self.mid += 1
        m = {"id": self.mid, "method": method}
        if params:
            m["params"] = params
        self.ws.send(json.dumps(m))
        return self.mid

    def recv_id(self, i: int) -> dict:
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == i:
                return msg

    def eval(self, expr: str) -> object:
        i = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        r = self.recv_id(i)
        if "error" in r:
            return None
        return r["result"]["result"].get("value")

    def enable(self) -> None:
        self.send("Runtime.enable")
        self.send("Page.enable")
        self.send("Network.enable", {"maxPostDataSize": 65536})
        # drain hello acks
        for _ in range(3):
            self.ws.recv()

    def navigate_and_capture(self, url: str, timeout: float = 30.0) -> str:
        """导航到 url，等主请求 loadingFinished，返回响应 HTML。"""
        self._pending_main = None
        self._main_body = None
        self._nav_done = False
        deadline = time.time() + timeout
        i = self.send("Page.navigate", {"url": url})
        main_req_id: str | None = None
        bodies: dict[str, str] = {}
        req_urls: dict[str, str] = {}
        while time.time() < deadline:
            raw = self.ws.recv()
            msg = json.loads(raw)
            m = msg.get("method", "")
            p = msg.get("params", {})
            rid = p.get("requestId")
            if m == "Network.requestWillBeSent":
                ru = p.get("request", {}).get("url", "")
                req_urls[rid] = ru
                # 主 frame 的第一个请求且 URL 匹配导航目标
                if main_req_id is None and url.split("?")[0] in ru:
                    main_req_id = rid
            elif m == "Network.loadingFinished":
                if rid and rid in req_urls:
                    try:
                        gi = self.send("Network.getResponseBody", {"requestId": rid})
                        r = self.recv_id(gi)
                        body = r.get("result", {}).get("body", "")
                        bodies[rid] = body
                    except Exception:
                        pass
                    if rid == main_req_id:
                        return bodies[rid]
            elif m == "Page.frameNavigated":
                pass
            elif m == "Page.loadEventFired":
                if main_req_id and main_req_id in bodies:
                    return bodies[main_req_id]
        return self._main_body or ""


def extract_entries(html: str) -> list[str]:
    """从选课首页 HTML 提取所有 chooseCourse 入口 URL。"""
    entries: set[str] = set()
    for m in re.finditer(r'href=["\']([^"\']*chooseCourse[^"\']*)["\']', html):
        entries.add(m.group(1))
    for m in re.finditer(r'chooseCourse[:(]?[^\s"\';<>)]*', html):
        s = m.group(0)
        if "event=" in s or ":" in s:
            entries.add(s)
    return sorted(entries)


def main() -> None:
    tab = find_matrix_tab()
    print(f"[cdp] 目标 tab: {tab['url'][:100]}")
    c = Cdp(tab)
    c.enable()

    # 1. 抓当前页 HTML
    html = c.eval("document.documentElement.outerHTML") or ""
    (OUT / "00_current_chooseCourse.html").write_text(html, encoding="utf-8")
    print(f"[cdp] 当前页 HTML 长度: {len(html)}")

    # 2. 提取入口
    entries = extract_entries(html)
    print(f"[cdp] 发现 {len(entries)} 个 chooseCourse 入口:")
    for e in entries:
        print(f"   {e[:160]}")

    # 3. 对每个完整 URL 入口导航抓取
    base = "https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm"
    full_urls: list[tuple[str, str]] = []
    for e in entries:
        if e.startswith("http"):
            full_urls.append((e, e))
        elif e.startswith("?"):
            full_urls.append((base + e, e))
        elif "event=" in e:
            full_urls.append((base + "?" + e, e))
    # 去重
    seen: set[str] = set()
    uniq = []
    for u, raw in full_urls:
        if u in seen:
            continue
        seen.add(u)
        uniq.append((u, raw))

    print(f"\n[cdp] 将导航抓取 {len(uniq)} 个 URL:")
    for idx, (u, raw) in enumerate(uniq, 1):
        print(f"\n=== [{idx}] {u[:120]}")
        body = c.navigate_and_capture(u)
        fname = f"{idx:02d}_list_{int(time.time())}.html"
        (OUT / fname).write_text(body, encoding="utf-8")
        # 简析 .courseShow
        n_show = body.count("courseShow")
        n_name = len(re.findall(r'class="name"', body))
        n_trigger = len(re.findall(r'class="trigger"', body))
        print(f"    保存 {fname} 长度={len(body)} courseShow={n_show} .name={n_name} .trigger={n_trigger}")

    print("\n[cdp] 完成")


if __name__ == "__main__":
    main()
