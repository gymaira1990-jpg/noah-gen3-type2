"""诺亚核心 · 仪表盘"""
from dataclasses import dataclass, field
from typing import Optional
from .kernel import Config, load_config, CONFIG_DIR
from .health import ModelStatus, check_all_models
from .models import get_model

@dataclass
class DashboardData:
    total_models: int = 0
    online_count: int = 0
    offline_count: int = 0
    api_models: int = 0
    local_models: int = 0
    models: list[ModelStatus] = field(default_factory=list)
    error: Optional[str] = None


def build_dashboard(cfg: Optional[Config] = None) -> DashboardData:
    if cfg is None:
        cfg = load_config()
    if not cfg.models:
        return DashboardData(error="没有配置模型")
    results = check_all_models(cfg.models)
    return DashboardData(
        total_models=len(results), models=results,
        online_count=sum(1 for r in results if r.online),
        offline_count=sum(1 for r in results if not r.online),
        api_models=sum(1 for r in results if r.type == "api"),
        local_models=sum(1 for r in results if r.type == "local"),
    )


def render_dashboard_text(data: DashboardData) -> str:
    import os
    if data.error:
        return f"\n  ⚠️  {data.error}\n"
    lines = []
    lines.append(f"\n  {'='*56}")
    lines.append(f"  诺亚核心 · 仪表盘")
    lines.append(f"  {'='*56}")
    lines.append(f"  总计: {data.total_models} | 🟢 在线: {data.online_count} | 🔴 离线: {data.offline_count}")
    lines.append(f"  API模型: {data.api_models} | 本地模型: {data.local_models}")
    lines.append(f"  {'─'*56}")
    cfg = load_config()
    for s in data.models:
        m = get_model(cfg, s.name)
        key_status = "✅ 已配置" if (m and m.api_key_env and os.environ.get(m.api_key_env)) else "⚠️ 未配置" if (m and m.api_key_env) else "-"
        lines.append(f"  {s.status_emoji} {m.name if m else s.name}")
        if m:
            lines.append(f"     真实名称: {m.real_name or '-'}")
            lines.append(f"     MOD名字: {m.model_id}")
            lines.append(f"     提供商:   {m.provider} · {m.type}")
            lines.append(f"     API地址:  {m.api_base}")
            lines.append(f"     KEY:      {m.api_key_env or '-'} {key_status}")
            lines.append(f"     参数:     temp={m.temperature}  max_tokens={m.max_tokens}")
        lines.append(f"     状态:     {s.status_text}")
        if m and m.description:
            lines.append(f"     描述:     {m.description}")
        if m and m.notes:
            lines.append(f"     备注:     {m.notes}")
        lines.append("")
    lines.append(f"  {'='*56}\n")
    return "\n".join(lines)
