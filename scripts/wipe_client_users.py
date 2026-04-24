"""
Удаляет всех клиентских пользователей и связанные с ними строки (аренды, платежи, сессии и т.д.).

Не трогает: admin_accounts, города, постаматы, каталог, admin_auth_sessions (по желанию — см. ниже).

Запуск из корня репозитория (нужен DB_URL в окружении или .env):

  python scripts/wipe_client_users.py

Перед миграциями / сменой схемы можно выполнить этот скрипт, чтобы очистить тестовые данные.

После импорта старых дампов с «кривыми» телефонами запустите: python scripts/normalize_user_phones.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.core.settings import settings
from backend.models.admin_user import AdminUser
from backend.models.auth_session import AuthSession
from backend.models.auth_verification_session import AuthVerificationSession
from backend.models.condition_report import ConditionReport
from backend.models.condition_report_photo import ConditionReportPhoto
from backend.models.media_file import MediaFile
from backend.models.payment import Payment
from backend.models.payment_event import PaymentEvent
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.reservation import Reservation
from backend.models.user import User
from backend.models.verification_request import VerificationRequest


def main() -> None:
    if not settings.DB_URL:
        raise RuntimeError("Задайте DB_URL (sync URL, например postgresql+psycopg://...)")

    from sqlalchemy import create_engine

    engine = create_engine(settings.DB_URL)

    with Session(engine) as session:
        session.execute(delete(ConditionReportPhoto))
        session.execute(delete(ConditionReport))
        session.execute(delete(RentalEvent))
        session.execute(delete(PaymentEvent))
        session.execute(delete(Payment))
        session.execute(delete(Rental))
        session.execute(delete(Reservation))
        session.execute(delete(AuthSession))
        session.execute(delete(VerificationRequest))
        session.execute(update(MediaFile).values(uploaded_by_user_id=None))
        session.execute(delete(AdminUser))
        session.execute(delete(User))
        session.execute(delete(AuthVerificationSession))
        session.commit()

    print("Готово: users и связанные данные удалены (admin_accounts сохранены).")


if __name__ == "__main__":
    main()
