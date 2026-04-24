import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.core.settings import settings
from backend.models.admin_account import AdminAccount
from backend.models.enums import AdminRole
from backend.utils.admin_auth_utils import hash_password


def main() -> None:
    if not settings.DB_URL:
        raise RuntimeError("DB_URL is not configured")

    engine = create_engine(settings.DB_URL)
    login = "admin"
    password = "admin"
    name = "Test Admin"

    with Session(engine) as session:
        existing_admin = session.execute(
            select(AdminAccount).where(AdminAccount.login == login)
        ).scalar_one_or_none()

        if existing_admin is None:
            existing_admin = AdminAccount(
                name=name,
                login=login,
                role=AdminRole.SUPER_ADMIN,
                password_hash=hash_password(password),
            )
            session.add(existing_admin)
            action = "created"
        else:
            existing_admin.name = name
            existing_admin.role = AdminRole.SUPER_ADMIN
            existing_admin.password_hash = hash_password(password)
            action = "updated"

        session.commit()
        print(
            f"Admin {action}: login={existing_admin.login} password={password} role={existing_admin.role.value}"
        )


if __name__ == "__main__":
    main()
