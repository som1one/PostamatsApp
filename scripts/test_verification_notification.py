"""Ручной тест: пройти авторизацию и создать заявку на верификацию,
чтобы проверить, что в Telegram-бот приходит уведомление.

Скрипт самодостаточный (нужен только ``httpx``), бьёт по реальному API
(локальному или прод) и проходит весь путь:

    1. POST /auth/request-code  — запрос кода (SMS или звонок).
    2. Ввод кода руками          — берём из SMS / входящего звонка.
    3. POST /auth/confirm-code   — получаем accessToken.
    4. PATCH /me (имя/фамилия)   — чтобы в уведомлении было осмысленное имя.
    5. presign + upload          — грузим тестовое фото (front + selfie).
    6. POST /me/verification     — создаём заявку → backend шлёт уведомление
                                   подписчикам Telegram-бота.

Использование:

    python scripts/test_verification_notification.py \\
        --base-url https://api.naprokatberu.ru \\
        --phone +79991234567

Локально:

    python scripts/test_verification_notification.py \\
        --base-url http://127.0.0.1:8000 --phone +79991234567

Флаги:
    --dev-login   использовать /auth/dev-login вместо SMS (только если на
                  сервере DEBUG=true) — код вводить не нужно.
    --doc-number  номер документа (по умолчанию случайный, чтобы не ловить
                  DOCUMENT_NUMBER_ALREADY_EXISTS).

Важно: заявка реально создаётся в БД того окружения, по которому бьём.
На проде это создаст настоящую запись в очереди верификации.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date

try:
    import httpx
except ImportError:
    print("Нужен httpx: pip install httpx")
    sys.exit(1)


# Минимальный валидный PNG 1x1 (тот же, что в backend/tests).
PNG_1x1 = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108020000009077"
    "53DE0000000C4944415478DA63F8FFFFFFFFFFFFFF1F00080100FFFFFFFF"
    "0007FBFFFEEFEC0000000049454E44AE426082"
)


def _data(resp: httpx.Response) -> dict:
    try:
        body = resp.json()
    except ValueError:
        return {}
    return body.get("data", body) if isinstance(body, dict) else {}


def _fail(step: str, resp: httpx.Response) -> None:
    print(f"[FAIL] {step}: HTTP {resp.status_code} {resp.text[:300]}")
    sys.exit(1)


def request_code(client: httpx.Client, base: str, phone: str) -> str:
    resp = client.post(f"{base}/auth/request-code", json={"phone": phone})
    if resp.status_code >= 400:
        _fail("request-code", resp)
    data = _data(resp)
    channel = data.get("channel")
    ttl = data.get("ttlSeconds")
    session_id = data.get("verificationSessionId")
    print(f"[OK] request-code: channel={channel} ttl={ttl}s sessionId={session_id}")
    if channel == "call":
        print("    Тебе ЗВОНИТ робот — код это последние 4 цифры входящего номера.")
    else:
        print("    Код отправлен в SMS.")
    return str(session_id)


def confirm_code(client: httpx.Client, base: str, session_id: str, code: str) -> str:
    resp = client.post(
        f"{base}/auth/confirm-code",
        json={"verificationSessionId": session_id, "code": code},
    )
    if resp.status_code >= 400:
        _fail("confirm-code", resp)
    token = _data(resp).get("accessToken")
    print(f"[OK] confirm-code: получили accessToken ({str(token)[:12]}…)")
    return str(token)


def dev_login(client: httpx.Client, base: str, phone: str) -> str:
    resp = client.post(f"{base}/auth/dev-login", json={"phone": phone})
    if resp.status_code >= 400:
        _fail("dev-login (нужен DEBUG=true на сервере)", resp)
    token = _data(resp).get("accessToken")
    print(f"[OK] dev-login: получили accessToken ({str(token)[:12]}…)")
    return str(token)


def patch_me(client: httpx.Client, base: str, token: str) -> None:
    resp = client.patch(
        f"{base}/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"firstName": "Тест", "lastName": "Бот-Проверка"},
    )
    if resp.status_code >= 400:
        # не критично для уведомления, просто предупредим
        print(f"[WARN] PATCH /me: HTTP {resp.status_code} {resp.text[:200]}")
        return
    print("[OK] PATCH /me: имя обновлено")


def presign_and_upload(
    client: httpx.Client, base: str, token: str, kind: str, file_name: str
) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        f"{base}/uploads/presign",
        headers=headers,
        json={
            "fileName": file_name,
            "mimeType": "image/png",
            "fileSize": len(PNG_1x1),
            "kind": kind,
        },
    )
    if resp.status_code >= 400:
        _fail(f"presign ({kind})", resp)
    data = _data(resp)
    file_key = data["fileKey"]
    upload_url = data["uploadUrl"]
    method = (data.get("method") or "PUT").upper()
    up_headers = data.get("headers") or {"Content-Type": "image/png"}

    # uploadUrl может быть относительным (filesystem storage) — дополняем base.
    if upload_url.startswith("/"):
        upload_url = f"{base}{upload_url}"

    up = client.request(method, upload_url, content=PNG_1x1, headers=up_headers)
    if up.status_code >= 400:
        _fail(f"upload ({kind})", up)
    print(f"[OK] upload {kind}: fileKey={file_key}")
    return file_key


def create_verification(
    client: httpx.Client,
    base: str,
    token: str,
    front_key: str,
    selfie_key: str,
    doc_number: str,
) -> None:
    resp = client.post(
        f"{base}/me/verification",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "firstName": "Тест",
            "lastName": "Бот-Проверка",
            "birthDate": "1990-01-01",
            "documentType": "passport_rf",
            "documentNumber": doc_number,
            "documentIssueDate": date.today().isoformat(),
            "files": [
                {"fileKey": front_key, "kind": "document_front"},
                {"fileKey": selfie_key, "kind": "selfie"},
            ],
        },
    )
    if resp.status_code >= 400:
        _fail("POST /me/verification", resp)
    status = _data(resp).get("verification", {}).get("status")
    print(f"[OK] POST /me/verification: статус={status}")
    print()
    print("=== Заявка создана. Уведомление должно прилететь в Telegram-бот. ===")
    print("Если бот молчит — проверь в админке раздел «Уведомления»:")
    print("  • есть включённый подписчик со статусом «Связан» (нажат /start);")
    print("  • нажата кнопка «Включить /start» (webhook зарегистрирован).")


def main() -> int:
    parser = argparse.ArgumentParser(description="Test verification -> Telegram notification")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--phone", required=True, help="Телефон в формате +7XXXXXXXXXX")
    parser.add_argument("--dev-login", action="store_true", help="использовать /auth/dev-login (DEBUG=true)")
    parser.add_argument("--doc-number", default=None, help="номер документа (по умолчанию случайный)")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    doc_number = args.doc_number or f"TEST{uuid.uuid4().hex[:8].upper()}"

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        if args.dev_login:
            token = dev_login(client, base, args.phone)
        else:
            session_id = request_code(client, base, args.phone)
            code = input("Введи код из SMS/звонка (4 цифры): ").strip()
            token = confirm_code(client, base, session_id, code)

        patch_me(client, base, token)
        front_key = presign_and_upload(client, base, token, "verification_front", "front.png")
        selfie_key = presign_and_upload(client, base, token, "verification_selfie", "selfie.png")
        create_verification(client, base, token, front_key, selfie_key, doc_number)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
