from contextlib import asynccontextmanager
import asyncio
import os
from pathlib import Path
import subprocess

import asyncpg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web.db import create_admin_pool
from web.service import WebAdminService
from web.routes import secretaries, messages, stats, documents


@asynccontextmanager
async def lifespan(app: FastAPI):
    import redis.asyncio as aioredis
    from shared.crypto import CredentialStore

    dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]
    fernet_key = os.environ["FERNET_KEY"].encode()

    pool = await create_admin_pool(dsn)
    redis = aioredis.from_url(redis_url, decode_responses=True)
    store = CredentialStore(fernet_key)

    service = WebAdminService(pool=pool, redis=redis, credential_store=store)

    app.state.service = service
    app.state.templates = Jinja2Templates(
        directory=str(Path(__file__).parent / "templates")
    )

    yield

    await pool.close()
    await redis.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="SV Admin", lifespan=lifespan)

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(secretaries.router)
    app.include_router(messages.router)
    app.include_router(stats.router)
    app.include_router(documents.router)

    @app.get("/metrics")
    async def metrics():
        import psutil
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()

        def _nvidia():
            try:
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=memory.used,memory.total",
                     "--format=csv,noheader,nounits"],
                    timeout=3, stderr=subprocess.DEVNULL,
                )
                used, total = out.decode().strip().split(",")
                return {"vram_used_mb": int(used.strip()), "vram_total_mb": int(total.strip())}
            except Exception:
                return {"vram_used_mb": None, "vram_total_mb": None}

        vram = await asyncio.to_thread(_nvidia)
        return JSONResponse({
            "cpu_percent": cpu,
            "ram_used_gb": round(mem.used / 1024**3, 2),
            "ram_total_gb": round(mem.total / 1024**3, 2),
            **vram,
        })

    @app.get("/api/stats")
    async def api_stats(request: Request):
        svc = getattr(request.app.state, "service", None)
        if svc is None:
            return JSONResponse({"error": "unavailable"}, status_code=503)
        row = await svc.get_stats()
        return JSONResponse({
            "secretaries_total": row.secretaries_total,
            "secretaries_active": row.secretaries_active,
            "msgs_today": row.msgs_today,
            "shared_docs": row.shared_docs,
            "vault_notes": row.vault_notes,
        })

    @app.get("/api/secretaries")
    async def api_secretaries(request: Request):
        svc = getattr(request.app.state, "service", None)
        if svc is None:
            return JSONResponse({"error": "unavailable"}, status_code=503)
        rows = await svc.list_secretaries()
        return JSONResponse([
            {
                "id": r.id,
                "name": r.name,
                "is_active": r.is_active,
                "msgs_today": r.msgs_today,
            }
            for r in rows
        ])

    @app.get("/health")
    async def health(request: Request):
        checks: dict[str, str] = {}
        ok = True

        svc = getattr(request.app.state, "service", None)
        if svc is None:
            checks["db"] = "unavailable"
            checks["redis"] = "unavailable"
            checks["status"] = "unavailable"
            return JSONResponse(content=checks, status_code=503)

        try:
            await svc._pool.fetchval("SELECT 1")
            checks["db"] = "ok"
        except Exception:
            checks["db"] = "error"
            ok = False

        try:
            await svc._redis.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "error"
            ok = False

        checks["status"] = "ok" if ok else "degraded"
        return JSONResponse(content=checks, status_code=200 if ok else 503)

    return app


app = create_app()
