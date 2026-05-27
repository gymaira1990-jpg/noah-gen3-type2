"""模型 CRUD + 发现 + 搜索 API"""

from fastapi import APIRouter, HTTPException, Body
from ..kernel import load_config, ModelConfig, CONFIG_FILE
from ..models import add_model, remove_model, get_model
from ..discovery import discover_ollama_models, discover_llamacpp_models, fetch_models_from_api, search_hf_models

router = APIRouter(prefix="/api", tags=["models"])


@router.get("/models")
async def api_models():
    cfg = load_config()
    return {"object": "list", "data": [
        {"id": m.name, "name": m.name, "real_name": m.real_name, "model_id": m.model_id,
         "object": "model", "owned_by": m.provider,
         "api_base": m.api_base, "api_key_env": m.api_key_env,
         "type": m.type, "temperature": m.temperature,
         "max_tokens": m.max_tokens,
         "description": m.description, "notes": m.notes} for m in cfg.models
    ]}


@router.post("/models")
async def api_add_model(body: dict = Body(...)):
    cfg = load_config()
    m = ModelConfig(
        name=body.get("name", ""),
        real_name=body.get("real_name", body.get("name", "")),
        model_id=body.get("model_id", body.get("name", "")),
        provider=body.get("provider", "openai"),
        api_base=body.get("api_base", ""),
        api_key_env=body.get("api_key_env") or None,
        type=body.get("type", "api"),
        temperature=float(body.get("temperature", 0.7)),
        max_tokens=int(body.get("max_tokens", 4096)),
        description=body.get("description", ""),
        notes=body.get("notes", ""),
    )
    if not m.name or not m.api_base:
        raise HTTPException(400, "名称和API地址不能为空")
    if get_model(cfg, m.name):
        raise HTTPException(409, f"模型 '{m.name}' 已存在")
    add_model(cfg, m)
    return {"status": "ok", "name": m.name}


@router.put("/models/{name}")
async def api_edit_model(name: str, body: dict = Body(...)):
    cfg = load_config()
    m = get_model(cfg, name)
    if not m:
        raise HTTPException(404, f"模型 '{name}' 不存在")
    for k, v in body.items():
        if v is not None and v != "":
            if k == "temperature":
                v = float(v)
            elif k == "max_tokens":
                v = int(v)
            if hasattr(m, k):
                setattr(m, k, v)
    add_model(cfg, m)
    return {"status": "ok", "name": name}


@router.delete("/models/{name}")
async def api_delete_model(name: str):
    cfg = load_config()
    if not get_model(cfg, name):
        raise HTTPException(404, f"模型 '{name}' 不存在")
    remove_model(cfg, name)
    return {"status": "ok", "name": name}


@router.get("/models/library")
async def api_models_library():
    """分类模型库：可对话 vs 功能，本地 vs 云"""
    cfg = load_config()
    result = {"chat": {"local": [], "cloud": []}, "function": {"local": [], "cloud": []}}
    for m in cfg.models:
        name_lower = (m.name + " " + m.model_id + " " + m.description).lower()
        is_embedding = "embedding" in name_lower or "embed" in name_lower
        is_reranker = "reranker" in name_lower or "rerank" in name_lower or "bge" in name_lower
        is_local = m.type == "local" or m.provider in ("llamacpp", "ollama")
        entry = {
            "name": m.name, "real_name": m.real_name, "model_id": m.model_id,
            "provider": m.provider, "api_base": m.api_base, "type": m.type,
            "temperature": m.temperature, "max_tokens": m.max_tokens,
            "description": m.description, "notes": m.notes,
        }
        if is_embedding or is_reranker:
            result["function"]["local" if is_local else "cloud"].append(entry)
        else:
            result["chat"]["local" if is_local else "cloud"].append(entry)
    return result


@router.get("/discover-ollama")
async def api_discover_ollama():
    ollama_models = discover_ollama_models()
    llama_models, llama_ports = discover_llamacpp_models()
    return {"models": ollama_models + llama_models, "llama_ports": llama_ports}


@router.get("/discover-api")
async def api_discover_api(api_base: str = "", api_key_env: str = ""):
    if not api_base:
        raise HTTPException(400, "api_base 不能为空")
    models = fetch_models_from_api(api_base, api_key_env or None)
    return {"models": models}


@router.get("/search-hf")
async def api_search_hf(q: str = ""):
    if not q:
        raise HTTPException(400, "搜索关键词不能为空")
    results = search_hf_models(q)
    return {"results": results}


@router.post("/add-discovered")
async def api_add_discovered(body: dict = Body(...)):
    cfg = load_config()
    models = body.get("models", [])
    added = 0
    for md in models:
        cap = md.get("capability", "chat")
        cap_label = {"chat": "对话", "embedding": "嵌入", "reranker": "排序", "vision": "视觉"}.get(cap, cap)
        m = ModelConfig(
            name=md.get("name", md.get("id", "")),
            real_name=md.get("real_name", md.get("id", "")),
            model_id=md.get("model_id", md.get("id", "")),
            provider=md.get("provider", body.get("default_provider", "openai")),
            api_base=md.get("api_base", body.get("default_api_base", "")),
            api_key_env=md.get("api_key_env") or body.get("default_api_key_env") or None,
            type=md.get("type", body.get("default_type", "api")),
            temperature=float(body.get("default_temperature", 0.7)),
            max_tokens=int(body.get("default_max_tokens", 4096)),
            description=f"{cap_label} · {md.get('description', '')}" if md.get('description') else f"{cap_label}",
            notes=md.get("notes", ""),
        )
        if not get_model(cfg, m.name):
            add_model(cfg, m)
            added += 1
    return {"status": "ok", "added": added}
