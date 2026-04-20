from contextlib import asynccontextmanager
import os

import asyncpg
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web.db import create_admin_pool
from web.service import WebAdminService
from web.routes import secretaries, messages, stats, documents

_pool: asyncpg.Pool | None = None
_service: WebAdminService | None = None


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
        directory=str(__import__("pathlib").Path(__file__).parent / "templates")
    )

    yield

    await pool.close()
    await redis.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="SV Admin", lifespan=lifespan)

    static_dir = str(__import__("pathlib").Path(__file__).parent / "static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    app.include_router(secretaries.router)
    app.include_router(messages.router)
    app.include_router(stats.router)
    app.include_router(documents.router)

    return app


app = create_app()
