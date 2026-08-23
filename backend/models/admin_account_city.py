"""Связь «франшиза — города»: у одного аккаунта может быть несколько городов.

Отдельная таблица вместо ``admin_accounts.city_id``: партнёр часто держит
и соседний город, а плодить ему по аккаунту на каждый — значит заставить
перелогиниваться, чтобы посмотреть свои же постаматы.

У ``super_admin`` и ``operator`` строк здесь нет: они видят всю сеть, и
пустой список для них означает «без ограничений» (см.
:func:`backend.utils.admin_scope.franchise_city_ids`).
"""

from sqlalchemy import Column, ForeignKey, Table, Uuid

from backend.core.database import Base


admin_account_cities = Table(
    "admin_account_cities",
    Base.metadata,
    Column(
        "admin_account_id",
        Uuid,
        ForeignKey("admin_accounts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "city_id",
        Uuid,
        ForeignKey("cities.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
)
