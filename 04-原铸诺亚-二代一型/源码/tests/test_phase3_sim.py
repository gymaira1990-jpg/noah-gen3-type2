#!/usr/bin/env python3
"""Phase 3 模拟测试 — 16轮对话 × 自动压缩效果"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path.home() / "noah-embryo"))

from brain.secretary import (
    _increment_round, _compress_context,
    _COMPRESS_RAN_AT, _ROUND_COUNTER,
)
from core.compression import compress

# ─── 测试对话数据 ───
ROUNDS = [
    "帮我写个Python脚本处理日志文件",
    "改成读取CSV格式",
    "再加个错误重试机制",
    "报FileNotFoundError了",
    "优化一下内存占用",
    "加个进度条显示",
    "按日期归档日志",
    "改成多线程并行处理",
    "mypy报type hints问题",
    "再集成logging模块",
    "输出格式改成JSON",
    "加个配置文件支持",
    "再加个定时调度功能",
    "决定采用方案B不用分批",
    "写个迁移脚本",
    "通知用户确认后执行",
]

SEP = "─" * 56

print(f"\n  {SEP}")
print(f"    ⛰️ 小诺亚 · Phase 3 自动压缩模拟")
print(f"    16轮对话 × 阈值触发 NEP-002 管线")
print(f"  {SEP}")
print(f"  阈值: 第6轮 → L1→L2 | 第11轮 → L2 | 第16轮 → L3")
print(f"  {SEP}\n")

for i, text in enumerate(ROUNDS, 1):
    # 模拟记忆积累（每轮在记忆上下文中追加）
    mem_entry = f"用户: {text}\n诺亚: 已处理请求，执行相关操作。"

    r = _increment_round()
    triggered = False
    compressed = None

    # 检查触发条件
    if r in (6, 11, 16) and not _COMPRESS_RAN_AT.get(r, True):
        _COMPRESS_RAN_AT[r] = True
        triggered = True
        try:
            compressed = _compress_context(mem_entry, r)
        except Exception as e:
            compressed = f"[降级] {e}"

    # 显示本轮信息
    head = f"  ▸ 第{r:2d}轮 {text[:35]:35s}"
    if triggered:
        lvl = "L1→L2" if r == 6 else "L2" if r == 11 else "L3"
        print(f"{head}  🔄 触发 {lvl} 压缩")
        if compressed:
            lines = compressed.split("\n")
            print(f"    ┌─ {lines[0]}")
            for line in lines[1:3]:
                print(f"    │  {line[:56]}")
            if len(lines) > 3:
                print(f"    │  … ({len(compressed)} chars)")
            print(f"    └{'─' * 40}")
    else:
        print(f"{head}  ·")

    # 模拟处理耗时
    time.sleep(0.1)

print(f"\n  {SEP}")
print(f"  触发记录: {_COMPRESS_RAN_AT}")
print(f"  总轮次:   {r}")
print(f"  {SEP}")
print(f"  L2 压缩效果测试 (模拟完整上下文):\n")

# 模拟长上下文看真实压缩比
long_text = """用户: 帮我写一个Python脚本处理日志文件，按日期归档。
诺亚: 使用正则表达式提取关键信息，按日期目录归档，支持批量处理。
用户: 改成多线程并行处理，加进度条显示。
诺亚: 已添加ThreadPoolExecutor和tqdm进度显示。
用户: mypy报了一堆type hints问题，需要补全。
诺亚: 已补全所有类型注解，支持严格模式。
用户: 决定采用方案B，不分区。
诺亚: 确认采用方案B，已完成方案A分支删除。
待办: 写迁移脚本，测试同步，用户确认后执行。"""

for rnd, label in [(6, "L1→L2"), (11, "L2")]:
    c = compress(long_text, level=2, rounds=rnd)
    ratio = c.compression_ratio
    print(f"    第{rnd:2d}轮 ({label}): {c.original_length} → {c.compressed_length} chars ({ratio:.0%})")

print(f"\n  {SEP}")
print(f"  ✅ Phase 3 模拟完成")
print(f"  {SEP}")
