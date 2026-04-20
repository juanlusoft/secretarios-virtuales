from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    svc = request.app.state.service
    templates = request.app.state.templates
    stats = await svc.get_stats()
    secretaries = await svc.list_secretaries()
    return templates.TemplateResponse(
        request,
        "stats.html",
        {"active": "stats", "stats": stats, "secretaries": secretaries},
    )
