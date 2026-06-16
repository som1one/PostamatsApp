import asyncio
from backend.core.database import SessionLocal
from backend.models.locker import LockerCell
from backend.models.inventory import InventoryUnit
from sqlalchemy import select, delete

async def _run():
    async with SessionLocal() as session:
        # Delete units first to avoid foreign key errors, though cascade should handle it
        await session.execute(
            delete(InventoryUnit).where(
                InventoryUnit.locker_cell_id.in_(
                    select(LockerCell.id).where(LockerCell.external_cell_id.like("seed-spb-nevsky-extra-%"))
                )
            )
        )
        
        await session.execute(
            delete(LockerCell).where(LockerCell.external_cell_id.like("seed-spb-nevsky-extra-%"))
        )
        await session.commit()

def main():
    asyncio.run(_run())

if __name__ == "__main__":
    main()
