import asyncio
from uuid import uuid4
from passlib.context import CryptContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

import bcrypt

async def main():
    password = b"support123"
    hashed_password = bcrypt.hashpw(password, bcrypt.gensalt()).decode("utf-8")
    
    engine = create_async_engine("postgresql+asyncpg://postgres:postgres@localhost:5432/postgres")
    async_session = sessionmaker(engine, class_=AsyncSession)
    
    async with async_session() as session:
        # Verify the user
        await session.execute(
            text("UPDATE users SET verification_status = 'approved' WHERE phone = '+79990000000'")
        )
        
        # Check if already exists
        result = await session.execute(
            text("SELECT id FROM admin_accounts WHERE login = '+79990000000'")
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            await session.execute(
                text("UPDATE admin_accounts SET password_hash = :hash, role = 'operator' WHERE login = :login"),
                {"hash": hashed_password, "login": "+79990000000"}
            )
        else:
            await session.execute(
                text("INSERT INTO admin_accounts (id, name, login, role, password_hash) "
                "VALUES (:id, 'Support Operator', :login, 'operator', :hash)"),
                {"id": str(uuid4()), "login": "+79990000000", "hash": hashed_password}
            )
            
        await session.commit()
    
    await engine.dispose()
    print("DONE. Admin login: +79990000000 / Password: support123")

if __name__ == "__main__":
    asyncio.run(main())
