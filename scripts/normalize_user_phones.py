"""
Приводит users.phone к виду с ведущим '+' и удаляет дубликаты по нормализованному номеру.

Оставляет самую раннюю запись (по created_at), более поздние с тем же номером удаляет вместе с их сессиями/заявками.

  python scripts/normalize_user_phones.py

Нужен синхронный DB_URL (как у seed_admin), не +asyncpg.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.core.settings import settings
from backend.models.admin_user import AdminUser
from backend.models.auth_session import AuthSession
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
from backend.utils.phone_utils import normalize_phone_for_storage


def _purge_user(session: Session, uid: UUID) -> None:
    rental_ids = list(session.scalars(select(Rental.id).where(Rental.user_id == uid)).all())

    report_ids: set[UUID] = set()
    if rental_ids:
        report_ids.update(
            session.scalars(
                select(ConditionReport.id).where(ConditionReport.rental_id.in_(rental_ids))
            ).all()
        )
    report_ids.update(
        session.scalars(
            select(ConditionReport.id).where(ConditionReport.created_by_user_id == uid)
        ).all()
    )
    if report_ids:
        session.execute(
            delete(ConditionReportPhoto).where(ConditionReportPhoto.condition_report_id.in_(report_ids))
        )
        session.execute(delete(ConditionReport).where(ConditionReport.id.in_(report_ids)))

    if rental_ids:
        session.execute(delete(RentalEvent).where(RentalEvent.rental_id.in_(rental_ids)))
    session.execute(delete(Rental).where(Rental.user_id == uid))

    payment_ids_subq = select(Payment.id).where(Payment.user_id == uid)
    session.execute(delete(PaymentEvent).where(PaymentEvent.payment_id.in_(payment_ids_subq)))
    session.execute(delete(Payment).where(Payment.user_id == uid))

    session.execute(delete(Reservation).where(Reservation.user_id == uid))
    session.execute(delete(AuthSession).where(AuthSession.user_id == uid))
    session.execute(delete(VerificationRequest).where(VerificationRequest.user_id == uid))
    session.execute(update(MediaFile).where(MediaFile.uploaded_by_user_id == uid).values(uploaded_by_user_id=None))
    session.execute(delete(AdminUser).where(AdminUser.user_id == uid))
    session.execute(delete(User).where(User.id == uid))


def main() -> None:
    if not settings.DB_URL:
        raise RuntimeError("Задайте DB_URL")

    engine = create_engine(settings.DB_URL)

    with Session(engine) as session:
        users = list(
            session.scalars(select(User).order_by(User.created_at.asc(), User.id.asc())).all()
        )

        seen: dict[str, User] = {}
        removed = 0
        updated = 0

        for u in users:
            try:
                normalized = normalize_phone_for_storage(u.phone)
            except ValueError:
                print(f"Пропуск user {u.id}: некорректный телефон {u.phone!r}")
                continue

            if normalized in seen:
                print(f"Дубликат по номеру {normalized}: удаляю user {u.id} (оставлен {seen[normalized].id})")
                _purge_user(session, u.id)
                session.flush()
                removed += 1
                continue

            seen[normalized] = u
            if u.phone != normalized:
                u.phone = normalized
                updated += 1

        session.commit()

    print(f"Готово: обновлено телефонов: {updated}, удалено дубликатов: {removed}")


if __name__ == "__main__":
    main()
