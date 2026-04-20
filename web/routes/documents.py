from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/documents", response_class=HTMLResponse)
async def documents_page(request: Request):
    svc = request.app.state.service
    templates = request.app.state.templates
    docs = await svc.list_shared_docs()
    return templates.TemplateResponse(
        request,
        "documents.html",
        {"active": "documents", "docs": docs},
    )
