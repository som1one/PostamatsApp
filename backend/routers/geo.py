"""Публичная ручка «откуда пришёл посетитель» для плашки про VPN.

Отдаёт только код страны и вывод «стоит ли предложить выключить VPN» —
IP наружу не возвращаем, он тут не нужен ни фронту, ни логам.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.utils.geo_lookup import client_ip, is_cis_country, lookup_country

router = APIRouter(prefix="/api/geo", tags=["public-geo"])


@router.get("/visitor")
async def get_visitor_geo(request: Request):
    ip = client_ip(request)
    country = await lookup_country(ip) if ip else None
    is_cis = is_cis_country(country)

    return {
        "data": {
            "country": country,
            "isCis": is_cis,
            # Неизвестная страна = молчим: плашка у клиента без VPN хуже,
            # чем её отсутствие у клиента с VPN.
            "shouldSuggestVpnOff": bool(country) and not is_cis,
        }
    }
