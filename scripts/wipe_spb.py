"""Удаляет постаматы СПб вместе с ячейками и юнитами — только вручную.

Раньше запускался на каждом деплое перед apply_catalog_bundle и удалял
заодно брони, аренды и платежи; 2026-10-23 так пропала оплаченная бронь.
Из deploy/deploy.sh убран. Чистка идёт через тот же helper, что у
``migrate_lockers_to_real``, а он отказывается трогать постамат, к которому
привязана хоть одна бронь или аренда, — тогда скрипт ничего не меняет и
выходит с кодом 1.
"""

import asyncio

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.models.city import City
from backend.models.locker_location import LockerLocation
from scripts.migrate_lockers_to_real import (
    LockerHasOperationsError,
    _purge_locker_contents,
)


async def _run() -> int:
    async with SessionLocal() as session:
        city = await session.scalar(select(City).where(City.slug == "spb"))
        if not city:
            print("SPB city not found — nothing to wipe")
            return 0

        lockers = (
            await session.scalars(
                select(LockerLocation).where(LockerLocation.city_id == city.id)
            )
        ).all()

        for locker in lockers:
            try:
                await _purge_locker_contents(session, locker)
            except LockerHasOperationsError as exc:
                await session.rollback()
                print(f"Refuse to wipe SPB: {exc}")
                return 1
            await session.delete(locker)

        await session.commit()
        print(f"Wiped {len(lockers)} SPB lockers")
        return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
