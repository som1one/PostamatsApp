"""Загрузка файлов: presign и PUT не пропускают то, что нельзя отдавать как картинку.

Здесь проверяется:
  * расширение ключа берётся из объявленного MIME, а не из имени файла —
    StaticFiles отдаёт по расширению, и «cell.svg» стал бы документом;
  * PUT режет тело больше лимита вида (и по Content-Length, и потоком);
  * PUT картинки проверяет сигнатуру байтов, а не только заголовок;
  * PUT не перезаписывает файл, который уже лежит в отчёте о состоянии;
  * клиентский presign всегда пишет владельца-клиента, даже если к нему
    привязан админ;
  * загрузка обложки товара из админки идёт через тот же PUT и работает.

Байты реально ложатся в LOCAL_UPLOAD_ROOT (filesystem, как на проде).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

os.environ["UPLOAD_DEV_STUB"] = "false"
os.environ["STORAGE_PROVIDER"] = "filesystem"
os.environ["UPLOAD_TOKEN_SECRET"] = "test-upload-token-secret"
os.environ["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "test-jwt-secret")

import httpx  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from backend.main import app  # noqa: E402
from backend.core.database import Base, get_db  # noqa: E402
from backend.core.settings import settings  # noqa: E402
from backend.models.admin_account import AdminAccount  # noqa: E402
from backend.models.admin_user import AdminUser  # noqa: E402
from backend.models.auth_session import AuthSession  # noqa: E402
from backend.models.condition_report import ConditionReport  # noqa: E402
from backend.models.condition_report_photo import ConditionReportPhoto  # noqa: E402
from backend.models.enums import (  # noqa: E402
    AdminRole,
    AuthPlatform,
    ConditionReportType,
    InventoryStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit  # noqa: E402
from backend.models.media_file import MediaFile  # noqa: E402
from backend.models.product import Product  # noqa: E402
from backend.models.product_category import ProductCategory  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.utils.admin_auth_utils import hash_password  # noqa: E402
from backend.utils.auth_utils import create_access_token  # noqa: E402
from backend.utils.local_storage import local_upload_path  # noqa: E402
from backend.utils.uploads_utils import MAX_FILE_SIZE_IMAGE, build_file_key  # noqa: E402

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


async def override_get_db():
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db

PNG_1x1 = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108020000009077"
    "53DE0000000C4944415478DA63F8FFFFFFFFFFFFFF1F00080100FFFFFFFF"
    "0007FBFFFEEFEC0000000049454E44AE426082"
)
JPEG_HEAD = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 32
WEBP_HEAD = b"RIFF\x24\x00\x00\x00WEBPVP8 \x18\x00\x00\x00" + b"\x00" * 24
GIF_HEAD = b"GIF89a\x01\x00\x01\x00\x80\x00\x00" + b"\x00" * 16
SVG_WITH_SCRIPT = (
    b'<svg xmlns="http://www.w3.org/2000/svg"><script>'
    b"fetch('/steal?t='+localStorage.getItem('postamats-admin-auth'))"
    b"</script></svg>"
)
PHOTO_KIND = "condition_photo_after"


class UploadHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._old_settings = {
            name: getattr(settings, name)
            for name in (
                "UPLOAD_DEV_STUB",
                "STORAGE_PROVIDER",
                "UPLOAD_TOKEN_SECRET",
                "LOCAL_UPLOAD_ROOT",
            )
        }
        self._tmp_uploads = tempfile.TemporaryDirectory()
        settings.UPLOAD_DEV_STUB = False
        settings.STORAGE_PROVIDER = "filesystem"
        settings.UPLOAD_TOKEN_SECRET = "test-upload-token-secret"
        settings.LOCAL_UPLOAD_ROOT = self._tmp_uploads.name

        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        self.user_id = uuid4()
        self.session_id = uuid4()
        now = datetime.now(timezone.utc)
        async with TestSessionLocal() as db:
            db.add_all(
                [
                    User(
                        id=self.user_id,
                        phone="+79995550011",
                        verification_status=VerificationStatus.APPROVED,
                    ),
                    AuthSession(
                        id=self.session_id,
                        user_id=self.user_id,
                        refresh_token_hash=f"hash-{uuid4().hex}",
                        platform=AuthPlatform.WEB,
                        expires_at=now + timedelta(days=30),
                    ),
                    AdminAccount(
                        name="Catalog Admin",
                        login="catalog-admin",
                        role=AdminRole.SUPER_ADMIN,
                        password_hash=hash_password("admin123"),
                    ),
                ]
            )
            await db.commit()

        self.auth_headers = {
            "Authorization": f"Bearer {create_access_token(self.user_id, self.session_id)}"
        }
        self.redis_patcher = patch("backend.core.redis.init_redis", new_callable=AsyncMock)
        self.redis_patcher.start()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        self.redis_patcher.stop()
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        for name, value in self._old_settings.items():
            setattr(settings, name, value)
        self._tmp_uploads.cleanup()

    # --- helpers ------------------------------------------------------------

    async def _presign(
        self,
        *,
        file_name: str = "cell.png",
        mime_type: str = "image/png",
        kind: str = PHOTO_KIND,
        file_size: int = len(PNG_1x1),
        headers: dict | None = None,
        url: str = "/uploads/presign",
    ) -> dict:
        response = await self.client.post(
            url,
            headers=self.auth_headers if headers is None else headers,
            json={
                "fileName": file_name,
                "mimeType": mime_type,
                "fileSize": file_size,
                "kind": kind,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        presign = response.json()["data"]
        self.assertTrue(presign["uploadUrl"].startswith("/uploads/files/"), presign)
        return presign

    async def _put(self, presign: dict, content) -> httpx.Response:
        return await self.client.put(presign["uploadUrl"], headers=presign["headers"], content=content)

    def _stored_path(self, presign: dict) -> Path:
        return local_upload_path(presign["fileKey"])

    # --- ключ файла -----------------------------------------------------------

    async def test_file_key_extension_follows_declared_mime(self):
        cases = [
            ("cell.svg", "image/png", "-cell.png"),
            ("report.html", "image/jpeg", "-report.jpg"),
            ("IMG_0042.JPEG", "image/jpeg", "-IMG_0042.jpg"),
            ("shot", "image/webp", "-shot.webp"),
            ("evil.html.png", "image/png", "-evil.html.png"),
        ]
        for file_name, mime_type, suffix in cases:
            with self.subTest(file_name=file_name, mime_type=mime_type):
                presign = await self._presign(file_name=file_name, mime_type=mime_type)
                self.assertTrue(presign["fileKey"].startswith("condition/"), presign["fileKey"])
                self.assertTrue(presign["fileKey"].endswith(suffix), presign["fileKey"])
                async with TestSessionLocal() as db:
                    media = await db.get(MediaFile, UUID(presign["fileId"]))
                self.assertEqual(media.file_key, presign["fileKey"])
                self.assertEqual(media.original_name, file_name)

    def test_build_file_key_without_mime_keeps_only_allowed_extension(self):
        file_id = uuid4()
        self.assertTrue(build_file_key("product_cover", file_id, "cover.PNG").endswith(f"{file_id}-cover.png"))
        self.assertTrue(build_file_key("product_cover", file_id, "cover.jpeg").endswith("-cover.jpg"))
        # Документ или неизвестное расширение у вида с картинками — .jpg:
        # что под ним растр, проверит PUT.
        self.assertTrue(build_file_key("product_cover", file_id, "cover.svg").endswith("-cover.jpg"))
        self.assertTrue(build_file_key("product_cover", file_id, "cover.pdf").endswith("-cover.jpg"))
        self.assertTrue(build_file_key("product_gallery", file_id, "photo").endswith("-photo.jpg"))
        self.assertTrue(build_file_key("incident_attachment", file_id, "act.pdf").endswith("-act.pdf"))
        self.assertTrue(build_file_key("rental_idea_photo", file_id, "idea.gif").endswith("-idea.gif"))
        # Объявленный MIME вне таблицы расширений — только как octet-stream.
        self.assertTrue(
            build_file_key("incident_attachment", file_id, "x.html", mime_type="text/html").endswith("-x.bin")
        )
        # Имя из одних точек и слэшей не ломает ключ.
        self.assertTrue(
            build_file_key("condition_photo_after", file_id, "../..", mime_type="image/png").endswith(
                f"{file_id}-file.png"
            )
        )

    # --- содержимое ----------------------------------------------------------

    async def test_put_rejects_svg_bytes_declared_as_png(self):
        presign = await self._presign(file_name="cell.svg")

        response = await self._put(presign, SVG_WITH_SCRIPT)

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "INVALID_FILE_CONTENT")
        self.assertFalse(self._stored_path(presign).exists())

    async def test_put_rejects_html_bytes_declared_as_jpeg(self):
        presign = await self._presign(file_name="photo.jpg", mime_type="image/jpeg", file_size=64)

        response = await self._put(presign, b"<!doctype html><script>alert(1)</script>")

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "INVALID_FILE_CONTENT")
        self.assertFalse(self._stored_path(presign).exists())

    async def test_put_accepts_real_image_signatures(self):
        cases = [
            ("shot.jpg", "image/jpeg", JPEG_HEAD),
            ("shot.webp", "image/webp", WEBP_HEAD),
            ("shot.png", "image/png", PNG_1x1),
            # Пережатый в JPEG кадр с непоправленным типом — всё ещё картинка.
            ("shot.png", "image/png", JPEG_HEAD),
        ]
        for file_name, mime_type, content in cases:
            with self.subTest(file_name=file_name, mime_type=mime_type, head=content[:4]):
                presign = await self._presign(
                    file_name=file_name, mime_type=mime_type, file_size=len(content)
                )
                response = await self._put(presign, content)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(self._stored_path(presign).read_bytes(), content)

    async def test_gif_is_accepted_only_where_the_kind_allows_it(self):
        # «Идея для аренды» — публичная форма, GIF там разрешён.
        idea = await self._presign(
            file_name="idea.gif",
            mime_type="image/gif",
            kind="rental_idea_photo",
            file_size=len(GIF_HEAD),
            headers={},
        )
        self.assertTrue(idea["fileKey"].endswith("-idea.gif"), idea["fileKey"])
        self.assertEqual((await self._put(idea, GIF_HEAD)).status_code, 200)

        # Фото возврата — только jpeg/png/webp, даже если заголовок png.
        photo = await self._presign(file_size=len(GIF_HEAD))
        response = await self._put(photo, GIF_HEAD)
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "INVALID_FILE_CONTENT")

    async def test_pdf_attachment_is_not_checked_as_image(self):
        content = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n"
        presign = await self._presign(
            file_name="act.pdf",
            mime_type="application/pdf",
            kind="incident_attachment",
            file_size=len(content),
        )
        self.assertTrue(presign["fileKey"].endswith("-act.pdf"), presign["fileKey"])

        response = await self._put(presign, content)

        self.assertEqual(response.status_code, 200, response.text)

    # --- размер --------------------------------------------------------------

    async def test_put_rejects_body_over_the_kind_limit(self):
        presign = await self._presign()
        oversized = PNG_1x1 + b"\x00" * (MAX_FILE_SIZE_IMAGE - len(PNG_1x1) + 1)

        response = await self._put(presign, oversized)

        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(response.json()["detail"], "FILE_TOO_LARGE")
        self.assertFalse(self._stored_path(presign).exists())

    async def test_put_rejects_streamed_body_without_content_length(self):
        presign = await self._presign()
        limit = 256

        async def chunks():
            yield PNG_1x1
            for _ in range(10):
                yield b"\x00" * 64

        with patch("backend.routers.uploads.max_size_for_kind", return_value=limit):
            request = self.client.build_request(
                "PUT", presign["uploadUrl"], headers=presign["headers"], content=chunks()
            )
            self.assertNotIn("content-length", {k.lower() for k in request.headers.keys()})
            response = await self.client.send(request)

        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(response.json()["detail"], "FILE_TOO_LARGE")
        self.assertFalse(self._stored_path(presign).exists())

    async def test_body_exactly_at_the_limit_is_stored(self):
        presign = await self._presign()
        content = PNG_1x1 + b"\x00" * 16

        with patch("backend.routers.uploads.max_size_for_kind", return_value=len(content)):
            response = await self._put(presign, content)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._stored_path(presign).read_bytes(), content)

    # --- перезапись ---------------------------------------------------------------

    async def test_put_refuses_to_overwrite_file_attached_to_a_report(self):
        presign = await self._presign()
        self.assertEqual((await self._put(presign, PNG_1x1)).status_code, 200)
        # До прикрепления повтор PUT (ретрай на плохой сети) разрешён.
        self.assertEqual((await self._put(presign, PNG_1x1)).status_code, 200)

        async with TestSessionLocal() as db:
            category = ProductCategory(name="Cat", slug=f"cat-{uuid4().hex[:6]}", is_active=True, sort_order=0)
            db.add(category)
            await db.flush()
            product = Product(category_id=category.id, name="Пылесос", slug=f"p-{uuid4().hex[:6]}", is_active=True)
            db.add(product)
            await db.flush()
            unit = InventoryUnit(product_id=product.id, status=InventoryStatus.AWAITING_CONFIRMATION)
            db.add(unit)
            await db.flush()
            report = ConditionReport(
                inventory_unit_id=unit.id,
                report_type=ConditionReportType.AFTER_RETURN,
                created_by_user_id=self.user_id,
            )
            db.add(report)
            await db.flush()
            db.add(
                ConditionReportPhoto(
                    condition_report_id=report.id,
                    file_id=UUID(presign["fileId"]),
                    sort_order=0,
                )
            )
            await db.commit()

        swapped = PNG_1x1 + b"swapped"
        response = await self._put(presign, swapped)

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"], "MEDIA_FILE_LOCKED")
        self.assertEqual(self._stored_path(presign).read_bytes(), PNG_1x1)

    # --- владелец -----------------------------------------------------------

    async def test_client_presign_keeps_user_id_for_account_linked_to_admin_user(self):
        admin_user_id = uuid4()
        async with TestSessionLocal() as db:
            db.add(
                AdminUser(
                    id=admin_user_id,
                    user_id=self.user_id,
                    email="operator@example.test",
                    password_hash="x",
                    full_name="Оператор",
                )
            )
            await db.commit()

        presign = await self._presign()

        async with TestSessionLocal() as db:
            media = await db.get(MediaFile, UUID(presign["fileId"]))
        self.assertEqual(media.uploaded_by_user_id, self.user_id)
        self.assertEqual(media.uploaded_by_admin_id, admin_user_id)

    async def test_client_presign_without_admin_link_has_no_admin_id(self):
        presign = await self._presign()

        async with TestSessionLocal() as db:
            media = await db.get(MediaFile, UUID(presign["fileId"]))
        self.assertEqual(media.uploaded_by_user_id, self.user_id)
        self.assertIsNone(media.uploaded_by_admin_id)

    # --- админка: обложка товара через тот же PUT ------------------------------

    async def test_admin_product_cover_upload_goes_through_the_same_put(self):
        login = await self.client.post(
            "/api/admin/auth/login",
            json={"login": "catalog-admin", "password": "admin123"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        admin_headers = {"Authorization": f"Bearer {login.json()['data']['accessToken']}"}

        cover = await self._presign(
            file_name="cover.png",
            kind="product_cover",
            headers=admin_headers,
            url="/api/admin/uploads/presign",
        )
        self.assertTrue(cover["fileKey"].startswith("product/"), cover["fileKey"])
        self.assertTrue(cover["fileKey"].endswith("-cover.png"), cover["fileKey"])
        response = await self._put(cover, PNG_1x1)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._stored_path(cover).read_bytes(), PNG_1x1)

        forged = await self._presign(
            file_name="cover.svg",
            kind="product_gallery",
            headers=admin_headers,
            url="/api/admin/uploads/presign",
        )
        self.assertFalse(forged["fileKey"].endswith(".svg"), forged["fileKey"])
        response = await self._put(forged, SVG_WITH_SCRIPT)
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "INVALID_FILE_CONTENT")

        # Расширение ключа в админке тоже берётся из MIME, а не из имени файла.
        renamed = await self._presign(
            file_name="cover.jpg",
            mime_type="image/png",
            kind="product_cover",
            headers=admin_headers,
            url="/api/admin/uploads/presign",
        )
        self.assertTrue(renamed["fileKey"].endswith("-cover.png"), renamed["fileKey"])


if __name__ == "__main__":
    unittest.main()
