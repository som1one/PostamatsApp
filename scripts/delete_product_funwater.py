import asyncio
import os
import sys

# Ensure backend module can be imported if running from inside backend dir or outside
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.core.database import SessionLocal
from backend.models.product import Product
from sqlalchemy import select, update

async def main():
    async with SessionLocal() as db:
        res = await db.execute(select(Product).where(Product.name.like("%Funwater Koi 350%")))
        products = res.scalars().all()
        for p in products:
            print(f"Deactivating product: {p.id} - {p.name}")
            await db.execute(update(Product).where(Product.id == p.id).values(is_active=False))
        await db.commit()
        print("Done deactivating Funwater Koi 350")

if __name__ == "__main__":
    asyncio.run(main())
