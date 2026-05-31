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
    # Safely delete any conflicting accounts to prevent UniqueViolation
    from sqlalchemy import delete
    await db.execute(
        delete(AdminAccount).where(AdminAccount.login.in_(["+79990000000", "operator"]))
    )
    
    admin = AdminAccount(
        name="Support Operator",
        login="operator",
        role=AdminRole.OPERATOR,
        password_hash=hash_password("support123")
    )
    db.add(admin)
    
    await db.commit()
