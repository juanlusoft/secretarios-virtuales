import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from web.routes import secretaries, messages, stats, documents
from web.service import WebAdminService, SecretaryRow, StatsRow


def make_service() -> WebAdminService:
    svc = MagicMock(spec=WebAdminService)
    svc.get_stats = AsyncMock(return_value=StatsRow(
        secretaries_total=3, secretaries_active=2, msgs_today=847,
        shared_docs=12, vault_notes=38,
    ))
    svc.list_secretaries = AsyncMock(return_value=[
        SecretaryRow(id=str(uuid4()), name="María", telegram_chat_id="987654321",
                     is_active=True, msgs_today=234),
        SecretaryRow(id=str(uuid4()), name="Carlos", telegram_chat_id="555000111",
                     is_active=False, msgs_today=0),
    ])
    svc.create_secretary = AsyncMock(return_value=str(uuid4()))
    svc.deactivate_secretary = AsyncMock()
    svc.send_message = AsyncMock()
    svc.list_shared_docs = AsyncMock(return_value=[
        {"vault_path": "shared/doc.md", "title": "Protocolo", "modified_at": "2026-04-01"},
    ])
    return svc


def make_test_app(svc, templates):
    app = FastAPI()
    static_dir = Path(__file__).parent.parent.parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(secretaries.router)
    app.include_router(messages.router)
    app.include_router(stats.router)
    app.include_router(documents.router)
    app.state.service = svc
    app.state.templates = templates
    return app


@pytest.fixture
def client():
    svc = make_service()
    templates_dir = Path(__file__).parent.parent.parent / "web" / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))
    app = make_test_app(svc, templates)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c, svc


def test_secretaries_page_renders(client):
    c, _ = client
    resp = c.get("/secretaries")
    assert resp.status_code == 200
    assert "María" in resp.text
    assert "Carlos" in resp.text
    assert "847" in resp.text


def test_create_secretary_returns_row(client):
    c, svc = client
    resp = c.post("/secretaries", data={
        "name": "Ana", "token": "bot:TOKEN", "chat_id": "111", "tools_enabled": ""
    })
    assert resp.status_code == 200
    svc.create_secretary.assert_called_once_with(
        name="Ana", token="bot:TOKEN", chat_id="111", tools_enabled=False
    )


def test_deactivate_secretary(client):
    c, svc = client
    emp_id = str(uuid4())
    resp = c.delete(f"/secretaries/{emp_id}")
    assert resp.status_code == 200
    svc.deactivate_secretary.assert_called_once_with(emp_id)


def test_messages_page_renders(client):
    c, _ = client
    resp = c.get("/messages")
    assert resp.status_code == 200
    assert "Enviar" in resp.text


def test_send_message_broadcast(client):
    c, svc = client
    svc.list_secretaries = AsyncMock(return_value=[
        SecretaryRow(id="id-1", name="María", telegram_chat_id="1", is_active=True, msgs_today=0),
        SecretaryRow(id="id-2", name="Pedro", telegram_chat_id="2", is_active=True, msgs_today=0),
    ])
    resp = c.post("/messages/send", data={"broadcast": "on", "text": "Hola"})
    assert resp.status_code == 200
    assert svc.send_message.call_count == 1
    call_ids = svc.send_message.call_args[1]["employee_ids"]
    assert set(call_ids) == {"id-1", "id-2"}


def test_documents_page_renders(client):
    c, _ = client
    resp = c.get("/documents")
    assert resp.status_code == 200
    assert "Protocolo" in resp.text


def test_stats_page_renders(client):
    c, _ = client
    resp = c.get("/stats")
    assert resp.status_code == 200
    assert "847" in resp.text
