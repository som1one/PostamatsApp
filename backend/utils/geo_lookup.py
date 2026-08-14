"""Страна посетителя по IP — для плашки «похоже, включён VPN».

Сервис работает в России и СНГ: с зарубежного IP отваливаются оплата и
карта, поэтому посетителю с иностранным адресом сайт предлагает выключить
VPN. Единственный надёжный признак — IP, а не таймзона браузера: у клиента
с включённым VPN таймзона как раз остаётся московской.

Своей базы IP→страна у нас нет (MaxMind ради одной плашки — лишний
мегабайт в образе и лицензия), поэтому спрашиваем внешний бесплатный
сервис. Отсюда три страховки:

* кэш (Redis, а без него — словарь в процессе): один посетитель стоит
  максимум одного запроса наружу за ``GEO_CACHE_TTL_SECONDS``;
* глобальный потолок запросов в минуту — бесплатные тарифы лимитированы
  по частоте, и публичная ручка не должна превращаться в способ их
  исчерпать;
* fail-open: любая ошибка, таймаут или приватный адрес означают
  «страна неизвестна», а неизвестная страна плашку не показывает. Ложная
  плашка у обычного клиента хуже, чем её отсутствие у клиента с VPN.
"""

from __future__ import annotations

import ipaddress
import logging
import time
from collections import deque
from typing import Any

import httpx
from fastapi import Request

from backend.core.redis import get_redis_client
from backend.core.settings import settings

logger = logging.getLogger(__name__)

# Что кладём в кэш, когда страну определить не удалось: пустую строку
# Redis отдал бы неотличимо от промаха.
UNKNOWN_MARKER = "??"

_REDIS_KEY_PREFIX = "geo:country:"

# Локальный кэш для dev и на случай, когда Redis не поднялся:
# ip -> (страна или None, момент истечения по time.monotonic()).
_local_cache: dict[str, tuple[str | None, float]] = {}
_MAX_LOCAL_CACHE_ENTRIES = 2048

# ip-api на бесплатном тарифе разрешает 45 запросов в минуту с одного
# адреса сервера; держимся ниже.
_LOOKUP_RATE_LIMIT = 40
_LOOKUP_RATE_WINDOW = 60.0
_recent_lookups: deque[float] = deque()


def _parse_ip(raw: str) -> str | None:
    """Нормализует один элемент X-Forwarded-For в IP или None."""

    candidate = raw.strip()
    if not candidate:
        return None

    # "[2001:db8::1]:443" — форма с портом для IPv6.
    if candidate.startswith("["):
        candidate = candidate[1:].split("]", 1)[0]
    elif candidate.count(":") == 1:
        # "203.0.113.10:51234" — IPv4 с портом. У голого IPv6 двоеточий
        # всегда больше одного, так что перепутать нельзя.
        candidate = candidate.split(":", 1)[0]

    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def client_ip(request: Request) -> str | None:
    """IP посетителя с учётом того, что бэкенд стоит за Caddy.

    Берём ПОСЛЕДНИЙ элемент X-Forwarded-For, а не первый: Caddy дописывает
    в конец адрес, с которого запрос реально пришёл, а всё левее клиент мог
    прислать сам. Первый элемент позволил бы кому угодно подставить чужой IP
    и гонять нас во внешний сервис по произвольным адресам.

    Если между Caddy и клиентом однажды появится CDN, здесь окажется адрес
    CDN — тогда сюда придётся добавить разбор её заголовка.
    """

    forwarded = request.headers.get("x-forwarded-for", "")
    for candidate in reversed(forwarded.split(",")):
        ip = _parse_ip(candidate)
        if ip is not None:
            return ip

    if request.client and request.client.host:
        return _parse_ip(request.client.host)
    return None


def is_lookupable_ip(ip: str) -> bool:
    """False для адресов, о которых внешнему сервису нечего рассказать.

    Локалка и приватные сети — это dev-запуск и обращения внутри docker-сети;
    спрашивать про них страну бессмысленно.
    """

    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False

    return not (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_reserved
        or parsed.is_multicast
        or parsed.is_unspecified
    )


