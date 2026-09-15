"""Фото вещи при возврате в постамат.

Клиент снимает вещь в открытой ячейке, грузит кадр обычным presign+PUT
и присылает fileId в `confirm-return`. Операторы получают фото вместе с
«ожидает подтверждения», а если дверца завершила возврат раньше кнопки —
отдельным сообщением при досылке.

Здесь проверяется:
  * отчёт AFTER_RETURN, фото и событие пишутся в одной транзакции с
    завершением возврата, уведомление уходит с MediaFile и комментарием;
  * подтверждение без тела работает как раньше, но операторы видят «без фото»;
  * любой кривой файл (чужой, не того типа, не загруженный, уже в другом
    отчёте, больше четырёх) отбивается ДО перевода аренды;
  * досылка к возврату, который закрыла дверца: окно, идемпотентный повтор,
    запрет второго отчёта;
  * комментарий без фото после дверцы не теряется, а отчёт без фото ждёт
    фото, пока идёт окно;
  * аренда блокируется и перечитывается до любых проверок (двойное нажатие);
  * `returnReport` в `GET /me/rentals` и `GET /me/rentals/{id}` во всех
    состояниях (с данными квитанции), список — пачкой, без запроса на каждую аренду.

Байты реально ложатся в LOCAL_UPLOAD_ROOT (filesystem, как на проде).
Уведомления замоканы, ни один путь не шлёт в ESI `open-cell`.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

import httpx
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DB_PATH = os.path.abspath(f"./backend/tests/test_return_photos_{uuid4().hex}.sqlite")
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["DB_URL"] = TEST_DB_URL
os.environ["ASYNC_DB_URL"] = TEST_DB_URL
os.environ["YOOKASSA_DEV_STUB"] = "true"
os.environ["ESI_DEV_STUB"] = "true"
# Filesystem-хранилище, как на проде: presign отдаёт относительный PUT,
# байты реально пишутся на диск и проверка «файл загружен» работает.
os.environ["UPLOAD_DEV_STUB"] = "false"
os.environ["STORAGE_PROVIDER"] = "filesystem"
os.environ["UPLOAD_TOKEN_SECRET"] = "test-upload-token-secret"

from backend.main import app  # noqa: E402
from backend.core import database as core_db  # noqa: E402
from backend.core.database import Base, get_db  # noqa: E402
from backend.core.settings import settings  # noqa: E402
from backend.models.admin_user import AdminUser  # noqa: E402
from backend.models.auth_session import AuthSession  # noqa: E402
from backend.models.city import City  # noqa: E402
from backend.models.condition_report import ConditionReport  # noqa: E402
from backend.models.condition_report_photo import ConditionReportPhoto  # noqa: E402
from backend.models.enums import (  # noqa: E402
    AuthPlatform,
    ConditionReportType,
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    MediaFileKind,
    RentalEventSource,
    RentalStatus,
    ReturnRequestStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit  # noqa: E402
from backend.models.locker_cell import LockerCell  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402
from backend.models.media_file import MediaFile  # noqa: E402
from backend.models.price_plan import PricePlan  # noqa: E402
from backend.models.product import Product  # noqa: E402
from backend.models.product_category import ProductCategory  # noqa: E402
from backend.models.rental import Rental  # noqa: E402
from backend.models.rental_event import RentalEvent  # noqa: E402
from backend.models.return_request import ReturnRequest  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.utils.auth_utils import create_access_token  # noqa: E402
from backend.utils.return_photos import (  # noqa: E402
    load_return_report_views,
    serialize_admin_return_report,
)
from backend.utils.return_requests import complete_return_request  # noqa: E402

test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


async def override_get_db():
    async with TestSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db

PNG_1x1 = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108020000009077"
    "53DE0000000C4944415478DA63F8FFFFFFFFFFFFFF1F00080100FFFFFFFF"
    "0007FBFFFEEFEC0000000049454E44AE426082"
)
PHOTO_KIND = "condition_photo_after"


class ReturnPhotosTestBase(unittest.IsolatedAsyncioTestCase):
    """Аренда в возврате: заявка создана, ячейка зарезервирована, PIN у клиента.

    Рядом — вторая аренда того же клиента, которая в постамат не возвращалась.
    """

    async def asyncSetUp(self):
        self._old_settings = {
            name: getattr(settings, name)
            for name in (
                "YOOKASSA_DEV_STUB",
                "ESI_DEV_STUB",
                "UPLOAD_DEV_STUB",
                "STORAGE_PROVIDER",
                "UPLOAD_TOKEN_SECRET",
                "LOCAL_UPLOAD_ROOT",
                "MEDIA_PUBLIC_BASE_URL",
            )
        }
        self._tmp_uploads = tempfile.TemporaryDirectory()
        settings.YOOKASSA_DEV_STUB = True
        settings.ESI_DEV_STUB = True
        settings.UPLOAD_DEV_STUB = False
        settings.STORAGE_PROVIDER = "filesystem"
        settings.UPLOAD_TOKEN_SECRET = "test-upload-token-secret"
        settings.LOCAL_UPLOAD_ROOT = self._tmp_uploads.name
        settings.MEDIA_PUBLIC_BASE_URL = None

        self._patches = [patch.object(core_db, "SessionLocal", TestSessionLocal)]
        # ESI не должен понадобиться вовсе, а open-cell — тем более.
        self.esi_post = AsyncMock(return_value={})
        self._patches.append(patch("backend.utils.esi_client._esi_post", new=self.esi_post))
        self.notify_awaiting = Mock()
        self.notify_attached = Mock()
        self._patches.append(
            patch("backend.routers.me.notify_inventory_awaiting_confirmation", new=self.notify_awaiting)
        )
        self._patches.append(
            patch("backend.routers.me.notify_return_photos_attached", new=self.notify_attached)
        )
        # Страховка от реальной отправки, если какой-то путь обойдёт моки выше.
        self.fire_and_forget = Mock()
        self._patches.append(
            patch(
                "backend.utils.inventory_confirmation_notifications.fire_and_forget_notify",
                new=self.fire_and_forget,
            )
        )
        for active_patch in self._patches:
            active_patch.start()

        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        self.city_id = uuid4()
        self.category_id = uuid4()
        self.product_id = uuid4()
        self.plan_id = uuid4()
        self.user_id = uuid4()
        self.session_id = uuid4()
        self.other_user_id = uuid4()
        self.other_session_id = uuid4()
        self.locker_id = uuid4()
        self.cell_id = uuid4()
        self.unit_id = uuid4()
        self.rental_id = uuid4()
        self.return_request_id = uuid4()
        self.second_unit_id = uuid4()
        self.second_rental_id = uuid4()

        now = datetime.now(timezone.utc)
        async with TestSessionLocal() as db:
            db.add_all(
                [
                    City(
                        id=self.city_id,
                        name="Test City",
                        slug="test-city",
                        timezone="Europe/Moscow",
                        is_active=True,
                        sort_order=0,
                    ),
                    ProductCategory(
                        id=self.category_id,
                        name="Cat",
                        slug="cat",
                        is_active=True,
                        sort_order=0,
                    ),
                    Product(
                        id=self.product_id,
                        category_id=self.category_id,
                        name="Моющий пылесос",
                        slug="washing-vacuum",
                        is_active=True,
                    ),
                    PricePlan(
                        id=self.plan_id,
                        product_id=self.product_id,
                        name="1 day",
                        duration_type="day",
                        duration_value=1,
                        base_amount=Decimal("750.00"),
                        currency="RUB",
                        is_active=True,
                    ),
                    User(
                        id=self.user_id,
                        phone="+79995556677",
                        verification_status=VerificationStatus.APPROVED,
                    ),
                    AuthSession(
                        id=self.session_id,
                        user_id=self.user_id,
                        refresh_token_hash=f"hash-{uuid4().hex}",
                        platform=AuthPlatform.WEB,
                        expires_at=now + timedelta(days=30),
                    ),
                    User(
                        id=self.other_user_id,
                        phone="+79995556688",
                        verification_status=VerificationStatus.APPROVED,
                    ),
                    AuthSession(
                        id=self.other_session_id,
                        user_id=self.other_user_id,
                        refresh_token_hash=f"hash-{uuid4().hex}",
                        platform=AuthPlatform.WEB,
                        expires_at=now + timedelta(days=30),
                    ),
                    LockerLocation(
                        id=self.locker_id,
                        city_id=self.city_id,
                        name="ТРЦ Тестовый",
                        address="ул. Тестовая, 1",
                        status=LockerStatus.ONLINE,
                        external_provider="esi",
                        external_locker_id="ESI-TEST-PHOTO",
                    ),
                    LockerCell(
                        id=self.cell_id,
                        locker_id=self.locker_id,
                        label="B7",
                        external_cell_id="7",
                        status=LockerCellStatus.RESERVED,
                        supports_return=True,
                    ),
                    InventoryUnit(
                        id=self.unit_id,
                        product_id=self.product_id,
                        locker_cell_id=None,
                        status=InventoryStatus.RETURN_PENDING,
                        serial_number=f"SN-{uuid4().hex[:6]}",
                    ),
                    InventoryUnit(
                        id=self.second_unit_id,
                        product_id=self.product_id,
                        locker_cell_id=None,
                        status=InventoryStatus.RENTED,
                        serial_number=f"SN-{uuid4().hex[:6]}",
                    ),
                ]
            )
            await db.flush()
            db.add_all(
                [
                    Rental(
                        id=self.rental_id,
                        user_id=self.user_id,
                        inventory_unit_id=self.unit_id,
                        pickup_locker_id=self.locker_id,
                        return_locker_id=self.locker_id,
                        status=RentalStatus.RETURN_IN_PROGRESS,
                        pickup_pin="1234",
                        starts_at=now - timedelta(days=1),
                        planned_end_at=now + timedelta(hours=2),
                    ),
                    Rental(
                        id=self.second_rental_id,
                        user_id=self.user_id,
                        inventory_unit_id=self.second_unit_id,
                        pickup_locker_id=self.locker_id,
                        status=RentalStatus.ACTIVE,
                        pickup_pin="5678",
                        starts_at=now - timedelta(days=1),
                        planned_end_at=now + timedelta(hours=5),
                    ),
                ]
            )
            await db.flush()
            db.add(
                ReturnRequest(
                    id=self.return_request_id,
                    rental_id=self.rental_id,
                    locker_id=self.locker_id,
                    cell_id=self.cell_id,
                    pin="4417",
                    status=ReturnRequestStatus.CREATED,
                    requested_at=now - timedelta(minutes=5),
                    deadline_at=now + timedelta(minutes=25),
                )
            )
            await db.commit()

        self.auth_headers = {
            "Authorization": f"Bearer {create_access_token(self.user_id, self.session_id)}"
        }
        self.other_auth_headers = {
            "Authorization": f"Bearer {create_access_token(self.other_user_id, self.other_session_id)}"
        }
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        opened = [
            call.args[0]
            for call in self.esi_post.await_args_list
            if call.args and str(call.args[0]).startswith("/open-cell")
        ]
        for active_patch in reversed(self._patches):
            active_patch.stop()
        # Файл БД не удаляем: на Windows он ещё удерживается пулом, а между
        # тестами схему всё равно пересоздаёт `drop_all` в setUp.
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        for name, value in self._old_settings.items():
            setattr(settings, name, value)
        self._tmp_uploads.cleanup()
        self.assertEqual(opened, [], "фото при возврате не должны открывать ячейку")

    # --- загрузка ---------------------------------------------------------

    async def _presign(
        self,
        *,
        headers: dict | None = None,
        kind: str = PHOTO_KIND,
        file_name: str = "cell.png",
    ) -> dict:
        response = await self.client.post(
            "/uploads/presign",
            headers=headers or self.auth_headers,
            json={
                "fileName": file_name,
                "mimeType": "image/png",
                "fileSize": len(PNG_1x1),
                "kind": kind,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        presign = response.json()["data"]
        self.assertTrue(presign["uploadUrl"].startswith("/uploads/files/"), presign)
        return presign

    async def _upload_photo(self, *, headers: dict | None = None, kind: str = PHOTO_KIND) -> str:
        presign = await self._presign(headers=headers, kind=kind)
        put_response = await self.client.put(
            presign["uploadUrl"],
            headers=presign["headers"],
            content=PNG_1x1,
        )
        self.assertEqual(put_response.status_code, 200, put_response.text)
        return presign["fileId"]

    async def _upload_photos(self, count: int) -> list[str]:
        return [await self._upload_photo() for _ in range(count)]

    # --- действия -----------------------------------------------------------

    async def _confirm(self, body: dict | None = None, *, rental_id: UUID | None = None) -> httpx.Response:
        url = f"/me/rentals/{rental_id or self.rental_id}/confirm-return"
        if body is None:
            return await self.client.post(url, headers=self.auth_headers)
        return await self.client.post(url, headers=self.auth_headers, json=body)

    async def _complete_by_door(self, *, completed_at: datetime | None = None) -> None:
        """Как вебхук закрытия дверцы: возврат завершён без участия клиента."""
        async with TestSessionLocal() as db:
            request = await db.get(ReturnRequest, self.return_request_id)
            await complete_return_request(
                db,
                request=request,
                provider_event_id="door-closed-1",
                source=RentalEventSource.LOCKER_WEBHOOK,
            )
            if completed_at is not None:
                request.completed_at = completed_at
            await db.commit()

    # --- чтение состояния ----------------------------------------------------

    async def _reports(self) -> list[ConditionReport]:
        async with TestSessionLocal() as db:
            return list(
                (
                    await db.scalars(
                        select(ConditionReport).order_by(ConditionReport.created_at.asc())
                    )
                ).all()
            )

    async def _report_photos(self, report_id: UUID) -> list[ConditionReportPhoto]:
        async with TestSessionLocal() as db:
            return list(
                (
                    await db.scalars(
                        select(ConditionReportPhoto)
                        .where(ConditionReportPhoto.condition_report_id == report_id)
                        .order_by(ConditionReportPhoto.sort_order.asc())
                    )
                ).all()
            )

    async def _events(self, event_type: str) -> list[RentalEvent]:
        async with TestSessionLocal() as db:
            return list(
                (
                    await db.scalars(
                        select(RentalEvent).where(
                            RentalEvent.rental_id == self.rental_id,
                            RentalEvent.event_type == event_type,
                        )
                    )
                ).all()
            )

    async def _assert_return_untouched(self) -> None:
        """Отбитый запрос не должен сдвинуть возврат ни на шаг."""
        async with TestSessionLocal() as db:
            rental = await db.get(Rental, self.rental_id)
            request = await db.get(ReturnRequest, self.return_request_id)
            unit = await db.get(InventoryUnit, self.unit_id)
            cell = await db.get(LockerCell, self.cell_id)
        self.assertEqual(rental.status, RentalStatus.RETURN_IN_PROGRESS)
        self.assertIsNone(rental.completed_at)
        self.assertEqual(request.status, ReturnRequestStatus.CREATED)
        self.assertEqual(unit.status, InventoryStatus.RETURN_PENDING)
        self.assertIsNone(unit.locker_cell_id)
        self.assertEqual(cell.status, LockerCellStatus.RESERVED)
        self.assertEqual(await self._reports(), [])
        self.assertEqual(await self._events("return_completed"), [])
        self.assertEqual(await self._events("return_photos_attached"), [])
        self.notify_awaiting.assert_not_called()
        self.notify_attached.assert_not_called()

    async def _client_return_report(self, rental_id: UUID) -> tuple[dict | None, dict | None]:
        """returnReport из списка и из карточки — должны совпадать."""
        list_response = await self.client.get("/me/rentals", headers=self.auth_headers)
        self.assertEqual(list_response.status_code, 200, list_response.text)
        items = {item["id"]: item for item in list_response.json()["data"]["rentals"]}
        self.assertIn(str(rental_id), items)

        detail_response = await self.client.get(f"/me/rentals/{rental_id}", headers=self.auth_headers)
        self.assertEqual(detail_response.status_code, 200, detail_response.text)
        return items[str(rental_id)]["returnReport"], detail_response.json()["data"]["rental"]["returnReport"]


class ConfirmReturnWithPhotosTests(ReturnPhotosTestBase):
    async def test_one_photo_with_note_creates_report_and_notifies(self):
        file_id = await self._upload_photo()

        response = await self._confirm({"photoFileIds": [file_id], "note": "  Поцарапан корпус  "})

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["rental"], {"id": str(self.rental_id), "status": "completed"})

        reports = await self._reports()
        self.assertEqual(len(reports), 1)
        report = reports[0]
        self.assertEqual(report.rental_id, self.rental_id)
        self.assertEqual(report.inventory_unit_id, self.unit_id)
        self.assertEqual(report.report_type, ConditionReportType.AFTER_RETURN)
        self.assertEqual(report.created_by_user_id, self.user_id)
        self.assertEqual(report.note, "Поцарапан корпус")

        photos = await self._report_photos(report.id)
        self.assertEqual([(p.file_id, p.sort_order) for p in photos], [(UUID(file_id), 0)])

        events = await self._events("return_photos_attached")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source, RentalEventSource.USER)
        self.assertEqual(events[0].from_status, RentalStatus.COMPLETED)
        self.assertEqual(events[0].to_status, RentalStatus.COMPLETED)
        self.assertEqual(
            events[0].payload_json,
            {
                "conditionReportId": str(report.id),
                "returnRequestId": str(self.return_request_id),
                "photoCount": 1,
                "fileIds": [file_id],
            },
        )
        self.assertEqual(len(await self._events("return_completed")), 1)

        self.notify_awaiting.assert_called_once()
        self.notify_attached.assert_not_called()
        kwargs = self.notify_awaiting.call_args.kwargs
        self.assertEqual([m.id for m in kwargs["return_photos"]], [UUID(file_id)])
        self.assertTrue(all(isinstance(m, MediaFile) for m in kwargs["return_photos"]))
        self.assertEqual(kwargs["note"], "Поцарапан корпус")
        self.assertEqual(kwargs["rental"].id, self.rental_id)
        self.assertEqual(kwargs["cell"].id, self.cell_id)
        self.assertEqual(kwargs["locker"].id, self.locker_id)

        return_report = data["returnReport"]
        self.assertEqual(len(return_report["photos"]), 1)
        self.assertEqual(return_report["photos"][0]["id"], file_id)
        self.assertTrue(
            return_report["photos"][0]["url"].startswith("/assets/runtime-uploads/condition/"),
            return_report,
        )
        self.assertEqual(return_report["note"], "Поцарапан корпус")
        self.assertIsNotNone(return_report["submittedAt"])
        self.assertFalse(return_report["canAttachPhotos"])
        self.assertEqual(return_report["maxPhotos"], 4)

        async with TestSessionLocal() as db:
            request = await db.get(ReturnRequest, self.return_request_id)
            unit = await db.get(InventoryUnit, self.unit_id)
            cell = await db.get(LockerCell, self.cell_id)
        self.assertEqual(request.status, ReturnRequestStatus.COMPLETED)
        self.assertEqual(unit.status, InventoryStatus.AWAITING_CONFIRMATION)
        self.assertEqual(cell.status, LockerCellStatus.OCCUPIED)

    async def test_client_linked_to_admin_user_can_attach_own_photos(self):
        """Сотрудник возвращает вещь со своего клиентского аккаунта."""
        async with TestSessionLocal() as db:
            db.add(
                AdminUser(
                    id=uuid4(),
                    user_id=self.user_id,
                    email="operator@example.test",
                    password_hash="x",
                    full_name="Оператор",
                )
            )
            await db.commit()
        file_id = await self._upload_photo()

        response = await self._confirm({"photoFileIds": [file_id]})

        self.assertEqual(response.status_code, 200, response.text)
        async with TestSessionLocal() as db:
            media = await db.get(MediaFile, UUID(file_id))
        self.assertEqual(media.uploaded_by_user_id, self.user_id)
        self.assertEqual(len(await self._reports()), 1)

    async def test_three_photos_keep_order_and_duplicates_collapse(self):
        first, second, third = await self._upload_photos(3)

        response = await self._confirm({"photoFileIds": [first, second, first, third]})

        self.assertEqual(response.status_code, 200, response.text)
        reports = await self._reports()
        self.assertEqual(len(reports), 1)
        self.assertIsNone(reports[0].note)
        photos = await self._report_photos(reports[0].id)
        self.assertEqual(
            [(str(p.file_id), p.sort_order) for p in photos],
            [(first, 0), (second, 1), (third, 2)],
        )

        events = await self._events("return_photos_attached")
        self.assertEqual(events[0].payload_json["photoCount"], 3)
        self.assertEqual(events[0].payload_json["fileIds"], [first, second, third])

        self.notify_awaiting.assert_called_once()
        kwargs = self.notify_awaiting.call_args.kwargs
        self.assertEqual([str(m.id) for m in kwargs["return_photos"]], [first, second, third])
        self.assertIsNone(kwargs["note"])

        self.assertEqual(
            [photo["id"] for photo in response.json()["data"]["returnReport"]["photos"]],
            [first, second, third],
        )

    async def test_confirm_without_body_still_completes_and_says_no_photo(self):
        response = await self._confirm()

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["rental"]["status"], "completed")
        self.assertEqual(await self._reports(), [])
        self.assertEqual(await self._events("return_photos_attached"), [])

        self.notify_awaiting.assert_called_once()
        kwargs = self.notify_awaiting.call_args.kwargs
        self.assertEqual(kwargs["return_photos"], [])
        self.assertIsNone(kwargs["note"])

        # Возврат закрыт без фото — клиент ещё может дослать их в окне.
        return_report = data["returnReport"]
        self.assertEqual(return_report["photos"], [])
        self.assertTrue(return_report["canAttachPhotos"])
        self.assertIsNotNone(return_report["attachPhotosUntil"])

    async def test_note_without_photos_is_saved_as_report(self):
        response = await self._confirm({"photoFileIds": [], "note": "Камера не работает"})

        self.assertEqual(response.status_code, 200, response.text)
        reports = await self._reports()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].note, "Камера не работает")
        self.assertEqual(await self._report_photos(reports[0].id), [])
        kwargs = self.notify_awaiting.call_args.kwargs
        self.assertEqual(kwargs["return_photos"], [])
        self.assertEqual(kwargs["note"], "Камера не работает")

    async def test_blank_note_is_ignored(self):
        response = await self._confirm({"note": "   "})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(await self._reports(), [])
        self.assertIsNone(self.notify_awaiting.call_args.kwargs["note"])

    async def test_too_long_note_is_rejected_before_completion(self):
        response = await self._confirm({"note": "x" * 501})

        self.assertEqual(response.status_code, 422, response.text)
        await self._assert_return_untouched()


class ConfirmReturnRejectsBadPhotosTests(ReturnPhotosTestBase):
    async def test_more_than_four_photos(self):
        file_ids = [(await self._presign())["fileId"] for _ in range(5)]

        response = await self._confirm({"photoFileIds": file_ids})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "RETURN_PHOTOS_TOO_MANY")
        await self._assert_return_untouched()

    async def test_foreign_users_file(self):
        foreign_file_id = await self._upload_photo(headers=self.other_auth_headers)

        response = await self._confirm({"photoFileIds": [foreign_file_id]})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "RETURN_PHOTO_INVALID")
        await self._assert_return_untouched()

    async def test_unknown_file_id(self):
        response = await self._confirm({"photoFileIds": [str(uuid4())]})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "RETURN_PHOTO_INVALID")
        await self._assert_return_untouched()

    async def test_wrong_kind(self):
        selfie_id = await self._upload_photo(kind="verification_selfie")

        response = await self._confirm({"photoFileIds": [selfie_id]})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "RETURN_PHOTO_INVALID")
        await self._assert_return_untouched()

    async def test_old_key_with_document_extension(self):
        """Presign до выравнивания расширения по MIME мог оставить ключ .svg."""
        file_id = uuid4()
        async with TestSessionLocal() as db:
            db.add(
                MediaFile(
                    id=file_id,
                    storage_provider="stub",
                    bucket="dev-stub",
                    file_key=f"condition/2026/09/14/{file_id}-cell.svg",
                    mime_type="image/png",
                    file_size=len(PNG_1x1),
                    kind=MediaFileKind.CONDITION_PHOTO_AFTER,
                    uploaded_by_user_id=self.user_id,
                    created_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        response = await self._confirm({"photoFileIds": [str(file_id)]})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "RETURN_PHOTO_INVALID")
        await self._assert_return_untouched()

    async def test_file_on_disk_over_the_size_limit(self):
        """Файл, залитый до лимита на PUT, операторам не отправить."""
        file_id = await self._upload_photo()

        with patch("backend.utils.return_photos.max_size_for_kind", return_value=len(PNG_1x1) - 1):
            response = await self._confirm({"photoFileIds": [file_id]})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "RETURN_PHOTO_INVALID")
        await self._assert_return_untouched()

    async def test_presigned_but_never_uploaded(self):
        good_id = await self._upload_photo()
        missing_id = (await self._presign())["fileId"]

        response = await self._confirm({"photoFileIds": [good_id, missing_id]})

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"], "RETURN_PHOTO_NOT_UPLOADED")
        await self._assert_return_untouched()

    async def test_file_already_attached_to_another_report(self):
        file_id = await self._upload_photo()
        async with TestSessionLocal() as db:
            old_report = ConditionReport(
                inventory_unit_id=self.second_unit_id,
                rental_id=self.second_rental_id,
                report_type=ConditionReportType.AFTER_RETURN,
                created_by_user_id=self.user_id,
            )
            db.add(old_report)
            await db.flush()
            db.add(
                ConditionReportPhoto(
                    condition_report_id=old_report.id,
                    file_id=UUID(file_id),
                    sort_order=0,
                )
            )
            await db.commit()
            old_report_id = old_report.id

        response = await self._confirm({"photoFileIds": [file_id]})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "RETURN_PHOTO_INVALID")
        async with TestSessionLocal() as db:
            rental = await db.get(Rental, self.rental_id)
            reports = (await db.scalars(select(ConditionReport))).all()
        self.assertEqual(rental.status, RentalStatus.RETURN_IN_PROGRESS)
        self.assertEqual([r.id for r in reports], [old_report_id])
        self.notify_awaiting.assert_not_called()

    async def test_stub_storage_skips_bytes_check(self):
        """Без filesystem проверить байты нечем — файл принимаем."""
        file_id = uuid4()
        async with TestSessionLocal() as db:
            db.add(
                MediaFile(
                    id=file_id,
                    storage_provider="stub",
                    bucket="dev-stub",
                    file_key=f"condition/stub/{file_id}.png",
                    mime_type="image/png",
                    file_size=len(PNG_1x1),
                    kind=MediaFileKind.CONDITION_PHOTO_AFTER,
                    uploaded_by_user_id=self.user_id,
                    created_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        response = await self._confirm({"photoFileIds": [str(file_id)]})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(await self._reports()), 1)

    async def test_rental_that_is_not_returning(self):
        file_id = await self._upload_photo()

        response = await self._confirm({"photoFileIds": [file_id]}, rental_id=self.second_rental_id)

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"], "RENTAL_NOT_RETURNING")
        self.assertEqual(await self._reports(), [])


class LateReturnPhotosTests(ReturnPhotosTestBase):
    """Дверца закрыла возврат раньше, чем клиент нажал «Подтвердить»."""

    async def test_late_photos_within_window_create_report_and_notify(self):
        await self._complete_by_door()
        first, second = await self._upload_photos(2)

        response = await self._confirm({"photoFileIds": [first, second], "note": "Положил ровно"})

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["rental"]["status"], "completed")

        reports = await self._reports()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].note, "Положил ровно")
        photos = await self._report_photos(reports[0].id)
        self.assertEqual([str(p.file_id) for p in photos], [first, second])

        events = await self._events("return_photos_attached")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload_json["returnRequestId"], str(self.return_request_id))
        self.assertEqual(events[0].from_status, RentalStatus.COMPLETED)

        self.notify_awaiting.assert_not_called()
        self.notify_attached.assert_called_once()
        kwargs = self.notify_attached.call_args.kwargs
        self.assertEqual([str(m.id) for m in kwargs["return_photos"]], [first, second])
        self.assertEqual(kwargs["note"], "Положил ровно")
        self.assertEqual(kwargs["locker"].id, self.locker_id)
        self.assertEqual(kwargs["cell"].id, self.cell_id)
        self.assertEqual(kwargs["unit"].id, self.unit_id)
        self.assertEqual(kwargs["product"].id, self.product_id)
        self.assertEqual(kwargs["rental"].id, self.rental_id)

        return_report = data["returnReport"]
        self.assertEqual([p["id"] for p in return_report["photos"]], [first, second])
        self.assertFalse(return_report["canAttachPhotos"])

    async def test_completed_without_photos_in_request_is_a_no_op(self):
        await self._complete_by_door()

        response = await self._confirm()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["rental"]["status"], "completed")
        self.assertTrue(response.json()["data"]["returnReport"]["canAttachPhotos"])
        self.assertEqual(await self._reports(), [])
        self.notify_awaiting.assert_not_called()
        self.notify_attached.assert_not_called()

    async def test_late_photos_after_window_are_refused(self):
        window = settings.RETURN_PHOTO_LATE_WINDOW_MINUTES
        await self._complete_by_door(
            completed_at=datetime.now(timezone.utc) - timedelta(minutes=window + 1)
        )
        file_id = await self._upload_photo()

        response = await self._confirm({"photoFileIds": [file_id]})

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"], "RETURN_PHOTOS_WINDOW_CLOSED")
        self.assertEqual(await self._reports(), [])
        self.notify_attached.assert_not_called()

    async def test_completed_without_return_request_refuses_photos(self):
        """Админ закрыл аренду в обход постамата — окна досылки нет."""
        async with TestSessionLocal() as db:
            rental = await db.get(Rental, self.second_rental_id)
            rental.status = RentalStatus.COMPLETED
            rental.completed_at = datetime.now(timezone.utc)
            await db.commit()
        file_id = await self._upload_photo()

        response = await self._confirm({"photoFileIds": [file_id]}, rental_id=self.second_rental_id)

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"], "RETURN_PHOTOS_WINDOW_CLOSED")
        self.assertEqual(await self._reports(), [])

    async def test_repeating_the_same_late_request_is_idempotent(self):
        await self._complete_by_door()
        first, second = await self._upload_photos(2)

        first_response = await self._confirm({"photoFileIds": [first, second]})
        self.assertEqual(first_response.status_code, 200, first_response.text)

        # Ответ потерялся — клиент повторяет тот же набор (порядок не важен).
        repeat_response = await self._confirm({"photoFileIds": [second, first]})

        self.assertEqual(repeat_response.status_code, 200, repeat_response.text)
        self.assertEqual(len(await self._reports()), 1)
        self.assertEqual(len(await self._events("return_photos_attached")), 1)
        self.notify_attached.assert_called_once()
        self.assertEqual(
            [p["id"] for p in repeat_response.json()["data"]["returnReport"]["photos"]],
            [first, second],
        )

    async def test_repeat_after_confirm_with_photos_is_idempotent(self):
        file_id = await self._upload_photo()
        first_response = await self._confirm({"photoFileIds": [file_id]})
        self.assertEqual(first_response.status_code, 200, first_response.text)

        repeat_response = await self._confirm({"photoFileIds": [file_id]})

        self.assertEqual(repeat_response.status_code, 200, repeat_response.text)
        self.assertEqual(len(await self._reports()), 1)
        self.notify_awaiting.assert_called_once()
        self.notify_attached.assert_not_called()

    async def test_different_files_after_report_are_refused(self):
        await self._complete_by_door()
        first = await self._upload_photo()
        response = await self._confirm({"photoFileIds": [first]})
        self.assertEqual(response.status_code, 200, response.text)

        other = await self._upload_photo()
        second_response = await self._confirm({"photoFileIds": [first, other]})

        self.assertEqual(second_response.status_code, 409, second_response.text)
        self.assertEqual(second_response.json()["detail"], "RETURN_PHOTOS_ALREADY_SENT")
        reports = await self._reports()
        self.assertEqual(len(reports), 1)
        self.assertEqual(
            [str(p.file_id) for p in await self._report_photos(reports[0].id)],
            [first],
        )
        self.notify_attached.assert_called_once()

    async def test_note_only_request_after_photo_report_is_a_no_op(self):
        await self._complete_by_door()
        file_id = await self._upload_photo()
        response = await self._confirm({"photoFileIds": [file_id], "note": "Положил ровно"})
        self.assertEqual(response.status_code, 200, response.text)

        repeat = await self._confirm({"note": "Забыл сказать"})

        self.assertEqual(repeat.status_code, 200, repeat.text)
        reports = await self._reports()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].note, "Положил ровно")
        self.notify_attached.assert_called_once()


class LateReturnNoteTests(ReturnPhotosTestBase):
    """Отчёт без фото: комментарий не теряется, фото к нему можно дослать."""

    async def test_note_without_photos_after_door_creates_note_only_report(self):
        await self._complete_by_door()

        response = await self._confirm({"photoFileIds": [], "note": "Дверца заедает"})

        self.assertEqual(response.status_code, 200, response.text)
        reports = await self._reports()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].note, "Дверца заедает")
        self.assertEqual(await self._report_photos(reports[0].id), [])
        events = await self._events("return_photos_attached")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload_json["photoCount"], 0)
        self.assertEqual(events[0].payload_json["returnRequestId"], str(self.return_request_id))

        # Операторы узнают о комментарии: пустой список — «клиент фото не приложил».
        self.notify_awaiting.assert_not_called()
        self.notify_attached.assert_called_once()
        kwargs = self.notify_attached.call_args.kwargs
        self.assertEqual(kwargs["return_photos"], [])
        self.assertEqual(kwargs["note"], "Дверца заедает")
        self.assertEqual(kwargs["cell"].id, self.cell_id)

        return_report = response.json()["data"]["returnReport"]
        self.assertEqual(return_report["note"], "Дверца заедает")
        self.assertIsNotNone(return_report["submittedAt"])
        # Отчёт без фото остаётся открытым для фото.
        self.assertTrue(return_report["canAttachPhotos"])
        self.assertIsNotNone(return_report["attachPhotosUntil"])

    async def test_photos_after_note_only_report_join_the_same_report(self):
        # Фото не загрузилось — клиент подтвердил с комментарием, пока шёл возврат.
        first_response = await self._confirm({"note": "Фото не грузится"})
        self.assertEqual(first_response.status_code, 200, first_response.text)
        first_report = first_response.json()["data"]["returnReport"]
        self.assertTrue(first_report["canAttachPhotos"])
        self.assertIsNotNone(first_report["attachPhotosUntil"])
        self.notify_awaiting.assert_called_once()
        from_list, from_detail = await self._client_return_report(self.rental_id)
        self.assertTrue(from_list["canAttachPhotos"])
        self.assertEqual(from_list, from_detail)

        # Связь появилась — досылаем фото тем же confirm-return.
        first, second = await self._upload_photos(2)
        response = await self._confirm({"photoFileIds": [first, second]})

        self.assertEqual(response.status_code, 200, response.text)
        reports = await self._reports()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].note, "Фото не грузится")
        self.assertEqual(
            [(str(p.file_id), p.sort_order) for p in await self._report_photos(reports[0].id)],
            [(first, 0), (second, 1)],
        )
        events = await self._events("return_photos_attached")
        self.assertEqual(
            sorted(event.payload_json["photoCount"] for event in events),
            [0, 2],
        )
        attached_event = next(e for e in events if e.payload_json["photoCount"] == 2)
        self.assertEqual(attached_event.payload_json["conditionReportId"], str(reports[0].id))
        self.assertEqual(attached_event.payload_json["fileIds"], [first, second])

        self.notify_attached.assert_called_once()
        kwargs = self.notify_attached.call_args.kwargs
        self.assertEqual([str(m.id) for m in kwargs["return_photos"]], [first, second])
        self.assertEqual(kwargs["note"], "Фото не грузится")

        return_report = response.json()["data"]["returnReport"]
        self.assertEqual([p["id"] for p in return_report["photos"]], [first, second])
        self.assertFalse(return_report["canAttachPhotos"])
        self.assertIsNone(return_report["attachPhotosUntil"])

        # Повтор — идемпотентно, другой набор — уже поздно.
        repeat = await self._confirm({"photoFileIds": [second, first]})
        self.assertEqual(repeat.status_code, 200, repeat.text)
        other = await self._upload_photo()
        refused = await self._confirm({"photoFileIds": [other]})
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertEqual(refused.json()["detail"], "RETURN_PHOTOS_ALREADY_SENT")
        self.notify_attached.assert_called_once()

    async def test_photos_with_new_note_replace_note_of_note_only_report(self):
        await self._complete_by_door()
        await self._confirm({"note": "Камера не работает"})
        file_id = await self._upload_photo()

        response = await self._confirm({"photoFileIds": [file_id], "note": "Всё-таки снял"})

        self.assertEqual(response.status_code, 200, response.text)
        reports = await self._reports()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].note, "Всё-таки снял")
        self.assertEqual(self.notify_attached.call_count, 2)
        kwargs = self.notify_attached.call_args.kwargs
        self.assertEqual([str(m.id) for m in kwargs["return_photos"]], [file_id])
        self.assertEqual(kwargs["note"], "Всё-таки снял")

    async def test_changed_note_on_report_without_photos_updates_quietly(self):
        await self._complete_by_door()
        await self._confirm({"note": "Дверца заедает"})
        self.notify_attached.assert_called_once()

        same = await self._confirm({"note": "Дверца заедает"})
        changed = await self._confirm({"note": "Дверца заедает, корпус цел"})

        self.assertEqual(same.status_code, 200, same.text)
        self.assertEqual(changed.status_code, 200, changed.text)
        reports = await self._reports()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].note, "Дверца заедает, корпус цел")
        self.assertEqual(changed.json()["data"]["returnReport"]["note"], "Дверца заедает, корпус цел")
        self.assertEqual(len(await self._events("return_photos_attached")), 1)
        self.notify_attached.assert_called_once()

    async def test_note_or_photos_after_window_are_refused_but_empty_body_is_not(self):
        window = settings.RETURN_PHOTO_LATE_WINDOW_MINUTES
        await self._complete_by_door(
            completed_at=datetime.now(timezone.utc) - timedelta(minutes=window + 1)
        )

        empty = await self._confirm()
        note_only = await self._confirm({"note": "Дверца заедает"})

        self.assertEqual(empty.status_code, 200, empty.text)
        self.assertEqual(note_only.status_code, 409, note_only.text)
        self.assertEqual(note_only.json()["detail"], "RETURN_PHOTOS_WINDOW_CLOSED")
        self.assertEqual(await self._reports(), [])
        self.notify_attached.assert_not_called()

    async def test_photos_to_note_only_report_after_window_are_refused(self):
        await self._confirm({"note": "Фото не грузится"})
        window = settings.RETURN_PHOTO_LATE_WINDOW_MINUTES
        async with TestSessionLocal() as db:
            request = await db.get(ReturnRequest, self.return_request_id)
            request.completed_at = datetime.now(timezone.utc) - timedelta(minutes=window + 1)
            await db.commit()
        from_list, _ = await self._client_return_report(self.rental_id)
        self.assertFalse(from_list["canAttachPhotos"])
        self.assertEqual(from_list["note"], "Фото не грузится")
        file_id = await self._upload_photo()

        response = await self._confirm({"photoFileIds": [file_id]})

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"], "RETURN_PHOTOS_WINDOW_CLOSED")
        reports = await self._reports()
        self.assertEqual(await self._report_photos(reports[0].id), [])
        self.notify_attached.assert_not_called()


class ConfirmReturnLockTests(ReturnPhotosTestBase):
    """Двойное нажатие: аренда блокируется и перечитывается до любых проверок."""

    async def test_rental_is_locked_and_reread_before_anything_else(self):
        from sqlalchemy.orm import Session

        executed: list = []

        def _capture(orm_execute_state):
            executed.append(orm_execute_state)

        event.listen(Session, "do_orm_execute", _capture)
        try:
            file_id = await self._upload_photo()
            executed.clear()
            response = await self._confirm({"photoFileIds": [file_id]})
        finally:
            event.remove(Session, "do_orm_execute", _capture)

        self.assertEqual(response.status_code, 200, response.text)
        rental_selects = [
            state
            for state in executed
            if state.is_select
            and any(
                desc.get("entity") is Rental for desc in state.statement.column_descriptions
            )
        ]
        self.assertTrue(rental_selects, "аренда должна читаться запросом, а не из identity map")
        first = rental_selects[0]
        self.assertIsNotNone(first.statement._for_update_arg, "аренда должна браться FOR UPDATE")
        self.assertTrue(first.execution_options.get("populate_existing"))
        # До блокировки — только авторизация, никаких заявок и отчётов.
        before_lock = executed[: executed.index(first)]
        touched = {
            desc.get("entity")
            for state in before_lock
            if state.is_select
            for desc in state.statement.column_descriptions
        }
        self.assertFalse(touched & {ReturnRequest, ConditionReport, ConditionReportPhoto, MediaFile})

    async def test_second_submit_that_waited_for_the_lock_takes_the_idempotent_path(self):
        """Второй запрос успел прочитать аренду до commit первого.

        Под блокировкой он перечитывает статус и не завершает возврат повторно.
        """
        file_id = await self._upload_photo()
        first = await self._confirm({"photoFileIds": [file_id]})
        self.assertEqual(first.status_code, 200, first.text)

        from backend.routers import me as me_router

        original_auth = me_router.get_current_client_user
        rental_id = self.rental_id

        async def auth_with_stale_rental(request, db):
            user = await original_auth(request, db)
            stale = await db.get(Rental, rental_id)
            # Как будто этот запрос прочитал аренду ещё до commit первого.
            stale.status = RentalStatus.RETURN_IN_PROGRESS
            return user

        # Держим «старое» состояние в identity map без flush: без populate_existing
        # ручка увидела бы RETURN_IN_PROGRESS и пошла завершать возврат снова.
        with patch.object(me_router, "get_current_client_user", new=auth_with_stale_rental):
            second = await self._confirm({"photoFileIds": [file_id]})

        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["data"]["rental"]["status"], "completed")
        self.assertEqual(len(await self._reports()), 1)
        self.assertEqual(len(await self._events("return_completed")), 1)
        self.assertEqual(len(await self._events("return_photos_attached")), 1)
        self.notify_awaiting.assert_called_once()
        self.notify_attached.assert_not_called()


class ClientReturnReportTests(ReturnPhotosTestBase):
    async def test_return_in_progress_accepts_photos(self):
        from_list, from_detail = await self._client_return_report(self.rental_id)

        expected = {
            "photos": [],
            "note": None,
            "submittedAt": None,
            "canAttachPhotos": True,
            "attachPhotosUntil": None,
            "maxPhotos": 4,
            # Возврат ещё не завершён — квитанции не из чего собираться.
            "lockerName": None,
            "cellLabel": None,
            "returnedAt": None,
        }
        self.assertEqual(from_list, expected)
        self.assertEqual(from_detail, expected)

    async def test_rental_without_any_return_has_no_report(self):
        from_list, from_detail = await self._client_return_report(self.second_rental_id)

        self.assertIsNone(from_list)
        self.assertIsNone(from_detail)

    async def test_completed_by_door_is_open_for_late_photos(self):
        before = datetime.now(timezone.utc)
        await self._complete_by_door()

        from_list, from_detail = await self._client_return_report(self.rental_id)

        self.assertEqual(from_list, from_detail)
        self.assertTrue(from_list["canAttachPhotos"])
        self.assertEqual(from_list["photos"], [])
        self.assertIsNone(from_list["submittedAt"])
        # Квитанция: постамат, ячейка и время из завершённой заявки.
        self.assertEqual(from_list["lockerName"], "ТРЦ Тестовый")
        self.assertEqual(from_list["cellLabel"], "B7")
        async with TestSessionLocal() as db:
            request = await db.get(ReturnRequest, self.return_request_id)
        self.assertEqual(
            datetime.fromisoformat(from_list["returnedAt"]),
            request.completed_at.replace(tzinfo=request.completed_at.tzinfo or timezone.utc),
        )
        until = datetime.fromisoformat(from_list["attachPhotosUntil"])
        self.assertIsNotNone(until.tzinfo)
        window = timedelta(minutes=settings.RETURN_PHOTO_LATE_WINDOW_MINUTES)
        self.assertGreaterEqual(until, before + window - timedelta(seconds=5))
        self.assertLessEqual(until, datetime.now(timezone.utc) + window + timedelta(seconds=5))

    async def test_completed_after_window_is_closed(self):
        window = settings.RETURN_PHOTO_LATE_WINDOW_MINUTES
        completed_at = datetime.now(timezone.utc) - timedelta(minutes=window + 1)
        await self._complete_by_door(completed_at=completed_at)

        from_list, from_detail = await self._client_return_report(self.rental_id)

        expected = {
            "photos": [],
            "note": None,
            "submittedAt": None,
            "canAttachPhotos": False,
            "attachPhotosUntil": None,
            "maxPhotos": 4,
            "lockerName": "ТРЦ Тестовый",
            "cellLabel": "B7",
            "returnedAt": from_list["returnedAt"],
        }
        self.assertEqual(from_list, expected)
        self.assertEqual(from_detail, expected)
        self.assertEqual(datetime.fromisoformat(from_list["returnedAt"]), completed_at)

    async def test_completed_with_report_shows_photos(self):
        first, second = await self._upload_photos(2)
        response = await self._confirm({"photoFileIds": [first, second], "note": "Всё цело"})
        self.assertEqual(response.status_code, 200, response.text)

        from_list, from_detail = await self._client_return_report(self.rental_id)

        self.assertEqual(from_list, from_detail)
        self.assertEqual([p["id"] for p in from_list["photos"]], [first, second])
        for photo in from_list["photos"]:
            self.assertTrue(photo["url"].startswith("/assets/runtime-uploads/condition/"), photo)
        self.assertEqual(from_list["note"], "Всё цело")
        self.assertIsNotNone(datetime.fromisoformat(from_list["submittedAt"]).tzinfo)
        self.assertFalse(from_list["canAttachPhotos"])
        self.assertIsNone(from_list["attachPhotosUntil"])
        self.assertEqual(from_list["maxPhotos"], 4)
        self.assertEqual(from_list["lockerName"], "ТРЦ Тестовый")
        self.assertEqual(from_list["cellLabel"], "B7")
        self.assertIsNotNone(datetime.fromisoformat(from_list["returnedAt"]).tzinfo)

    async def test_list_loads_reports_in_constant_number_of_queries(self):
        file_id = await self._upload_photo()
        response = await self._confirm({"photoFileIds": [file_id]})
        self.assertEqual(response.status_code, 200, response.text)

        statements: list[str] = []

        def _count(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(test_engine.sync_engine, "before_cursor_execute", _count)
        try:
            async with TestSessionLocal() as db:
                views = await load_return_report_views(
                    db, [self.rental_id, self.second_rental_id, uuid4()]
                )
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", _count)

        self.assertLessEqual(len(statements), 4, statements)
        self.assertEqual([m.id for m in views[self.rental_id].photos], [UUID(file_id)])
        self.assertIsNone(views[self.second_rental_id].report)
        self.assertFalse(views[self.second_rental_id].has_any_return_request)

    async def test_admin_serialization_of_report_and_missing_photo(self):
        await self._complete_by_door()
        async with TestSessionLocal() as db:
            views = await load_return_report_views(db, [self.rental_id, self.second_rental_id])
            rental = await db.get(Rental, self.rental_id)
            second_rental = await db.get(Rental, self.second_rental_id)
        without_photo = serialize_admin_return_report(rental, views[self.rental_id])
        self.assertEqual(without_photo["id"], None)
        self.assertEqual(without_photo["photos"], [])
        self.assertEqual(without_photo["photoCount"], 0)
        self.assertTrue(without_photo["expected"])
        self.assertIsNotNone(without_photo["returnedAt"])
        # Флаг проверки считает вызывающий; по умолчанию кнопок нет.
        self.assertFalse(without_photo["pendingReview"])
        # Фото нет, но окно открыто — операторы видят, до какого времени ждать.
        until = datetime.fromisoformat(without_photo["attachPhotosUntil"])
        window = timedelta(minutes=settings.RETURN_PHOTO_LATE_WINDOW_MINUTES)
        self.assertEqual(until, datetime.fromisoformat(without_photo["returnedAt"]) + window)
        self.assertTrue(
            serialize_admin_return_report(rental, views[self.rental_id], pending_review=True)[
                "pendingReview"
            ]
        )
        after_window = serialize_admin_return_report(
            rental, views[self.rental_id], now=until + timedelta(seconds=1)
        )
        self.assertIsNone(after_window["attachPhotosUntil"])
        self.assertIsNone(serialize_admin_return_report(second_rental, views[self.second_rental_id]))

        file_id = await self._upload_photo()
        response = await self._confirm({"photoFileIds": [file_id], "note": "ok"})
        self.assertEqual(response.status_code, 200, response.text)
        async with TestSessionLocal() as db:
            view = (await load_return_report_views(db, [self.rental_id]))[self.rental_id]
            rental = await db.get(Rental, self.rental_id)
        admin_payload = serialize_admin_return_report(rental, view)
        self.assertEqual(admin_payload["source"], "user")
        self.assertEqual(admin_payload["photoCount"], 1)
        self.assertEqual(admin_payload["photos"][0]["id"], file_id)
        self.assertEqual(admin_payload["photos"][0]["mimeType"], "image/png")
        self.assertEqual(admin_payload["photos"][0]["fileSize"], len(PNG_1x1))
        self.assertEqual(admin_payload["note"], "ok")
        self.assertTrue(admin_payload["expected"])
        # Фото пришли — ждать больше нечего.
        self.assertIsNone(admin_payload["attachPhotosUntil"])


if __name__ == "__main__":
    unittest.main()
