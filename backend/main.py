import asyncio
import sys
import threading
from pathlib import Path
import uvicorn

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.core.database import close_db, init_db
from backend.core.redis import close_redis, init_redis
from backend.core.settings import settings
from backend.routers.admin.audit import router as admin_audit_router
from backend.routers.admin.auth import router as admin_auth_router
from backend.routers.admin.cities import router as admin_cities_router
from backend.routers.admin.dashboard import router as admin_dashboard_router
from backend.routers.admin.inventory import router as admin_inventory_router
from backend.routers.admin.lockers import router as admin_lockers_router
from backend.routers.admin.product_categories import router as admin_product_categories_router
from backend.routers.admin.product_filters import router as admin_product_filters_router
from backend.routers.admin.products import router as admin_products_router
from backend.routers.admin.rentals import router as admin_rentals_router
from backend.routers.admin.rental_ideas import router as admin_rental_ideas_router
from backend.routers.admin.telegram_subscribers import router as admin_telegram_subscribers_router
from backend.routers.admin.uploads import router as admin_uploads_router
from backend.routers.admin.users import router as admin_users_router
from backend.routers.admin.verification_queue import router as admin_verification_queue_router
from backend.routers.admin.support import router as admin_support_router
from backend.routers.auth import router as auth_router
from backend.routers.me import router as me_router
from backend.routers.support import router as support_router
from backend.realtime.chat_gateway import router as support_ws_router
from backend.realtime.connection_hub import get_connection_hub
from backend.routers.cities import router as cities_router
from backend.routers.lockers import router as lockers_router
from backend.routers.uploads import router as uploads_router
from backend.routers.products import router as products_router
from backend.routers.reservation import router as reservation_router
from backend.routers.payments import router as payments_router, yookassa_webhook_router
from backend.routers.public_stats import router as public_stats_router
from backend.routers.rental_ideas import router as rental_ideas_router
from backend.routers.telegram_webhook import router as telegram_webhook_router
from backend.routers.webhooks_esi import router as webhooks_esi_router
from backend.utils.featured_product import (
    start_featured_product_scheduler,
    stop_featured_product_scheduler,
)
from backend.utils.esi_reconcile import (
    start_esi_reconcile_scheduler,
    stop_esi_reconcile_scheduler,
)
from backend.utils.reservation_expiry import (
    start_reservation_expiry_scheduler,
    stop_reservation_expiry_scheduler,
)
from backend.utils.rental_pickup_expiry import (
    start_rental_pickup_expiry_scheduler,
    stop_rental_pickup_expiry_scheduler,
)
from backend.utils.rental_overdue import (
    start_rental_overdue_scheduler,
    stop_rental_overdue_scheduler,
)
from backend.utils.rental_auto_pickup import (
    start_rental_auto_pickup_scheduler,
    stop_rental_auto_pickup_scheduler,
)


app = FastAPI()
featured_product_worker: threading.Thread | None = None
featured_product_stop_event: threading.Event | None = None
reservation_expiry_worker: threading.Thread | None = None
reservation_expiry_stop_event: threading.Event | None = None
rental_pickup_expiry_worker: threading.Thread | None = None
rental_pickup_expiry_stop_event: threading.Event | None = None
rental_overdue_worker_handle: threading.Thread | None = None
rental_overdue_stop_event: threading.Event | None = None
esi_reconcile_worker: threading.Thread | None = None
esi_reconcile_stop_event: threading.Event | None = None
rental_auto_pickup_worker_handle: threading.Thread | None = None
rental_auto_pickup_stop_event: threading.Event | None = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(me_router)
app.include_router(cities_router)
app.include_router(lockers_router)
app.include_router(uploads_router)
app.include_router(products_router)
app.include_router(reservation_router)
app.include_router(payments_router)
app.include_router(yookassa_webhook_router)
app.include_router(public_stats_router)
app.include_router(rental_ideas_router)
app.include_router(telegram_webhook_router)
app.include_router(webhooks_esi_router)
app.include_router(admin_auth_router)
app.include_router(admin_dashboard_router)
app.include_router(admin_users_router)
app.include_router(admin_verification_queue_router)
app.include_router(admin_cities_router)
app.include_router(admin_lockers_router)
app.include_router(admin_inventory_router)
app.include_router(admin_rentals_router)
app.include_router(admin_rental_ideas_router)
app.include_router(admin_telegram_subscribers_router)
app.include_router(admin_audit_router)
app.include_router(admin_product_categories_router)
app.include_router(admin_product_filters_router)
app.include_router(admin_products_router)
app.include_router(admin_uploads_router)
app.include_router(admin_support_router)

