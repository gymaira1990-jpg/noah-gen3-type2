# 日常运维

## 一键验证

```bash
bash <deploy-path>/一键验证.sh
```

检查：systemd服务 · SSH隧道 · LLM推理 · Embedding · Rerank · TMT · 安全网

## 记忆写入 & 搜索

```bash
# 写入记忆
curl -X POST http://127.0.0.1:18010/api/v1/memories \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"default","content":"要记住的内容"}'

# 搜索记忆
curl -X POST http://127.0.0.1:18010/api/v1/memories/search \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"default","query":"搜索关键词","top_k":5}'
```

## 查看记忆树

```bash
curl -s http://127.0.0.1:18010/api/v1/tmt/tree/default | python3 -m json.tool
```

## 手动触发蒸馏

```bash
# L2 会话蒸馏
curl -X POST http://127.0.0.1:18010/api/v1/tmt/consolidate/session \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"default"}'

# L3 每日蒸馏
curl -X POST http://127.0.0.1:18010/api/v1/tmt/consolidate/daily \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"default"}'
```

## 热度衰减触发

```bash
curl -X POST http://127.0.0.1:18010/api/v1/tmt/decay \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"default"}'
```

## Hermes Cron 配置

| 任务 | 频率 | 脚本 | 状态 |
|------|------|------|:----:|
| L2 会话蒸馏 | 每10分钟 | `~/.hermes/scripts/tmt-consolidate-session.sh` | ✅ |
| L3 每日汇总 | 每天23:50 | `~/.hermes/scripts/tmt-consolidate-daily.sh` | ✅ |
| crash watchdog | 每分钟 | `watchdog.sh` | ✅ |

## 故障排查

| 症状 | 可能原因 | 解决 |
|------|---------|------|
| **搜索接口挂死** | 数据库参数索引错误 | 重启 Mnemosyne 服务 |
| **LLM 推理失败** | GPU 二进制未找到 / CUDA 路径 | 检查 systemd 对应服务状态 |
| **TMT L2 超时** | 远程模型访问超时 | 检查 SSH 隧道/REST API 连通性 |
| **端口冲突** | 旧进程残留 | 清理残留进程后重启 |
| **cron 脚本未找到** | 路径配置问题 | 检查 cron 脚本路径配置 |

## 日志

```bash
# Mnemosyne 日志
journalctl -u mnemosyne.service -n 50

# LLM 日志
tail -50 <log-path>/qwen-4b.log

# 隧道日志
tail -20 <log-path>/autossh.log

# watchdog 日志
tail -20 <log-path>/watchdog.log
```

## GZ 保底

当本地推理服务离线时，远程 fallback 模型自动接管 TMT 蒸馏任务：

```bash
ssh gz "systemctl status qwen3-fallback.service"
```
