from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def _parse_servers() -> list[dict]:
    raw = os.environ.get("SERVERS", "")
    servers = []
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(",", 1)
        if len(parts) == 2:
            servers.append({"name": parts[0].strip(), "url": parts[1].strip()})
    return servers


async def fetch_server(client: httpx.AsyncClient, server: dict) -> dict:
    base = server["url"].rstrip("/")
    name = server["name"]

    async def _get(path: str):
        try:
            r = await client.get(f"{base}{path}", timeout=5.0)
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    health, metrics, stats, secretaries = await asyncio.gather(
        _get("/health"),
        _get("/metrics"),
        _get("/api/stats"),
        _get("/api/secretaries"),
        return_exceptions=True,
    )

    def _safe(v):
        return v if isinstance(v, dict) else None

    def _safe_list(v):
        return v if isinstance(v, list) else []

    health = _safe(health)
    metrics = _safe(metrics)
    stats = _safe(stats)
    secretaries = _safe_list(secretaries)

    online = health is not None
    return {
        "name": name,
        "url": base,
        "online": online,
        "db": health.get("db") if health else "—",
        "redis": health.get("redis") if health else "—",
        "cpu_percent": metrics.get("cpu_percent") if metrics else None,
        "ram_used_gb": metrics.get("ram_used_gb") if metrics else None,
        "ram_total_gb": metrics.get("ram_total_gb") if metrics else None,
        "vram_used_mb": metrics.get("vram_used_mb") if metrics else None,
        "vram_total_mb": metrics.get("vram_total_mb") if metrics else None,
        "secretaries_total": stats.get("secretaries_total") if stats else None,
        "secretaries_active": stats.get("secretaries_active") if stats else None,
        "msgs_today": stats.get("msgs_today") if stats else None,
        "secretaries": secretaries,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = httpx.AsyncClient()
    app.state.client = client
    app.state.servers = _parse_servers()
    app.state.templates = Jinja2Templates(
        directory=str(Path(__file__).parent / "templates")
    )
    yield
    await client.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="SV Central", lifespan=lifespan)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        servers_data = await asyncio.gather(
            *[fetch_server(request.app.state.client, s) for s in request.app.state.servers],
            return_exceptions=True,
        )
        servers = [s if isinstance(s, dict) else {"name": "?", "online": False} for s in servers_data]
        return request.app.state.templates.TemplateResponse(
            name="dashboard.html", context={"request": request, "servers": servers}
        )

    @app.get("/partial", response_class=HTMLResponse)
    async def partial(request: Request):
        servers_data = await asyncio.gather(
            *[fetch_server(request.app.state.client, s) for s in request.app.state.servers],
            return_exceptions=True,
        )
        servers = [s if isinstance(s, dict) else {"name": "?", "online": False} for s in servers_data]
        return request.app.state.templates.TemplateResponse(
            name="partials/server_grid.html", context={"request": request, "servers": servers}
        )

    return app


app = create_app()
