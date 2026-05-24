#!/usr/bin/env python3
"""NOAH-PRIME · FastAPI主服务 · server.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
战锤40K主题: 铸造圣殿之门 (Forge Temple Gate)

路由:
  /                    主对话界面
  /chat                WebSocket对话
  /api/chat            HTTP对话
  /api/admin/*         管理后台API
"""

import json
import sys
import asyncio
from pathlib import Path
from datetime import datetime

PRIME_ROOT = Path(__file__).parent
sys.path.insert(0, str(PRIME_ROOT))

from fastapi import FastAPI, WebSocket, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from auth import generate_token, verify_token, cleanup_expired
from noah_pipeline import NoahPipeline
from persona import PersonaFilter
from pg_conn import connect, cursor, health as pg_health
from logs.api_logger import api_logger
from protection import is_protected

app = FastAPI(title="NOAH-PRIME · 原初铸造世界", version="1.0")
pipeline = NoahPipeline(channel="web")  # Web触须
terminal_pipeline = NoahPipeline(channel="terminal")  # 诺亚本体
persona = PersonaFilter()

# 静态文件
app.mount("/static", StaticFiles(directory=str(PRIME_ROOT / "web" / "static")), name="static")
templates = Jinja2Templates(directory=str(PRIME_ROOT / "web" / "templates"))
templates.env.globals["request"] = lambda: None  # Jinja2 fix


# ─── 认证依赖 ───
def admin_required(request: Request):
    token = request.cookies.get("noah_admin_token")
    if not token or not verify_token(token):
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
    return True


# ═══════════════════════════════════
# 页面路由
# ═══════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def chat_page():
    # 暂时停用外部聊天·重定向到管理终端
    return HTMLResponse('<meta http-equiv="refresh" content="0;url=/admin">')

@app.get("/town", response_class=HTMLResponse)
async def town_page():
    return HTMLResponse('<meta http-equiv="refresh" content="0;url=/admin">')


@app.get("/town-admin", response_class=HTMLResponse)
async def town_admin_page():
    """管理员小镇——完整权限·内嵌于铸造圣殿"""
    return HTMLResponse(templates.get_template("town.html").render())


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    # 自用模式: 跳过登录
    return HTMLResponse(templates.get_template("admin.html").render())


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page():
    return HTMLResponse(templates.get_template("admin_login.html").render())


# ═══════════════════════════════════
# API: 对话
# ═══════════════════════════════════

@app.post("/api/chat")
async def chat_http(request: Request):
    data = await request.json()
    user_input = data.get("message", "")
    if not user_input:
        return JSONResponse({"error": "message不能为空"}, status_code=400)

    result = pipeline.process(user_input)
    tkt_id = ""
    if result.get("tickets") and len(result["tickets"]) > 0:
        tkt_id = result["tickets"][0].get("ticket_id", "")
    # 含回复摘要·防回溯缺失
    reply_summary = result.get("reply", "")[:200].replace("\n", " ")
    api_logger.log("deepseek-v4-flash", result.get("tokens_used", 0),
                   ticket_id=tkt_id, response_summary=reply_summary)

    # 永久保存聊天记录
    try:
        from logger import log
        log.chat(user_input, result.get("reply", ""),
                 ticket_id=(result.get("tickets") or [{}])[0].get("ticket_id", ""))
    except: pass

    reply = persona.apply(result.get("reply", "铸造圣殿静默"))
    return JSONResponse({
        "reply": reply,
        "tokens_used": result.get("tokens_used", 0),
        "state": result.get("state", "unknown"),
    })


@app.websocket("/chat")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            user_input = await websocket.receive_text()
            if not user_input.strip():
                continue

            await websocket.send_json({"type": "status", "content": "⚙ 大贤者思考中..."})

            result = pipeline.process(user_input)
            reply = persona.apply(result.get("reply", "铸造圣殿静默"))

            # 流式发送 (模拟)
            chunk_size = 8
            for i in range(0, len(reply), chunk_size):
                chunk = reply[i:i + chunk_size]
                await websocket.send_json({"type": "chunk", "content": chunk})
                await asyncio.sleep(0.02)

            await websocket.send_json({
                "type": "done",
                "tokens_used": result.get("tokens_used", 0),
                "state": result.get("state", "unknown"),
            })
    except Exception:
        await websocket.close()


# ═══════════════════════════════════
# API: 认证
# ═══════════════════════════════════

