"""Deep-links в админ-панель.

Формат ссылки — контракт между бэкендом и статической админкой: query-параметры
разбирает ``applyDeepLinkFromQuery`` в ``admin/app.js``. Собираем их в одном
месте, чтобы уведомления, карточка клиента в поддержке и всё остальное вели в
одну и ту же карточку, а не каждый в свой список.

Все функции возвращают ``None``, если ``ADMIN_PANEL_URL`` не задан: тогда
вызывающий код просто не показывает кнопку/ссылку.
"""

from __future__ import annotations

from uuid import UUID

from backend.core.settings import settings

__all__ = ["build_admin_rentals_url"]


def build_admin_rentals_url(rental_id: UUID | str | None = None) -> str | None:
    """Ссылка в раздел «Аренды»; с ``rental_id`` — сразу в карточку аренды."""

    base = settings.ADMIN_PANEL_URL
    if not base:
        return None
    link = f"{base.rstrip('/')}/?section=rentals"
    if rental_id is not None:
        link += f"&rental={rental_id}"
    return link
