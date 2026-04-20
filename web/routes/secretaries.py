from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse(url="/secretaries", status_code=302)


@router.get("/secretaries", response_class=HTMLResponse)
async def list_secretaries(request: Request):
    svc = request.app.state.service
    templates = request.app.state.templates
    stats = await svc.get_stats()
    secretaries = await svc.list_secretaries()
    return templates.TemplateResponse(
        "secretaries.html",
        {"request": request, "active": "secretaries", "stats": stats, "secretaries": secretaries},
    )


@router.post("/secretaries", response_class=HTMLResponse)
async def create_secretary(
    request: Request,
    name: str = Form(...),
    token: str = Form(...),
    chat_id: str = Form(...),
    tools_enabled: str = Form(default=""),
):
    svc = request.app.state.service
    templates = request.app.state.templates
    emp_id = await svc.create_secretary(
        name=name,
        token=token,
        chat_id=chat_id,
        tools_enabled=bool(tools_enabled),
    )
    row = {"id": emp_id, "name": name, "telegram_chat_id": chat_id,
           "is_active": True, "msgs_today": 0}
    return templates.TemplateResponse(
        "partials/secretary_row.html",
        {"request": request, "s": row},
        status_code=200,
    )


@router.delete("/secretaries/{employee_id}", response_class=HTMLResponse)
async def deactivate_secretary(request: Request, employee_id: str):
    svc = request.app.state.service
    await svc.deactivate_secretary(employee_id)
    return HTMLResponse("")
