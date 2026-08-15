"""Простой лимитер для публичных форм, которые дёргают мессенджеры.

Любая ручка без авторизации, которая шлёт админам сообщение (заявка на
франшизу, обратная связь), — удобная мишень для спама. Здесь общий на всех
такой ограничитель: не больше ``per_ip`` заявок с одного IP за
``per_ip_window`` и не больше ``global_limit`` заявок суммарно за
``global_window``.

Счётчики живут в памяти процесса (у каждого воркера свои) и обнуляются при
рестарте — для защиты от «нажал десять раз» и мелкого флуда этого хватает,
а глобальный потолок ограничивает ущерб, даже если IP подделали.
"""

from __future__ import annotations

import time
from collections import deque

from fastapi import Request

# Чтобы словарь не рос бесконечно на длинной сессии процесса.
_MAX_TRACKED_IPS = 512


def client_ip(request: Request) -> str:
    """IP клиента с учётом того, что бэкенд стоит за Caddy.

    Заголовок подделывается кем угодно, поэтому на него завязан только
    per-IP лимит; настоящая страховка — глобальный потолок.
    """

    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Скользящее окно на IP плюс общий потолок на всю ручку."""

    def __init__(
        self,
        *,
        per_ip: int,
        per_ip_window: float,
        global_limit: int,
        global_window: float,
    ) -> None:
        self.per_ip = per_ip
        self.per_ip_window = per_ip_window
        self.global_limit = global_limit
        self.global_window = global_window
        self._by_ip: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()

    def reset(self) -> None:
        """Обнуляет счётчики (нужно тестам между кейсами)."""

        self._by_ip.clear()
        self._global.clear()

    @staticmethod
    def _prune(bucket: deque[float], window: float, now: float) -> None:
        while bucket and now - bucket[0] > window:
            bucket.popleft()

    def allow(self, ip: str) -> bool:
        """True, если заявку можно принять. Побочно фиксирует попытку."""

        now = time.monotonic()

        self._prune(self._global, self.global_window, now)
        if len(self._global) >= self.global_limit:
            return False

        bucket = self._by_ip.get(ip)
        if bucket is None:
            if len(self._by_ip) >= _MAX_TRACKED_IPS:
                # Выкидываем тех, у кого окно уже истекло; если таких нет —
                # чистим словарь целиком, глобальный лимит всё равно на месте.
                stale = [
                    key
                    for key, values in self._by_ip.items()
                    if not values or now - values[-1] > self.per_ip_window
                ]
                for key in stale:
                    del self._by_ip[key]
                if len(self._by_ip) >= _MAX_TRACKED_IPS:
                    self._by_ip.clear()
            bucket = deque()
            self._by_ip[ip] = bucket

        self._prune(bucket, self.per_ip_window, now)
        if len(bucket) >= self.per_ip:
            return False

        bucket.append(now)
        self._global.append(now)
        return True


__all__ = ["RateLimiter", "client_ip"]
