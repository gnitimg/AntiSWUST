"""对五个选课分类 URL 依次导航，抓取列表页 DOM HTML 与所有网络请求。

输出到 captures/five/：
  NN_<task>.html          渲染后 DOM
  NN_<task>_requests.json 所有网络请求清单（url/method/postData/status/mime/body 摘要）
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

import websocket

CDP = "http://127.0.0.1:9222"
OUT = Path(__file__).resolve().parent.parent / "captures" / "five2"
OUT.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ("01_sportTask", "https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm?event=chooseCourse:sportTask&CT=2"),
    ("02_fixupTask", "https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm?event=chooseCourse:fixupTask&CT=2"),
    ("03_retakeTask", "https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm?event=chooseCourse:retakeTask&CT=2"),
    ("04_programTask", "https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm?event=chooseCourse:programTask&CT=2"),
    ("05_commonTask", "https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm?event=chooseCourse:commonTask&CT=2"),
]

MAX_BODY = 30000


def find_matrix_tab() -> dict:
    with urllib.request.urlopen(CDP + "/json", timeout=5) as r:
        tabs = json.load(r)
    for t in tabs:
        if t.get("type") == "page" and "matrix.dean.swust.edu.cn" in t.get("url", ""):
            return t
    raise SystemExit("未找到 matrix tab")


class Cdp:
    def __init__(self, tab: dict) -> None:
        self.ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=15)
        self.ws.settimeout(1.5)
        self.mid = 0

    def send(self, method: str, params: dict | None = None) -> int:
        self.mid += 1
        m = {"id": self.mid, "method": method}
        if params:
            m["params"] = params
        self.ws.send(json.dumps(m))
        return self.mid

    def enable(self) -> None:
        for m in ("Runtime.enable", "Page.enable", "Network.enable"):
            self.send(m, {"maxPostDataSize": 65536} if m == "Network.enable" else None)
        # drain 3 acks
        for _ in range(3):
            try:
                self.ws.recv()
            except Exception:
                pass

    def eval(self, expr: str) -> str:
        i = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                msg = json.loads(self.ws.recv())
            except Exception:
                continue
            if msg.get("id") == i:
                return msg.get("result", {}).get("result", {}).get("value", "") or ""
        return ""

    def navigate(self, url: str, settle: float = 4.0, timeout: float = 30.0) -> tuple[str, list[dict]]:
        reqs: dict[str, dict] = {}
        order: list[str] = []
        bodies: dict[str, str] = {}
        loaded = False
        load_time = 0.0
        self.send("Page.navigate", {"url": url})
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                if loaded and time.time() - load_time > settle:
                    break
                continue
            except Exception:
                continue
            msg = json.loads(raw)
            m = msg.get("method", "")
            p = msg.get("params", {})
            rid = p.get("requestId")
            if m == "Network.requestWillBeSent":
                rq = p.get("request", {})
                if rid not in reqs:
                    reqs[rid] = {
                        "url": rq.get("url", ""),
                        "method": rq.get("method", ""),
                        "post_data": rq.get("postData", ""),
                        "headers": rq.get("headers", {}),
                    }
                    order.append(rid)
            elif m == "Network.responseReceived":
                if rid in reqs:
                    rp = p.get("response", {})
                    reqs[rid]["status"] = rp.get("status", 0)
                    reqs[rid]["mime"] = rp.get("mimeType", "")
                    reqs[rid]["resp_headers"] = rp.get("headers", {})
            elif m == "Network.loadingFinished" and rid in reqs:
                try:
                    gi = self.send("Network.getResponseBody", {"requestId": rid})
                    r = self._recv_id(gi, 5.0)
                    bodies[rid] = r.get("result", {}).get("body", "")
                except Exception:
                    bodies[rid] = ""
            elif m == "Page.loadEventFired":
                loaded = True
                load_time = time.time()
            if loaded and time.time() - load_time > settle:
                break
        dom = self.eval("document.documentElement.outerHTML")
        req_list = []
        for rid in order:
            r = reqs[rid]
            r["body"] = bodies.get(rid, "")[:MAX_BODY]
            r["body_truncated"] = len(bodies.get(rid, "")) > MAX_BODY
            req_list.append(r)
        return dom, req_list

    def _recv_id(self, i: int, timeout: float) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = json.loads(self.ws.recv())
            except Exception:
                continue
            if msg.get("id") == i:
                return msg
        return {}


def main() -> None:
    # 先抓取当前所有 cookie（登录态记录）
    try:
        tab0 = find_matrix_tab()
        c0 = Cdp(tab0)
        c0.enable()
        i = c0.send("Network.getAllCookies")
        r = c0._recv_id(i, 5.0)
        cookies = r.get("result", {}).get("cookies", [])
        (OUT / "00_cookies.json").write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[cdp] 已记录 {len(cookies)} 条 cookie 到 00_cookies.json")
    except Exception as e:
        print(f"[cdp] cookie 抓取失败: {e}")

    for name, url in TARGETS:
        print(f"\n=== {name} ===\n  {url}")
        try:
            tab = find_matrix_tab()
            c = Cdp(tab)
            c.enable()
            dom, reqs = c.navigate(url, settle=6.0, timeout=45.0)
        except Exception as e:
            print(f"  失败: {type(e).__name__}: {e}")
            continue
        (OUT / f"{name}.html").write_text(dom, encoding="utf-8")
        (OUT / f"{name}_requests.json").write_text(
            json.dumps(reqs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        n_show = len([1 for _ in re.finditer(r'class="courseShow', dom)])
        n_trigger = dom.count('class="trigger')
        n_name = dom.count('class="name"')
        main_reqs = [r for r in reqs if "chooseCourse" in r["url"] or "index.cfm" in r["url"]]
        ajax_reqs = [r for r in reqs if r.get("status") and "index.cfm" in r["url"] and r["method"] == "POST"]
        print(f"  DOM={len(dom)} courseShow={n_show} trigger={n_trigger} .name={n_name} 请求={len(reqs)} 主={len(main_reqs)} POST={len(ajax_reqs)}")
        for r in main_reqs[:6]:
            print(f"    {r['method']} {r['url'][:110]} -> {r.get('status','?')} ({r.get('mime','?')[:25]}) body={len(r.get('body',''))}B")
        for r in ajax_reqs[:6]:
            print(f"    [POST] {r['url'][:110]} -> {r.get('status','?')} post={r.get('post_data','')[:60]} body={len(r.get('body',''))}B")
    print(f"\n[cdp] 输出目录: {OUT}")


if __name__ == "__main__":
    main()
