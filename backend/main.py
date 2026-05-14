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
from backend.routers.admin.lockers import router as admin_lockers_router
from backend.routers.admin.product_categories import router as admin_product_categories_router
from backend.routers.admin.product_filters import router as admin_product_filters_router
from backend.routers.admin.products import router as admin_products_router
from backend.routers.admin.rentals import router as admin_rentals_router
from backend.routers.admin.uploads import router as admin_uploads_router
from backend.routers.admin.users import router as admin_users_router
from backend.routers.admin.verification_queue import router as admin_verification_queue_router
from backend.routers.auth import router as auth_router
from backend.routers.me import router as me_router
from backend.routers.cities import router as cities_router
from backend.routers.lockers import router as lockers_router
from backend.routers.uploads import router as uploads_router
from backend.routers.products import router as products_router
from backend.routers.reservation import router as reservation_router
from backend.routers.payments import router as payments_router, yookassa_webhook_router
from backend.routers.webhooks_esi import router as webhooks_esi_router
from backend.utils.featured_product import (
    start_featured_product_scheduler,
    stop_featured_product_scheduler,
)
from backend.utils.reservation_expiry import (
    start_reservation_expiry_scheduler,
    stop_reservation_expiry_scheduler,
)
from backend.utils.rental_pickup_expiry import (
    start_rental_pickup_expiry_scheduler,
    stop_rental_pickup_expiry_scheduler,
)


app = FastAPI()
featured_product_worker: threading.Thread | None = None
featured_product_stop_event: threading.Event | None = None
reservation_expiry_worker: threading.Thread | None = None
reservation_expiry_stop_event: threading.Event | None = None
rental_pickup_expiry_worker: threading.Thread | None = None
rental_pickup_expiry_stop_event: threading.Event | None = None

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
app.include_router(webhooks_esi_router)
app.include_router(admin_auth_router)
app.include_router(admin_dashboard_router)
app.include_router(admin_users_router)
app.include_router(admin_verification_queue_router)
app.include_router(admin_cities_router)
app.include_router(admin_lockers_router)
app.include_router(admin_rentals_router)
app.include_router(admin_audit_router)
app.include_router(admin_product_categories_router)
app.include_router(admin_product_filters_router)
app.include_router(admin_products_router)
app.include_router(admin_uploads_router)

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
    await init_db()
    await init_redis()
    loop = asyncio.get_running_loop()
    featured_product_worker, featured_product_stop_event = start_featured_product_scheduler(loop)
    reservation_expiry_worker, reservation_expiry_stop_event = start_reservation_expiry_scheduler(loop)
    rental_pickup_expiry_worker, rental_pickup_expiry_stop_event = start_rental_pickup_expiry_scheduler(loop)

@app.on_event("shutdown")
async def shutdown_event():
    global featured_product_worker, featured_product_stop_event
    global reservation_expiry_worker, reservation_expiry_stop_event
    global rental_pickup_expiry_worker, rental_pickup_expiry_stop_event
    await stop_featured_product_scheduler(featured_product_worker, featured_product_stop_event)
    featured_product_worker = None
    featured_product_stop_event = None
    await stop_reservation_expiry_scheduler(reservation_expiry_worker, reservation_expiry_stop_event)
    reservation_expiry_worker = None
    reservation_expiry_stop_event = None
    await stop_rental_pickup_expiry_scheduler(rental_pickup_expiry_worker, rental_pickup_expiry_stop_event)
    rental_pickup_expiry_worker = None
    rental_pickup_expiry_stop_event = None
    await close_redis()
    await close_db()

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
