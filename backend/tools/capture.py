"""mitmproxy 抓包脚本：记录 SWUST 教务系统全部请求，供接口分析。

使用方法（在虚拟机内，已连 atrust）：
  1. pip install mitmproxy
  2. mitmdump -s backend/tools/capture.py
  3. 浏览器/系统设置代理 → 127.0.0.1:8080
  4. 访问 http://mitm.it 安装 CA 证书（首次需要，用于解密 HTTPS）
  5. 打开教务系统 https://matrix.dean.swust.edu.cn 正常操作选课
  6. 所有请求自动记录到 captures/ 目录
  7. 操作完成后把 captures/ 目录打包发给开发者分析

输出：
  captures/
    0001_登录_143025.json   每个请求一个文件，含完整 req/resp
    0002_选课_143030.json
    ...
    summary.log             一行一条摘要，便于总览
"""
import json
import time
from pathlib import Path

from mitmproxy import http

TARGETS = (
    "matrix.dean.swust.edu.cn",
    "cas.swust.edu.cn",
    "myo.swust.edu.cn",
    "soa.swust.edu.cn",
    "202.115.175.177",
)

OUT = Path(__file__).resolve().parent.parent.parent / "captures"
OUT.mkdir(exist_ok=True)

MAX_REQ_BODY = 4000
MAX_RESP_BODY = 10000


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


class Capture:
    def __init__(self) -> None:
        self.count = 0

    def response(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host or ""
        if not any(t in host for t in TARGETS):
            return
        self.count += 1
        url = flow.request.pretty_url
        tag = _tag(url)

        req_body = ""
        if flow.request.content:
            req_body = flow.request.get_text(strict=False) or ""
        resp_body = ""
        if flow.response.content:
            resp_body = flow.response.get_text(strict=False) or ""

        record = {
            "seq": self.count,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tag": tag,
            "method": flow.request.method,
            "url": url,
            "req_headers": dict(flow.request.headers),
            "req_body": req_body[:MAX_REQ_BODY],
            "status": flow.response.status_code,
            "resp_headers": dict(flow.response.headers),
            "resp_body": resp_body[:MAX_RESP_BODY],
            "resp_body_truncated": len(resp_body) > MAX_RESP_BODY,
        }

        safe_tag = tag.replace("/", "_")
        fname = f"{self.count:04d}_{safe_tag}_{time.strftime('%H%M%S')}.json"
        (OUT / fname).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        with open(OUT / "summary.log", "a", encoding="utf-8") as f:
            f.write(
                f"[{record['time']}] #{self.count} [{tag}] "
                f"{flow.request.method} {url} -> {record['status']} "
                f"req={len(req_body)}B resp={len(resp_body)}B\n"
            )

        print(f"#{self.count} [{tag}] {flow.request.method} {url} -> {record['status']}", flush=True)


addons = [Capture()]