def extract_country_code(payload: Any) -> str | None:
    """Двухбуквенный код страны из ответа любого из провайдеров.

    api.country.is отдаёт ``{"country": "US"}``, ip-api —
    ``{"status": "success", "countryCode": "US"}``, ipwho.is —
    ``{"success": true, "country_code": "US"}``. Разбираем все три формы, а
    заодно проверяем поля статуса: провайдер может ответить 200 с отказом.
    """

    if not isinstance(payload, dict):
        return None
    if payload.get("status") == "fail" or payload.get("success") is False:
        return None

    for key in ("country_code", "countryCode", "country"):
        raw = payload.get(key)
        if isinstance(raw, str):
            code = raw.strip().upper()
            if len(code) == 2 and code.isalpha():
                return code
    return None


def is_cis_country(country: str | None) -> bool:
    """Страна из «своего» региона (СНГ + соседи), где плашка не нужна."""

    if not country:
        return False
    return country.upper() in settings.GEO_CIS_COUNTRIES


async def _cache_get(ip: str) -> tuple[bool, str | None]:
    """(есть ли ответ в кэше, страна). Страна None = «известно, что неизвестно»."""

    redis = get_redis_client()
    if redis is not None:
        try:
            cached = await redis.get(f"{_REDIS_KEY_PREFIX}{ip}")
        except Exception:
            logger.warning("Geo cache read failed, falling back to lookup", exc_info=True)
        else:
            if cached:
                return True, (None if cached == UNKNOWN_MARKER else cached)
            return False, None

    entry = _local_cache.get(ip)
    if entry is None:
        return False, None
    country, expires_at = entry
    if expires_at <= time.monotonic():
        _local_cache.pop(ip, None)
        return False, None
    return True, country


async def _cache_set(ip: str, country: str | None) -> None:
    ttl = (
        settings.GEO_CACHE_TTL_SECONDS
        if country
        else settings.GEO_CACHE_UNKNOWN_TTL_SECONDS
    )

    redis = get_redis_client()
    if redis is not None:
        try:
            await redis.set(f"{_REDIS_KEY_PREFIX}{ip}", country or UNKNOWN_MARKER, ex=ttl)
            return
        except Exception:
            logger.warning("Geo cache write failed", exc_info=True)

    if len(_local_cache) >= _MAX_LOCAL_CACHE_ENTRIES:
        now = time.monotonic()
        stale = [key for key, (_, expires_at) in _local_cache.items() if expires_at <= now]
        for key in stale:
            del _local_cache[key]
        if len(_local_cache) >= _MAX_LOCAL_CACHE_ENTRIES:
            _local_cache.clear()
    _local_cache[ip] = (country, time.monotonic() + ttl)


def _rate_limit_allows() -> bool:
    now = time.monotonic()
    while _recent_lookups and now - _recent_lookups[0] > _LOOKUP_RATE_WINDOW:
        _recent_lookups.popleft()
    if len(_recent_lookups) >= _LOOKUP_RATE_LIMIT:
        return False
    _recent_lookups.append(now)
    return True


def _http_client() -> httpx.AsyncClient:
    """Отдельной функцией, чтобы тесты подменяли транспорт."""

    return httpx.AsyncClient(timeout=settings.GEO_LOOKUP_TIMEOUT_SECONDS)


async def _fetch_country(ip: str) -> str | None:
    """Спрашивает провайдеров по очереди: побеждает первый внятный ответ."""

    async with _http_client() as client:
        for template in settings.GEO_LOOKUP_PROVIDERS:
            url = template.replace("{ip}", ip)
            try:
                response = await client.get(url, headers={"Accept": "application/json"})
                response.raise_for_status()
                country = extract_country_code(response.json())
            except Exception:
                logger.info("Geo provider failed: %s", template, exc_info=True)
                continue
            if country:
                return country
    return None


async def lookup_country(ip: str) -> str | None:
    """Код страны для IP или None, если определить не удалось."""

    if not settings.GEO_LOOKUP_ENABLED or not settings.GEO_LOOKUP_PROVIDERS:
        return None
    if not is_lookupable_ip(ip):
        return None

    cached, country = await _cache_get(ip)
    if cached:
        return country

    if not _rate_limit_allows():
        logger.warning("Geo lookup rate limit reached, skipping lookup for %s", ip)
        return None

    country = await _fetch_country(ip)
    await _cache_set(ip, country)
    return country