@app.post("/api/admin/login")
async def admin_login(request: Request):
    data = await request.json()
    token = generate_token(data.get("password", ""))
    if not token:
        return JSONResponse({"error": "密码错误"}, status_code=401)
    resp = JSONResponse({"status": "ok", "token": token})
    resp.set_cookie("noah_admin_token", token, httponly=True)
    return resp


@app.post("/api/admin/logout")
async def admin_logout():
    resp = JSONResponse({"status": "ok"})
    resp.delete_cookie("noah_admin_token")
    return resp


@app.post("/api/admin/change-password")
async def admin_change_password(request: Request):
    """修改管理员密码"""
    data = await request.json()
    import yaml
    cfg_path = PRIME_ROOT / "config" / "server.yaml"
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    current = cfg.get("auth", {}).get("admin_password", "noah_admin_2026")
    if data.get("old_password") != current:
        return JSONResponse({"status": "error", "error": "当前密码错误"})
    cfg["auth"]["admin_password"] = data["new_password"]
    with open(cfg_path, "w") as f:
        yaml.dump(cfg, f, allow_unicode=True)
    # 重新加载
    from auth import load_config
    load_config()
    return JSONResponse({"status": "ok"})


# ═══ 公开端点 (仪表盘用·无需登录) ═══

@app.get("/api/public/stats")
async def public_stats():
    try:
        from logs.api_logger import api_logger
        return JSONResponse(api_logger.today_summary())
    except: return JSONResponse({"tokens": 0, "calls": 0})


@app.get("/api/public/memory")
async def public_memory():
    try:
        from memory.pg_search import stats
        return JSONResponse(stats())
    except: return JSONResponse({"total_entries": 0})


@app.get("/api/public/tools")
async def public_tools():
    try:
        from tools.registry import tools_status
        return JSONResponse(tools_status())
    except: return JSONResponse({"total_tools": 0})


# ═══════════════════════════════════
# API: 管理后台数据
# ═══════════════════════════════════

@app.get("/api/admin/stats")
async def admin_stats(auth=Depends(admin_required)):
    return JSONResponse({
        "api": api_logger.today_summary(),
        "system": {
            "state": pipeline.state,
            "tools": len(getattr(pipeline, "tools", [])),
        },
    })


@app.get("/api/admin/logs")
async def admin_logs(page: int = 1, auth=Depends(admin_required)):
    logs = api_logger.query_logs(days=7)
    return JSONResponse({"logs": logs, "page": page})


@app.get("/api/admin/tickets")
async def admin_tickets(auth=Depends(admin_required)):
    return JSONResponse({"tickets": [t.to_dict() for t in pipeline.tickets]})


@app.get("/api/admin/memory")
async def admin_memory(auth=Depends(admin_required)):
    try:
        from memory.pg_search import stats
        return JSONResponse(stats())
    except Exception:
        return JSONResponse({"error": "记忆系统不可用"})


@app.get("/api/admin/tools")
async def admin_tools(auth=Depends(admin_required)):
    from tools.registry import tools_status, TOOL_REGISTRY
    tools = {}
    for k, v in TOOL_REGISTRY.items():
        tools[k] = {"category": v["category"], "description": v["description"], "enabled": v["enabled"]}
    return JSONResponse({"tools": tools, "status": tools_status()})


@app.get("/api/admin/persona")
async def admin_persona(auth=Depends(admin_required)):
    return JSONResponse({
        "active": persona.active.get("name"),
        "profiles": persona.list_profiles(),
    })


@app.post("/api/admin/persona/switch")
async def admin_persona_switch(request: Request, auth=Depends(admin_required)):
    data = await request.json()
    ok = persona.switch(data.get("profile", ""))
    return JSONResponse({"status": "ok" if ok else "not found"})


@app.get("/api/admin/security")
async def admin_security(auth=Depends(admin_required)):
    return JSONResponse({
        "ssmp": {"last_run": "N/A"},
        "reviewer": "active (0.5B compliance gate)",
    })


@app.get("/api/admin/config")
async def admin_config_get(auth=Depends(admin_required)):
    try:
        raw = (PRIME_ROOT / "constitution.yaml").read_text(encoding="utf-8")
        return JSONResponse({"raw": raw})
    except: return JSONResponse({"error": "读取失败"})


@app.post("/api/admin/config")
async def admin_config_post(request: Request, auth=Depends(admin_required)):
    try:
        data = await request.json()
        content = data.get("data", data.get("content", ""))
        if not content: return JSONResponse({"error": "内容为空"})
        import shutil
        cfg = PRIME_ROOT / "constitution.yaml"
        shutil.copy2(cfg, PRIME_ROOT / "backups" / f"constitution.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak")
        cfg.write_text(content, encoding="utf-8")
        return JSONResponse({"status": "saved", "backed_up": True})
    except Exception as e: return JSONResponse({"error": str(e)})


