"""诺亚核心 · Web Server
只做 uvicorn.run + 路由注册
"""

from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .kernel import load_config, CONFIG_DIR


def create_app() -> FastAPI:
    """创建 FastAPI 应用并注册所有路由"""
    app = FastAPI(title="诺亚核心", version="0.2.0")

    # 静态文件
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # 注册路由组
    from .handlers.model_routes import router as model_router
    from .handlers.system_routes import router as system_router
    from .handlers.chat_routes import router as chat_router
    from .handlers.page_routes import router as page_router

    app.include_router(model_router)
    app.include_router(system_router)
    app.include_router(chat_router)
    app.include_router(page_router)

    # DeepSeek 原生 API 路由
    from .deepseek.router import router as deepseek_router
    from .deepseek.anthropic_router import anthropic_router
    app.include_router(deepseek_router)
    app.include_router(anthropic_router)

    return app


def start_server(host: str | None = None, port: int | None = None):
    """启动 Web 面板"""
    import uvicorn
    cfg = load_config()
    host = host or cfg.server.get("host", "127.0.0.1")
    port = port or cfg.server.get("port", 8110)

    print(f"  🌐 仪表盘: http://localhost:{port}/dashboard")
    print(f"  📚 模型库:  http://localhost:{port}/models")
    print(f"  🤖 DeepSeek: http://localhost:{port}/chat/deepseek")
    print(f"  🖥️  4B 本地: http://localhost:{port}/chat/4b")
    print(f"  ⚡ API:     http://localhost:{port}/api/check")
    print(f"  🧠 DeepSeek: http://localhost:{port}/api/deepseek/chat/pro")
    print(f"     Stream:    http://localhost:{port}/api/deepseek/chat/stream/pro")
    print(f"     Anthropic: http://localhost:{port}/api/deepseek/anthropic/messages")

    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    start_server()
