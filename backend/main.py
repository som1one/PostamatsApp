import sys
from pathlib import Path
import uvicorn

from fastapi import FastAPI

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.core.database import close_db, init_db
from backend.routers.auth import router as auth_router
from backend.routers.me import router as me_router
from backend.routers.cities import router as cities_router
from backend.routers.lockers import router as lockers_router
from backend.routers.uploads import router as uploads_router
from backend.routers.products import router as products_router


app = FastAPI()

app.include_router(auth_router)
app.include_router(me_router)
app.include_router(cities_router)
app.include_router(lockers_router)
app.include_router(uploads_router)
app.include_router(products_router)

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