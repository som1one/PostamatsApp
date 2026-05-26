"""Печать текущего состояния всех постаматов.

Используется для dry-run проверки перед миграцией: workflow
"Migrate lockers to real config" в режиме `dryRun=true` запускает этот
скрипт и показывает, что лежит в БД, без какого-либо изменения данных.
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import select

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.core.database import SessionLocal, engine  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402


async def _run() -> int:
    async with SessionLocal() as session:
        rows = (
            await session.scalars(
                select(LockerLocation).order_by(LockerLocation.created_at.asc())
            )
        ).all()
        print(f"Total lockers: {len(rows)}")
        for row in rows:
            print(
                f"  provider={row.external_provider!r} "
                f"external_id={row.external_locker_id!r} "
                f"name={row.name!r} "
                f"status={row.status.value} "
                f"partner={row.partner_name!r}"
            )
    await engine.dispose()
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
