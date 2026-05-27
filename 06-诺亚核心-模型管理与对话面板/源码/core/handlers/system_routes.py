"""系统状态 + 健康检查 + 服务状态 API"""

import subprocess, re, os, time
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from ..kernel import load_config, CONFIG_FILE
from ..models import get_model
from ..dashboard import build_dashboard
from ..health import check_model_health

router = APIRouter(prefix="/api", tags=["system"])


def _run(cmd, timeout=5):
    """安全执行命令，返回 stdout 或空字符串"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


@router.get("/check")
async def api_check():
    from ..dashboard import build_dashboard
    d = build_dashboard()
    cfg = load_config()
    return {"total": d.total_models, "online": d.online_count,
            "offline": d.offline_count, "models": [
        {"name": s.name, "online": s.online, "latency_ms": s.latency_ms,
         "status_text": s.status_text, "provider": s.provider,
         "type": s.type, "description": s.description,
         "real_name": (get_model(cfg, s.name).real_name if get_model(cfg, s.name) else ""),
         "model_id": (get_model(cfg, s.name).model_id if get_model(cfg, s.name) else ""),
         "api_base": (get_model(cfg, s.name).api_base if get_model(cfg, s.name) else ""),
         "api_key_env": (get_model(cfg, s.name).api_key_env if get_model(cfg, s.name) else None),
         "temperature": (get_model(cfg, s.name).temperature if get_model(cfg, s.name) else 0.7),
         "max_tokens": (get_model(cfg, s.name).max_tokens if get_model(cfg, s.name) else 4096),
         "notes": (get_model(cfg, s.name).notes if get_model(cfg, s.name) else "")} for s in d.models
    ]}


@router.get("/check/{name}")
async def api_check_one(name: str):
    cfg = load_config()
    model = get_model(cfg, name)
    if not model:
        raise HTTPException(404, f"模型 '{name}' 不存在")
    s = check_model_health(model)
    return {"name": s.name, "online": s.online, "latency_ms": s.latency_ms,
            "status_text": s.status_text}


def _parse_mem_val(val):
    """解析 'MiB' 值 → 纯数字"""
    if isinstance(val, (int, float)):
        return val
    return int(re.sub(r'[^0-9.]', '', str(val)) or 0)


@router.get("/system")
async def api_system():
    """系统资源：CPU/RAM/GPU/磁盘/运行时间"""
    info = {"cpu": {}, "memory": {}, "gpu": [], "disk": {}, "uptime": "", "swap": {}}

    try:
        # ── CPU ──
        cpu_cores = _run(["nproc"])
        load_raw = _run(["cat", "/proc/loadavg"]).split()[:3]
        info["cpu"] = {"cores": cpu_cores, "load": load_raw}

        # ── 内存 ──
        mem_raw = _run(["free", "-m"])
        for line in mem_raw.split("\n"):
            if line.startswith("Mem:"):
                parts = line.split()
                total = int(parts[1])
                used = int(parts[2])
                free = int(parts[3])
                pct = round(used / total * 100, 1) if total > 0 else 0
                info["memory"] = {
                    "total": total, "used": used, "free": free,
                    "pct": f"{pct}%", "pct_num": round(pct)
                }
            if line.startswith("Swap:"):
                parts = line.split()
                swap_t = int(parts[1])
                swap_u = int(parts[2])
                swap_pct = round(swap_u / swap_t * 100, 1) if swap_t > 0 else 0
                info["swap"] = {
                    "total": swap_t, "used": swap_u,
                    "pct": f"{swap_pct}%", "pct_num": round(swap_pct)
                }

        # ── GPU ──
        gpu_raw = _run([
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu",
            "--format=csv,noheader"
        ], timeout=10)
        for line in gpu_raw.split("\n"):
            if line.strip():
                parts = [p.strip() for p in line.split(",")]
                vram_t = _parse_mem_val(parts[1]) if len(parts) > 1 else 0
                vram_u = _parse_mem_val(parts[2]) if len(parts) > 2 else 0
                util = _parse_mem_val(parts[3]) if len(parts) > 3 else 0
                temp = parts[4].strip() if len(parts) > 4 else "?"
                info["gpu"].append({
                    "name": parts[0],
                    "vram_total": vram_t, "vram_used": vram_u,
                    "vram_pct": round(vram_u / vram_t * 100, 1) if vram_t > 0 else 0,
                    "util": util, "temp": temp
                })

        # ── 磁盘 → / ──
        df_raw = _run(["df", "-h", "--output=target,size,used,avail,pcent", "/"])
        for line in df_raw.split("\n")[1:2]:
            parts = line.split()
            if len(parts) >= 5:
                use_pct_raw = parts[4].replace("%", "")
                info["disk"] = {
                    "mount": parts[0], "total": parts[1],
                    "used": parts[2], "avail": parts[3],
                    "use_pct": f"{use_pct_raw}%",
                    "use_pct_num": int(use_pct_raw)
                }
        # ── 磁盘 → /home ──
        df_home = _run(["df", "-h", "--output=target,size,used,avail,pcent", "/home/user"])
        for line in df_home.split("\n")[1:2]:
            parts = line.split()
            if len(parts) >= 5:
                hpct = parts[4].replace("%", "")
                info["disk_home"] = {
                    "mount": parts[0], "total": parts[1],
                    "used": parts[2], "avail": parts[3],
                    "use_pct": f"{hpct}%", "use_pct_num": int(hpct)
                }

        # ── 运行时间 ──
        uptime_sec = _run(["cat", "/proc/uptime"]).split()
        if uptime_sec:
            sec = float(uptime_sec[0])
            days = int(sec // 86400)
            hours = int((sec % 86400) // 3600)
            mins = int((sec % 3600) // 60)
            parts = []
            if days > 0: parts.append(f"{days}天")
            if hours > 0: parts.append(f"{hours}时")
            parts.append(f"{mins}分")
            info["uptime"] = " ".join(parts)
            info["uptime_sec"] = round(sec)

        # ── 进程数 ──
        proc_count = _run(["ps", "-A", "--no-headers", "|", "wc", "-l"])
        if not proc_count or "|" in proc_count:
            proc_count = _run(["ps", "--no-headers", "-e"])
            info["processes"] = len(proc_count.split("\n"))
        else:
            info["processes"] = int(proc_count)

        # ── 主机名 ──
        info["hostname"] = _run(["hostname"])

    except Exception:
        pass

    return info


@router.get("/services")
async def api_services():
    """本地 llama.cpp 服务状态"""
    services = []
    for f in ["lla-server", "lla-embed", "lla-reranker"]:
        try:
            r = subprocess.run(["systemctl", "is-active", f], capture_output=True, text=True, timeout=5)
            active = r.stdout.strip() == "active"
            port = {"lla-server": 11435, "lla-embed": 11433, "lla-reranker": 11436}.get(f, "?")
            name_map = {"lla-server": "Qwen3.5-4B", "lla-embed": "Qwen3 Embedding", "lla-reranker": "Qwen3 Reranker"}
            entry = {"name": name_map.get(f, f), "service": f, "active": active, "port": port, "has_mmproj": False}
            if active:
                try:
                    p = subprocess.run(["ss", "-tlnp", f"sport = :{port}"], capture_output=True, text=True, timeout=5)
                    m = re.search(r'pid=(\d+)', p.stdout)
                    if m:
                        cmd = open(f"/proc/{m.group(1)}/cmdline").read()
                        entry["has_mmproj"] = "--mmproj" in cmd
                except Exception:
                    pass
            services.append(entry)
        except Exception:
            services.append({"name": f, "service": f, "active": False, "port": "?", "has_mmproj": False})
    return services


@router.get("/config")
async def api_config():
    """返回配置文件内容"""
    try:
        yaml_text = CONFIG_FILE.read_text(encoding="utf-8")
        return {"yaml": yaml_text, "path": str(CONFIG_FILE)}
    except Exception as e:
        return {"yaml": f"# 无法读取配置: {e}", "path": str(CONFIG_FILE)}
