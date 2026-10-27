import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from app.api import account, admin_catalog, auth, catalog, payments, shop, staff
from app.core.config import settings
from app.db.session import engine

settings.assert_production_safe()
log = logging.getLogger("quantumstore")

app = FastAPI(title=f"{settings.app_name} API", version="0.1.0",
              docs_url=None if settings.is_production else "/docs",
              redoc_url=None, openapi_url=None if settings.is_production else "/openapi.json")

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    if settings.is_production:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Error no controlado en %s %s", request.method, request.url.path)  # traza solo en logs
    return JSONResponse({"detail": "Error interno del servidor"}, status_code=500)


@app.get("/health", tags=["system"])
def health():
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(account.router)
app.include_router(staff.router)
app.include_router(catalog.router)
app.include_router(admin_catalog.router)
app.include_router(shop.router)
app.include_router(payments.router)
