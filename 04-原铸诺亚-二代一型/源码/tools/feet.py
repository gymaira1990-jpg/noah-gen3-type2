#!/usr/bin/env python3
"""远征队 · 联网与远程工具 · tools/feet.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
HTTP请求、SSH远程、Git操作
"""

import subprocess
import json
from tools.registry import register, is_safe_url, is_safe_path


# ═══ F1: HTTP请求 ═══

def http_request(method: str, url: str, body: dict = None, headers: dict = None, timeout: int = 15) -> dict:
    if not is_safe_url(url):
        return {"error": f"SSRF防护: 禁止访问内网地址 {url}"}
    import requests
    try:
        resp = requests.request(method, url, json=body, headers=headers, timeout=timeout)
        return {
            "status": "ok",
            "status_code": resp.status_code,
            "body": resp.text[:5000],
        }
    except Exception as e:
        return {"error": str(e)}


register("http_request", http_request, "feet", "发送HTTP请求", requires_review=True)


# ═══ F2: SSH远程执行 ═══

def ssh_remote(host: str, command: str, key_path: str = None) -> dict:
    if not key_path:
        from pathlib import Path
        key_path = str(Path.home() / ".ssh" / "guangzhou-server.pem")
    import paramiko
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, key_filename=key_path, timeout=10)
        _, stdout, stderr = ssh.exec_command(command, timeout=30)
        result = {
            "status": "ok",
            "stdout": stdout.read().decode("utf-8", errors="replace")[-5000:],
            "stderr": stderr.read().decode("utf-8", errors="replace")[-2000:],
        }
        ssh.close()
        return result
    except Exception as e:
        return {"error": f"SSH失败: {e}"}


register("ssh_remote", ssh_remote, "feet", "SSH远程执行命令", requires_review=True)


# ═══ F3: Git操作 ═══

def git_clone(repo_url: str, target_dir: str = None) -> dict:
    from pathlib import Path
    target = target_dir or str(Path.home() / "noah-prime" / "data" / "repos")
    subprocess.run(["mkdir", "-p", target], capture_output=True)
    result = subprocess.run(
        ["git", "clone", repo_url, target],
        capture_output=True, text=True, timeout=120,
    )
    return {
        "status": "ok" if result.returncode == 0 else "failed",
        "stdout": result.stdout[-3000:],
    }


register("git_clone", git_clone, "feet", "克隆Git仓库", requires_review=True)

# ─── 测试 ───
if __name__ == "__main__":
    print("feet工具: http_request, ssh_remote, git_clone 已注册")
