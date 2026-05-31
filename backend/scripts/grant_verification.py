"""Выдать (или снять) верификацию пользователю по номеру телефона.

Зачем: верификация хранится в БД (поле ``users.verification_status``), и для
ручной выдачи статуса нужен прямой доступ к продакшен-базе. Этот скрипт делает
это безопасно: находит пользователя по телефону и переводит его в нужный
статус (``approved`` по умолчанию).

Запуск на сервере (из каталога с проектом, в окружении backend):

    python -m backend.scripts.grant_verification +79990000000

В Docker-развёртывании — внутри контейнера backend, например:

    docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml \
        exec backend python -m backend.scripts.grant_verification +79990000000

Опционально можно указать статус вторым аргументом:

    python -m backend.scripts.grant_verification +79990000000 approved
    python -m backend.scripts.grant_verification +79990000000 draft

Если пользователя с таким номером ещё нет — он будет создан со статусом.
"""

import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.models.enums import VerificationStatus
from backend.models.user import User
from backend.utils.phone_utils import normalize_phone_for_storage


async def grant(phone_raw: str, status_raw: str) -> int:
    try:
        phone = normalize_phone_for_storage(phone_raw)
    except ValueError as exc:
        print(f"Некорректный телефон '{phone_raw}': {exc}")
        return 2

    try:
        status = VerificationStatus(status_raw)
    except ValueError:
        allowed = ", ".join(s.value for s in VerificationStatus)
        print(f"Неизвестный статус '{status_raw}'. Допустимо: {allowed}")
        return 2

    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.phone == phone))
        user = result.scalar_one_or_none()

        if user is None:
            user = User(phone=phone, verification_status=status)
            db.add(user)
            await db.commit()
            await db.refresh(user)
            print(f"Создан пользователь {phone} со статусом '{status.value}'.")
            return 0

        previous = user.verification_status
        user.verification_status = status
        await db.commit()
        print(
            f"Пользователь {phone}: статус '{previous.value}' -> '{status.value}'."
        )
        return 0


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Использование: python -m backend.scripts.grant_verification "
            "<phone> [status=approved]"
        )
        raise SystemExit(2)

    phone_raw = sys.argv[1]
    status_raw = sys.argv[2] if len(sys.argv) > 2 else "approved"
    raise SystemExit(asyncio.run(grant(phone_raw, status_raw)))


if __name__ == "__main__":
    main()
