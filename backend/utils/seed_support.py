import bcrypt
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.models.admin_account import AdminAccount
from backend.models.user import User
from backend.models.enums import AdminRole, VerificationStatus
from backend.utils.admin_auth_utils import hash_password

async def ensure_support_operator(db: AsyncSession) -> None:
    # 1. Verify user +79990000000
    user_result = await db.execute(select(User).where(User.phone == "+79990000000"))
    user = user_result.scalar_one_or_none()
    if user:
        user.verification_status = VerificationStatus.APPROVED
    
    # 2. Ensure admin account
    admin_result = await db.execute(select(AdminAccount).where(AdminAccount.login == "+79990000000"))
    admin = admin_result.scalar_one_or_none()
    
    if not admin:
        admin = AdminAccount(
            name="Support Operator",
            login="+79990000000",
            role=AdminRole.OPERATOR,
        )
        db.add(admin)
        
    admin.password_hash = hash_password("support123")
    
    await db.commit()
