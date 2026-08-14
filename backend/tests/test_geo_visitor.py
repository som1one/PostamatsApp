"""Тесты гео-проверки посетителя (`/api/geo/visitor`).

Проверяем то, ради чего ручка существует: иностранный IP получает
предложение выключить VPN, свой регион и неопределимый адрес — нет,
а внешний сервис не дёргается лишний раз.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx
from starlette.requests import Request

from backend.core.settings import settings
from backend.routers.geo import get_visitor_geo
from backend.utils import geo_lookup


def _request(ip: str = "127.0.0.1", forwarded: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/geo/visitor",
            "headers": headers,
            "client": (ip, 51234),
        }
    )


class ClientIpTests(unittest.TestCase):
    def test_takes_last_forwarded_entry(self) -> None:
        # Первый элемент клиент может прислать сам; настоящий адрес Caddy
        # дописывает в конец.
        request = _request(forwarded="1.2.3.4, 203.0.113.10")
        self.assertEqual(geo_lookup.client_ip(request), "203.0.113.10")

    def test_falls_back_to_peer_without_header(self) -> None:
        self.assertEqual(geo_lookup.client_ip(_request(ip="198.51.100.7")), "198.51.100.7")

    def test_strips_port_and_brackets(self) -> None:
        self.assertEqual(
            geo_lookup.client_ip(_request(forwarded="203.0.113.10:51234")),
            "203.0.113.10",
        )
        self.assertEqual(
            geo_lookup.client_ip(_request(forwarded="[2001:db8::1]:443")),
            "2001:db8::1",
        )

    def test_ignores_garbage_entries(self) -> None:
        request = _request(forwarded="203.0.113.10, not-an-ip")
        self.assertEqual(geo_lookup.client_ip(request), "203.0.113.10")

    def test_private_addresses_are_not_looked_up(self) -> None:
        self.assertFalse(geo_lookup.is_lookupable_ip("127.0.0.1"))
        self.assertFalse(geo_lookup.is_lookupable_ip("192.168.1.6"))
        self.assertFalse(geo_lookup.is_lookupable_ip("172.18.0.4"))
        # 203.0.113.0/24 — документационная сеть, ipaddress тоже считает
        # её приватной, поэтому «настоящий» публичный адрес берём другой.
        self.assertFalse(geo_lookup.is_lookupable_ip("203.0.113.10"))
        self.assertTrue(geo_lookup.is_lookupable_ip("8.8.8.8"))


class CountryCodeParsingTests(unittest.TestCase):
    def test_reads_every_provider_shape(self) -> None:
        self.assertEqual(geo_lookup.extract_country_code({"country": "us"}), "US")
        self.assertEqual(
            geo_lookup.extract_country_code({"status": "success", "countryCode": "DE"}),
            "DE",
        )
        self.assertEqual(
            geo_lookup.extract_country_code({"success": True, "country_code": "RU"}),
            "RU",
        )

    def test_rejects_failures_and_junk(self) -> None:
        self.assertIsNone(geo_lookup.extract_country_code({"status": "fail"}))
        self.assertIsNone(geo_lookup.extract_country_code({"success": False, "country_code": "US"}))
        self.assertIsNone(geo_lookup.extract_country_code({"country": "United States"}))
        self.assertIsNone(geo_lookup.extract_country_code({}))
        self.assertIsNone(geo_lookup.extract_country_code("US"))


class VisitorGeoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # Кэш и лимитер живут в модуле — между тестами их надо обнулять.
        geo_lookup._local_cache.clear()
        geo_lookup._recent_lookups.clear()
        self.calls: list[str] = []

    def _client_factory(self, handler):
        def factory() -> httpx.AsyncClient:
            return httpx.AsyncClient(transport=httpx.MockTransport(handler))

        return factory

    def _answer(self, country: str | None, *, status: int = 200):
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(str(request.url))
            if country is None:
                return httpx.Response(status, json={"status": "fail"})
            return httpx.Response(status, json={"country": country})

        return self._client_factory(handler)

    async def _visit(self, forwarded: str, factory) -> dict:
        with patch.object(geo_lookup, "_http_client", factory):
            payload = await get_visitor_geo(_request(forwarded=forwarded))
        return payload["data"]

    async def test_foreign_ip_gets_vpn_hint(self) -> None:
        data = await self._visit("8.8.8.8", self._answer("US"))
        self.assertEqual(data["country"], "US")
        self.assertFalse(data["isCis"])
        self.assertTrue(data["shouldSuggestVpnOff"])

    async def test_cis_ip_stays_silent(self) -> None:
        data = await self._visit("8.8.8.8", self._answer("KZ"))
        self.assertEqual(data["country"], "KZ")
        self.assertTrue(data["isCis"])
        self.assertFalse(data["shouldSuggestVpnOff"])

    async def test_provider_failure_is_silent(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(str(request.url))
            raise httpx.ConnectError("boom")

        data = await self._visit("8.8.8.8", self._client_factory(handler))
        self.assertIsNone(data["country"])
        self.assertFalse(data["shouldSuggestVpnOff"])
        # Оба провайдера из списка были опрошены, прежде чем сдаться.
        self.assertEqual(len(self.calls), len(settings.GEO_LOOKUP_PROVIDERS))

    async def test_falls_back_to_second_provider(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(str(request.url))
            if len(self.calls) == 1:
                return httpx.Response(429, json={})
            return httpx.Response(200, json={"countryCode": "FR"})

        data = await self._visit("8.8.8.8", self._client_factory(handler))
        self.assertEqual(data["country"], "FR")
        self.assertTrue(data["shouldSuggestVpnOff"])

    async def test_local_request_never_leaves_the_process(self) -> None:
        data = await self._visit("192.168.1.6", self._answer("US"))
        self.assertIsNone(data["country"])
        self.assertFalse(data["shouldSuggestVpnOff"])
        self.assertEqual(self.calls, [])

    async def test_repeat_visit_is_served_from_cache(self) -> None:
        factory = self._answer("US")
        await self._visit("8.8.8.8", factory)
        data = await self._visit("8.8.8.8", factory)
        self.assertTrue(data["shouldSuggestVpnOff"])
        self.assertEqual(len(self.calls), 1)

    async def test_unknown_country_is_cached_too(self) -> None:
        factory = self._answer(None)
        await self._visit("8.8.8.8", factory)
        calls_after_first = len(self.calls)
        await self._visit("8.8.8.8", factory)
        self.assertEqual(len(self.calls), calls_after_first)

    async def test_rate_limit_stops_outgoing_lookups(self) -> None:
        factory = self._answer("US")
        for index in range(geo_lookup._LOOKUP_RATE_LIMIT):
            await self._visit(f"8.8.{index}.1", factory)
        calls_before = len(self.calls)

        data = await self._visit("9.9.9.9", factory)
        self.assertIsNone(data["country"])
        self.assertFalse(data["shouldSuggestVpnOff"])
        self.assertEqual(len(self.calls), calls_before)

    async def test_disabled_lookup_returns_nothing(self) -> None:
        factory = self._answer("US")
        with patch.object(settings, "GEO_LOOKUP_ENABLED", False):
            data = await self._visit("8.8.8.8", factory)
        self.assertIsNone(data["country"])
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