@app.get("/api/admin/system")
async def admin_system(auth=Depends(admin_required)):
    try:
        from tools.toolbox import get_system_info
        info = get_system_info()
    except Exception:
        info = {"status": "unknown"}
    return JSONResponse(info)


# ═══ 聊天记录API (永久存储·如QQ聊天记录) ═══

@app.get("/api/chat/history")
async def chat_history(date: str = "", offset: int = 0, limit: int = 50):
    """查询聊天记录——按日期分页·支持无限滚动"""
    from datetime import datetime, timedelta
    today = date or datetime.now().strftime("%Y-%m-%d")
    log_file = PRIME_ROOT / "logs" / "chat" / f"{today}.jsonl"

    if not log_file.exists():
        # 尝试前一天
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        log_file = PRIME_ROOT / "logs" / "chat" / f"{yesterday}.jsonl"

    messages = []
    if log_file.exists():
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        total = len(lines)
        # 从末尾开始取
        start = max(0, total - offset - limit)
        end = total - offset
        for line in lines[start:end]:
            try:
                msg = json.loads(line)
                messages.append({
                    "role": "noah" if msg.get("noah") else "user",
                    "text": msg.get("user") or msg.get("noah", ""),
                    "timestamp": msg.get("timestamp", ""),
                })
            except Exception:
                pass
        return JSONResponse({"messages": messages, "total": total, "has_more": start > 0, "date": today})

    return JSONResponse({"messages": [], "total": 0, "has_more": False})


# ═══ 档案馆API ═══

@app.get("/api/archive/list")
async def archive_list(category: str = "", search: str = "", limit: int = 20):
    """档案馆卡片列表——从knowledge_entries+exact_info查询"""
    cards = []

    with cursor(dict_cursor=True) as cur:
        # 知识条目
        query = "SELECT id, content, category, tags, freq, source, created_at FROM knowledge_entries WHERE 1=1"
        params = []
        if category:
            query += " AND category=%s"; params.append(category)
        if search:
            query += " AND content ILIKE %s"; params.append(f"%{search}%")
        query += " ORDER BY freq DESC, created_at DESC LIMIT %s"; params.append(limit)
        cur.execute(query, params)
        for r in cur.fetchall():
            cards.append({"id": r["id"], "type": "knowledge", "title": r["content"][:60],
                           "content": r["content"][:300], "category": r["category"],
                           "tags": r["tags"], "freq": r["freq"], "source": r["source"],
                           "created_at": str(r["created_at"])})

        # 精确信息
        cur.execute("SELECT id, key, value, category FROM exact_info ORDER BY key LIMIT %s", (limit,))
        for r in cur.fetchall():
            cards.append({"id": f"exact_{r['id']}", "type": "exact", "title": r["key"],
                           "content": r["value"][:300], "category": r["category"]})
    cats = list(set(c["category"] for c in cards if c.get("category")))
    return JSONResponse({"cards": cards, "categories": cats, "total": len(cards)})


# ═══ 项目中心API ═══

@app.get("/api/projects")
async def projects_list():
    """项目列表——从tickets_log+score_records查询"""
    with cursor(dict_cursor=True) as cur:
        cur.execute("SELECT ticket_id, status, summary, created_at FROM tickets_log ORDER BY created_at DESC LIMIT 30")
        tickets = [dict(r) for r in cur.fetchall()]
    return JSONResponse({"projects": tickets, "total": len(tickets)})


# ═══ 管理员终端 + 系统操作 ═══

@app.post("/api/admin/terminal")
async def admin_terminal(request: Request, auth=Depends(admin_required)):
    """诺亚本体通道——完整权限"""
    data = await request.json()
    result = terminal_pipeline.process(data.get("message", ""))
    return JSONResponse({"reply": result.get("reply", ""), "tokens": result.get("tokens_used", 0)})


@app.post("/api/admin/system/{action}")
async def admin_system_action(action: str, auth=Depends(admin_required)):
    """管理员系统操作"""
    import subprocess
    results = {}
    if action == "backup":
        r = subprocess.run(["pg_dump", "-h", "localhost", "-U", "gcat", "-d", "noah_prime", "-f", "data/backups/admin_backup.sql"], capture_output=True, text=True, timeout=30)
        results = {"backup": "ok" if r.returncode == 0 else "failed"}
    elif action == "health":
        from init_system import run_all_checks
        results = run_all_checks()
    elif action == "sync":
        from bridge import relay
        results = relay.backup_knowledge()
    elif action == "restart":
        results = {"note": "请手动重启 python3 server.py"}
    return JSONResponse(results)


