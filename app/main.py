import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import config
from app.db import Base, SessionLocal, engine
from app.deps import AdminRequired, LoginRequired
from app.push import notifier_loop
from app.routes import admin, auth, evening, play
from app.seed import seed_if_empty

logging.basicConfig(level=logging.INFO)
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_if_empty(db)
    task = asyncio.create_task(notifier_loop()) if config.RUN_SCHEDULER else None
    yield
    if task:
        task.cancel()


app = FastAPI(title=config.APP_NAME, lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SECRET_KEY,
    max_age=60 * 60 * 24 * 365,
    same_site="lax",
    https_only=config.SECURE_COOKIES,
)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

app.include_router(auth.router)
app.include_router(play.router)
app.include_router(evening.router)
app.include_router(admin.router)


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(AdminRequired)
async def _admin_required(request: Request, exc: AdminRequired):
    return RedirectResponse("/", status_code=303)


# De service worker moet vanaf de root geserveerd worden om de hele app te beslaan
@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
async def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/health", include_in_schema=False)
async def health():
    return {"ok": True}
