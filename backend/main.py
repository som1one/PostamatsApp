import sys
from pathlib import Path
import uvicorn

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.core.database import close_db, init_db
from backend.routers.admin.audit import router as admin_audit_router
from backend.routers.admin.auth import router as admin_auth_router
from backend.routers.admin.cities import router as admin_cities_router
from backend.routers.admin.dashboard import router as admin_dashboard_router
from backend.routers.admin.lockers import router as admin_lockers_router
from backend.routers.admin.product_categories import router as admin_product_categories_router
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


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
app.include_router(admin_products_router)
app.include_router(admin_uploads_router)

admin_frontend_dir = ROOT_DIR / "admin"
if admin_frontend_dir.exists():
    app.mount("/admin", StaticFiles(directory=admin_frontend_dir, html=True), name="admin")

@app.on_event("startup")
async def startup_event():
    await init_db()

@app.on_event("shutdown")
async def shutdown_event():
    await close_db()

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
