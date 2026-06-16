import asyncio
from backend.core.database import SessionLocal
from backend.models.locker_location import LockerLocation
from backend.models.locker_cell import LockerCell
from backend.models.inventory_unit import InventoryUnit
from backend.models.city import City
from sqlalchemy import select, delete

async def _run():
    async with SessionLocal() as session:
        # Find SPB
        city = await session.scalar(select(City).where(City.slug == "spb"))
        if not city:
            return

        lockers = (await session.scalars(select(LockerLocation).where(LockerLocation.city_id == city.id))).all()
        locker_ids = [l.id for l in lockers]
        
        if locker_ids:
            # Delete reservations
            from backend.models.reservation import Reservation
            await session.execute(
                delete(Reservation).where(
                    Reservation.locker_id.in_(locker_ids)
                )
            )
            # Delete movements
            from backend.models.inventory_movement import InventoryMovement
            await session.execute(
                delete(InventoryMovement).where(
                    InventoryMovement.inventory_unit_id.in_(
                        select(InventoryUnit.id).where(
                            InventoryUnit.locker_cell_id.in_(
                                select(LockerCell.id).where(LockerCell.locker_id.in_(locker_ids))
                            )
                        )
                    )
                )
            )
            # Delete units
            await session.execute(
                delete(InventoryUnit).where(
                    InventoryUnit.locker_cell_id.in_(
                        select(LockerCell.id).where(LockerCell.locker_id.in_(locker_ids))
                    )
                )
            )
            # Delete cells
            await session.execute(delete(LockerCell).where(LockerCell.locker_id.in_(locker_ids)))
            # Delete lockers
            await session.execute(delete(LockerLocation).where(LockerLocation.id.in_(locker_ids)))
            
        await session.commit()
        print("Wiped SPB lockers")

def main():
    asyncio.run(_run())

if __name__ == "__main__":
    main()
