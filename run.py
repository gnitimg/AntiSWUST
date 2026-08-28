#!/usr/bin/env python3
"""AntiSWUST 一键启动：python run.py

同时启动后端 (uvicorn) 与前端 (vite)，自动检查并安装缺失依赖，
彩色日志区分 [api]/[web]，Ctrl+C 统一停止全部服务。
"""
from __future__ import annotations

import os
import sys
import time
import signal
import subprocess
import threading
import atexit
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
FRONTEND_PORT = 5173


def _enable_vt() -> None:
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
        except Exception:
            pass


_enable_vt()
C_API = "\033[36m"
C_WEB = "\033[32m"
C_SYS = "\033[33m"
C_ERR = "\033[31m"
C_RST = "\033[0m"

_lock = threading.Lock()
_procs: list[subprocess.Popen] = []


def _log(tag: str, color: str, msg: str) -> None:
    with _lock:
        for line in str(msg).splitlines():
            print(f"{color}[{tag}]{C_RST} {line}", flush=True)


def _stream(proc: subprocess.Popen, tag: str, color: str) -> None:
    assert proc.stdout is not None
    for line in iter(proc.stdout.readline, ""):
        _log(tag, color, line.rstrip("\n"))


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


def _cleanup() -> None:
    for p in _procs:
        if p.poll() is None:
            _kill_tree(p)


atexit.register(_cleanup)


def _check_python() -> bool:
    if sys.version_info < (3, 10):
        _log("sys", C_ERR, f"需要 Python >= 3.10，当前 {sys.version.split()[0]}")
        return False
    return True


def _check_node() -> str | None:
    npm = shutil.which("npm")
    if not npm:
        _log("sys", C_ERR, "未找到 npm，请先安装 Node.js >= 18: https://nodejs.org")
        return None
    return npm


def _ensure_backend_deps() -> bool:
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        import httpx  # noqa: F401
        import parsel  # noqa: F401
        return True
    except ImportError:
        pass
    _log("sys", C_SYS, "后端依赖缺失，正在安装 backend/requirements.txt ...")
    req = BACKEND_DIR / "requirements.txt"
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req)]
    ).returncode == 0


def _ensure_frontend_deps(npm: str) -> bool:
    if (FRONTEND_DIR / "node_modules").exists():
        return True
    _log("sys", C_SYS, "前端依赖缺失，正在执行 npm install ...")
    return subprocess.run([npm, "install"], cwd=str(FRONTEND_DIR)).returncode == 0


def _spawn(cmd: list[str], cwd: Path, tag: str, color: str) -> subprocess.Popen:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )
    _procs.append(proc)
    threading.Thread(target=_stream, args=(proc, tag, color), daemon=True).start()
    return proc


def main() -> None:
    if not BACKEND_DIR.exists() or not FRONTEND_DIR.exists():
        _log("sys", C_ERR, f"未找到 backend/ 或 frontend/ 目录，请在项目根目录运行")
        sys.exit(1)

    _log("sys", C_SYS, "AntiSWUST 教务辅助系统一键启动")
    _log("sys", C_SYS, f"后端 http://{BACKEND_HOST}:{BACKEND_PORT}  |  前端 http://localhost:{FRONTEND_PORT}")

    if not _check_python():
        sys.exit(1)
    npm = _check_node()
    if not npm:
        sys.exit(1)
    if not _ensure_backend_deps():
        _log("sys", C_ERR, "后端依赖安装失败，请手动: pip install -r backend/requirements.txt")
        sys.exit(1)
    if not _ensure_frontend_deps(npm):
        _log("sys", C_ERR, "前端依赖准备失败")
        sys.exit(1)

    api_cmd = [sys.executable, "-m", "uvicorn", "app.main:app",
               "--host", BACKEND_HOST, "--port", str(BACKEND_PORT), "--reload"]
    if os.environ.get("RUN_NO_RELOAD", "").lower() in ("1", "true", "yes"):
        api_cmd = [sys.executable, "-m", "uvicorn", "app.main:app",
                   "--host", BACKEND_HOST, "--port", str(BACKEND_PORT)]
    api_proc = _spawn(api_cmd, BACKEND_DIR, "api", C_API)
    web_proc = _spawn([npm, "run", "dev"], FRONTEND_DIR, "web", C_WEB)

    _log("sys", C_SYS, "服务已启动，按 Ctrl+C 停止全部")

    try:
        while True:
            for p in _procs:
                code = p.poll()
                if code is not None:
                    tag = "api" if p is api_proc else "web"
                    _log("sys", C_ERR, f"[{tag}] 进程退出 (code={code})，停止全部服务")
                    _cleanup()
                    sys.exit(code)
            time.sleep(0.5)
    except KeyboardInterrupt:
        _log("sys", C_SYS, "收到中断，正在停止全部服务")
        _cleanup()
        sys.exit(0)


if __name__ == "__main__":
    main()
