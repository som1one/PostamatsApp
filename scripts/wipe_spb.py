"""Полностью вычищает все постаматы СПб перед apply_catalog_bundle.

Нужно чтобы bundle мог пересобрать СПб с нуля: apply_bundle делает только
upsert и не удаляет старые ячейки/юниты. Каскад идёт через тот же helper,
что использует ``migrate_lockers_to_real`` при удалении постаматов —
иначе при наличии payments/return_requests/rentals/reservations
получаем FK violation (например, payments_reservation_id_fkey).
"""

import asyncio

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.models.city import City
from backend.models.locker_location import LockerLocation
from scripts.migrate_lockers_to_real import _purge_locker_contents


async def _run():
    async with SessionLocal() as session:
        city = await session.scalar(select(City).where(City.slug == "spb"))
        if not city:
            print("SPB city not found — nothing to wipe")
            return

        lockers = (
            await session.scalars(
                select(LockerLocation).where(LockerLocation.city_id == city.id)
            )
        ).all()

        for locker in lockers:
            await _purge_locker_contents(session, locker)
            await session.delete(locker)

        await session.commit()
        print(f"Wiped {len(lockers)} SPB lockers")


def main():
    asyncio.run(_run())


if __name__ == "__main__":
    main()
