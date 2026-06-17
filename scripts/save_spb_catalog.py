import asyncio
from backend.core.database import SessionLocal
from backend.models.product import Product
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.city import City
from sqlalchemy import select

async def _run():
    async with SessionLocal() as session:
        # Get all products in SPB
        stmt = select(Product.slug, LockerLocation.external_locker_id, InventoryUnit.status)\
            .select_from(Product)\
            .join(InventoryUnit, InventoryUnit.product_id == Product.id)\
            .join(LockerCell, InventoryUnit.locker_cell_id == LockerCell.id)\
            .join(LockerLocation, LockerCell.locker_id == LockerLocation.id)\
            .join(City, LockerLocation.city_id == City.id)\
            .where(City.slug == "spb")
        
        result = await session.execute(stmt)
        rows = result.all()
        
        output = ["# SPB Catalog Dump", ""]
        output.append(f"Total units: {len(rows)}")
        output.append("")
        
        slugs = set()
        for r in rows:
            output.append(f"- {r.slug} ({r.external_locker_id}) [{r.status}]")
            slugs.add(r.slug)
            
        output.append("")
        result_text = "\n".join(output)
        print("============== CATALOG DUMP ==============")
        print(result_text)
        print("==========================================")

def main():
    asyncio.run(_run())

if __name__ == "__main__":
    main()