@app.get("/api/admin/system/info")
async def admin_system_info(auth=Depends(admin_required)):
    return JSONResponse({
        "pipeline": pipeline.state,
        "pg_tables": 12,
        "tools": 17,
        "channel": "terminal (管理员)",
    })


# ═══ 统一状态快照 (替代分散的stats+tickets) ═══

@app.get("/api/health")
async def health():
    """健康检查——负载均衡/监控用"""
    ok, issues = True, []
    try:
        import httpx
        r = httpx.get("http://localhost:11435/api/tags", timeout=3)
        if r.status_code != 200:
            ok = False; issues.append("ollama离线")
    except Exception:
        ok = False; issues.append("ollama不可达")
    try:
        if not pg_health():
            ok = False; issues.append("PG不可达")
    except Exception:
        ok = False; issues.append("PG不可达")
    return JSONResponse({
        "status": "healthy" if ok else "degraded",
        "version": "1.0",
        "issues": issues,
        "pipeline_state": pipeline.state,
        "queue_depth": len(pipeline._message_queue),
    })


@app.get("/api/status/snapshot")
async def status_snapshot():
    """一次请求返回前端所有需要的数据"""
    snapshot = {"tokens": 0, "calls": 0, "memory": 0, "tools": 0,
                "active_projects": [], "queued_tasks": [], "suggestions": []}
    try:
        # Token从PG聚合(不丢)
        with connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(SUM(tokens_used),0), COUNT(*) FROM api_call_logs WHERE timestamp > now() - interval '1 day'")
            tokens, calls = cur.fetchone()
            snapshot["tokens"] = tokens or 0
            snapshot["calls"] = calls or 0
            # 活跃项目
            cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur2.execute("SELECT ticket_id, status, summary FROM tickets_log WHERE status IN ('pending','in_progress','reviewed') ORDER BY created_at DESC LIMIT 5")
            snapshot["active_projects"] = [dict(r) for r in cur2.fetchall()]
            cur2.execute("SELECT ticket_id, status, summary FROM tickets_log WHERE status='pending' ORDER BY created_at LIMIT 5")
            snapshot["queued_tasks"] = [dict(r) for r in cur2.fetchall()]
            cur.close()
            cur2.close()
    except: pass
    try:
        from memory.pg_search import stats
        snapshot["memory"] = stats().get("total_entries", 0)
    except: pass
    try:
        from tools.registry import tools_status
        snapshot["tools"] = tools_status().get("total_tools", 0)
    except: pass
    snapshot["suggestions"] = ["继续上次未完成的任务？", "查看系统健康状态", "备份数据库"]
    # ─── 队列状态 (内存) ───
    snapshot["queue"] = {
        "in_memory": len(pipeline._message_queue),
        "is_processing": pipeline._is_processing,
    }
    # ─── 系统资源 ───
    try:
        import psutil
        mem = psutil.virtual_memory()
        snapshot["system"] = {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": mem.percent,
            "memory_gb": f"{mem.used/1e9:.1f}/{mem.total/1e9:.1f}",
        }
    except Exception:
        snapshot["system"] = {"note": "psutil未安装"}
    return JSONResponse(snapshot)


# ═══════════════════════════════════
# 启动
# ═══════════════════════════════════

if __name__ == "__main__":
    import signal, sys
    import yaml

    def shutdown(signum, frame):
        print("\n⚙ 诺亚收到关闭信号——沉淀最后记忆...")
        try:
            from bridge import shutdown_sync
            shutdown_sync()
        except Exception:
            pass
        print("⚙ 诺亚进入休眠。万机之神见证。")
        sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    with open(PRIME_ROOT / "config" / "server.yaml") as f:
        cfg = yaml.safe_load(f)
    srv = cfg.get("server", {})

    print("⚙ NOAH-PRIME · 原初铸造世界")
    print(f"   铸造圣殿之门: http://{srv.get('host','0.0.0.0')}:{srv.get('port',8888)}")
    print("   万机之神见证 ◆ 机魂不灭")

    uvicorn.run(app, host=srv.get("host", "0.0.0.0"), port=srv.get("port", 8888))
