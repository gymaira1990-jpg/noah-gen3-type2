"""页面路由：Dashboard / 模型库 / 专用对话页"""

from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["pages"])
TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def _html(name: str) -> HTMLResponse:
    path = TEMPLATES / name
    if not path.exists():
        return HTMLResponse(f"<h2>页面不存在: {name}</h2>", status_code=404)
    return HTMLResponse(content=path.read_text(encoding="utf-8"))


@router.get("/", response_class=HTMLResponse)
async def root():
    return _html("dashboard.html")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return _html("dashboard.html")


@router.get("/models", response_class=HTMLResponse)
async def models_page():
    return _html("models.html")


@router.get("/chat/deepseek", response_class=HTMLResponse)
async def deepseek_chat_page():
    return _html("chat_deepseek.html")


@router.get("/chat/4b", response_class=HTMLResponse)
async def local_4b_chat_page():
    return _html("chat_4b.html")
