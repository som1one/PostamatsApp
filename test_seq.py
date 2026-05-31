import asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    # Use the async_db_url format
    engine = create_async_engine("postgresql+asyncpg://postgres:postgres@localhost:5432/postgres")
    try:
        async with engine.begin() as conn:
            await conn.execute("CREATE SEQUENCE IF NOT EXISTS support_message_seq")
            result = await conn.execute(select(func.nextval("support_message_seq")))
            print("Nextval result:", result.scalar_one())
    except Exception as e:
        print("Error:", e)
    finally:
        await engine.dispose()

asyncio.run(main())
