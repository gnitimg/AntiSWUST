from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any

from app.config import settings


class CookieStore:
    """本地 cookie 持久化存储，带 TTL 过期。

    每个 session 对应一个 JSON 文件，结构：
    {
        "session_id": "...",
        "created_at": 1700000000,
        "last_access": 1700000123,
        "user": {"name": "...", "student_id": "..."},
        "cookies": {"domain": {"name": {"value": "...", "domain": "...", "path": "/"}}}
    }
    """

    def __init__(self, store_dir: Path | None = None, ttl: int | None = None) -> None:
        self.store_dir = store_dir or settings.cookie_store_dir
        self.ttl = ttl or settings.cookie_ttl_seconds
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, Lock] = {}
        self._locks_guard = Lock()

    def _lock_for(self, session_id: str) -> Lock:
        with self._locks_guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = Lock()
                self._locks[session_id] = lock
            return lock

    def _path(self, session_id: str) -> Path:
        return self.store_dir / f"{session_id}.json"

    def create_session(self) -> str:
        return uuid.uuid4().hex

    def save(self, session_id: str, cookies: dict[str, Any], user: dict[str, Any] | None = None) -> None:
        with self._lock_for(session_id):
            now = int(time.time())
            record = {
                "session_id": session_id,
                "created_at": now,
                "last_access": now,
                "user": user or {},
                "cookies": cookies,
            }
            self._path(session_id).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    def update_cookies(self, session_id: str, cookies: dict[str, Any]) -> bool:
        record = self.load(session_id)
        if record is None:
            return False
        record["cookies"].update(cookies)
        with self._lock_for(session_id):
            record["last_access"] = int(time.time())
            self._path(session_id).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return True

    def load(self, session_id: str) -> dict[str, Any] | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        now = int(time.time())
        # ttl <= 0 表示暂不限制登录态时长（见 config.cookie_ttl_seconds 注释）
        if self.ttl > 0 and now - record.get("last_access", 0) > self.ttl:
            self.delete(session_id)
            return None
        record["last_access"] = now
        with self._lock_for(session_id):
            try:
                path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
        return record

    def get_cookies(self, session_id: str) -> dict[str, Any] | None:
        record = self.load(session_id)
        return record["cookies"] if record else None

    def get_user(self, session_id: str) -> dict[str, Any] | None:
        record = self.load(session_id)
        return record["user"] if record else None

    def is_valid(self, session_id: str) -> bool:
        return self.load(session_id) is not None

    def delete(self, session_id: str) -> None:
        path = self._path(session_id)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def cleanup_expired(self) -> int:
        if self.ttl <= 0:
            return 0
        now = int(time.time())
        removed = 0
        for path in self.store_dir.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if now - record.get("last_access", 0) > self.ttl:
                    path.unlink(missing_ok=True)
                    removed += 1
            except (json.JSONDecodeError, OSError):
                try:
                    path.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    pass
        return removed


cookie_store = CookieStore()