# Client support chat REST + the WebSocket gateway (client + operator sockets).
app.include_router(support_router)
app.include_router(support_ws_router)

admin_frontend_dir = ROOT_DIR / "admin"
assets_dir = ROOT_DIR / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
if admin_frontend_dir.exists():
    app.mount("/admin", StaticFiles(directory=admin_frontend_dir, html=True), name="admin")

@app.on_event("startup")
async def startup_event():
    global featured_product_worker, featured_product_stop_event
    global reservation_expiry_worker, reservation_expiry_stop_event
    global rental_pickup_expiry_worker, rental_pickup_expiry_stop_event
    global rental_overdue_worker_handle, rental_overdue_stop_event
    global esi_reconcile_worker, esi_reconcile_stop_event
    global rental_auto_pickup_worker_handle, rental_auto_pickup_stop_event
    await init_db()
    await init_redis()
    # Сидируем дефолтных Telegram-подписчиков (пока что один som1ones).
    try:
        from backend.core.database import SessionLocal
        from backend.utils.telegram_admin_subscribers import (
            ensure_default_subscribers,
        )
        from backend.utils.seed_support import ensure_support_operator

        async with SessionLocal() as db:
            await ensure_default_subscribers(db)
            await ensure_support_operator(db)
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "failed to seed default telegram subscribers"
        )
    loop = asyncio.get_running_loop()
    featured_product_worker, featured_product_stop_event = start_featured_product_scheduler(loop)
    reservation_expiry_worker, reservation_expiry_stop_event = start_reservation_expiry_scheduler(loop)
    rental_pickup_expiry_worker, rental_pickup_expiry_stop_event = start_rental_pickup_expiry_scheduler(loop)
    rental_overdue_worker_handle, rental_overdue_stop_event = start_rental_overdue_scheduler(loop)
    esi_reconcile_worker, esi_reconcile_stop_event = start_esi_reconcile_scheduler(loop)
    rental_auto_pickup_worker_handle, rental_auto_pickup_stop_event = start_rental_auto_pickup_scheduler(loop)
    # Start the per-worker support-chat Redis subscriber for cross-worker fan-out.
    get_connection_hub().start()

@app.on_event("shutdown")
async def shutdown_event():
    global featured_product_worker, featured_product_stop_event
    global reservation_expiry_worker, reservation_expiry_stop_event
    global rental_pickup_expiry_worker, rental_pickup_expiry_stop_event
    global rental_overdue_worker_handle, rental_overdue_stop_event
    global esi_reconcile_worker, esi_reconcile_stop_event
    global rental_auto_pickup_worker_handle, rental_auto_pickup_stop_event
    await stop_featured_product_scheduler(featured_product_worker, featured_product_stop_event)
    featured_product_worker = None
    featured_product_stop_event = None
    await stop_reservation_expiry_scheduler(reservation_expiry_worker, reservation_expiry_stop_event)
    reservation_expiry_worker = None
    reservation_expiry_stop_event = None
    await stop_rental_pickup_expiry_scheduler(rental_pickup_expiry_worker, rental_pickup_expiry_stop_event)
    rental_pickup_expiry_worker = None
    rental_pickup_expiry_stop_event = None
    await stop_rental_overdue_scheduler(rental_overdue_worker_handle, rental_overdue_stop_event)
    rental_overdue_worker_handle = None
    rental_overdue_stop_event = None
    await stop_esi_reconcile_scheduler(esi_reconcile_worker, esi_reconcile_stop_event)
    esi_reconcile_worker = None
    esi_reconcile_stop_event = None
    await stop_rental_auto_pickup_scheduler(rental_auto_pickup_worker_handle, rental_auto_pickup_stop_event)
    rental_auto_pickup_worker_handle = None
    rental_auto_pickup_stop_event = None
    # Stop the support-chat Redis subscriber before tearing down Redis.
    await get_connection_hub().stop()
    await close_redis()
    await close_db()

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
