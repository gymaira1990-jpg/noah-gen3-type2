#!/usr/bin/env python3
"""保护标记系统 · protection.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
战锤40K主题: 纯洁印记 (Purity Seal)

保护标记:
  <<TICKET>> ... <</TICKET>>    工单核心字段 — 100%保留，一字不易
  <<SOLUTION>> ... <</SOLUTION>> 代码或执行步骤 — 不删不改不概括
  (( ... ))                      关键参数 — 允许格式调整，禁数据丢失
  <<IRON_RULE>> ... <</IRON_RULE>> 永久铁律 — 跨会话携带，永不压缩

用法:
  from protection import scan, verify, strip_markers
  markers = scan(text)           → 提取所有保护标记
  is_intact = verify(text)       → 验证保护区完整性
  clean = strip_markers(text)    → 去除标记符号（用于展示）
"""

import re
import hashlib
from dataclasses import dataclass
from typing import List, Optional

# ─── 标记模式 ───
MARKER_TICKET   = re.compile(r'<<TICKET>>(.*?)<</TICKET>>', re.DOTALL)
MARKER_SOLUTION = re.compile(r'<<SOLUTION>>(.*?)<</SOLUTION>>', re.DOTALL)
MARKER_IRON     = re.compile(r'<<IRON_RULE>>(.*?)<</IRON_RULE>>', re.DOTALL)
MARKER_PARAM    = re.compile(r'\(\((.*?)\)\)', re.DOTALL)

PROTECTED_MARKER = "__NOAH_PRIME_PROTECTED__"


@dataclass
class ProtectionMarker:
    marker_type: str      # TICKET | SOLUTION | IRON_RULE | PARAM
    content: str
    hash: str
    start: int
    end: int


def scan(text: str) -> List[ProtectionMarker]:
    """扫描文本，提取所有保护标记"""
    markers = []
    for pattern, mtype in [
        (MARKER_TICKET, "TICKET"),
        (MARKER_SOLUTION, "SOLUTION"),
        (MARKER_IRON, "IRON_RULE"),
        (MARKER_PARAM, "PARAM"),
    ]:
        for match in pattern.finditer(text):
            content = match.group(1).strip()
            markers.append(ProtectionMarker(
                marker_type=mtype,
                content=content,
                hash=hashlib.sha256(content.encode()).hexdigest()[:16],
                start=match.start(),
                end=match.end(),
            ))
    return sorted(markers, key=lambda m: m.start)


def verify(original: str, compressed: str) -> dict:
    """压缩后验证：保护标记内容是否完整未被篡改"""
    orig_markers = scan(original)
    comp_markers = scan(compressed)

    orig_map = {m.hash: m for m in orig_markers}
    comp_map = {m.hash: m for m in comp_markers}

    intact = []
    missing = []
    altered = []

    for h, m in orig_map.items():
        if h in comp_map:
            if m.content == comp_map[h].content:
                intact.append(h)
            else:
                altered.append(h)
        else:
            missing.append(h)

    return {
        "total": len(orig_markers),
        "intact": len(intact),
        "missing": missing,
        "altered": altered,
        "passed": len(missing) == 0 and len(altered) == 0,
    }


def strip_markers(text: str) -> str:
    """去除标记标签，保留内容（用于展示）"""
    text = MARKER_TICKET.sub(r'\1', text)
    text = MARKER_SOLUTION.sub(r'\1', text)
    text = MARKER_IRON.sub(r'\1', text)
    text = MARKER_PARAM.sub(r'\1', text)
    return text


def is_protected(text: str) -> bool:
    """检查文本是否含保护标记"""
    return PROTECTED_MARKER in text or bool(
        MARKER_TICKET.search(text)
        or MARKER_SOLUTION.search(text)
        or MARKER_IRON.search(text)
    )


# ─── 测试 ───
if __name__ == "__main__":
    test = """用户说：备份一下数据库。
<<TICKET>>{"ticket_id":"20260509-NOA-001","type":"system_ops"}<</TICKET>>
<<SOLUTION>>pg_dump noah_prime > backup.sql<</SOLUTION>>
路径是 (( <noah_home>/data/ ))
<<IRON_RULE>>永不删除用户原始文件<</IRON_RULE>>"""

    m = scan(test)
    print(f"扫描到 {len(m)} 个保护标记:")
    for mm in m:
        print(f"  [{mm.marker_type}] {mm.hash}: {mm.content[:50]}...")

    v = verify(test, test)
    print(f"\n自检: {'✅ 通过' if v['passed'] else '❌ 失败'}")

    # 测试篡改
    tampered = test.replace("pg_dump noah_prime", "rm -rf /")
    v2 = verify(test, tampered)
    print(f"篡改检测: {'❌ 未检测到' if v2['passed'] else '✅ 正确标记为 altered'}")
