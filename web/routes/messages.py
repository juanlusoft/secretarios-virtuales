from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/messages", response_class=HTMLResponse)
async def messages_page(request: Request, to: str | None = None):
    svc = request.app.state.service
    templates = request.app.state.templates
    secretaries = await svc.list_secretaries()
    return templates.TemplateResponse(
        request,
        "messages.html",
        {"active": "messages", "secretaries": secretaries, "preselected": to},
    )


@router.post("/messages/send", response_class=HTMLResponse)
async def send_message(request: Request):
    svc = request.app.state.service
    form = await request.form()
    text = form.get("text", "").strip()
    broadcast = form.get("broadcast")

    if broadcast:
        secretaries = await svc.list_secretaries()
        employee_ids = [s.id for s in secretaries if s.is_active]
    else:
        employee_ids = form.getlist("recipients")

    if text and employee_ids:
        await svc.send_message(employee_ids=employee_ids, text=text)
        return HTMLResponse(
            '<div class="alert-success">✓ Mensaje enviado a '
            f'{len(employee_ids)} secretario(s)</div>'
        )
    return HTMLResponse('<div style="color:#ef4444">Selecciona al menos un destinatario y escribe un mensaje.</div>')
