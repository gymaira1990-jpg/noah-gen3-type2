#!/usr/bin/env python3
"""Analyze heat distribution from real heat-engine.json data + session history"""
import json
import os
import sys
from pathlib import Path
from collections import Counter, defaultdict

# Load real data
data_file = Path.home() / ".hermes" / "knowledge" / "soft-context" / "heat-engine.json"
data = json.loads(data_file.read_text())

items = data["items"]
total_rounds = data["total_rounds"]

# Collect all items with their level
all_items = []
for level in ["L1", "L2", "L3"]:
    for item in items.get(level, []):
        item["_level"] = level
        all_items.append(item)

print("═══ 热度引擎实测分析 ═══")
print(f"数据文件: {data_file}")
print(f"总轮次: {total_rounds}")
print(f"总条目: {len(all_items)}")
print()

# ─── 1. 按层级分布 ───
print("─── 1. 按层级分布 ───")
for level in ["L1", "L2", "L3"]:
    level_items = items.get(level, [])
    heats = [i["heat"] for i in level_items]
    if heats:
        print(f"  {level}: {len(level_items)}条 | 热度 [{min(heats):.1f} ~ {max(heats):.1f}] | 均值 {sum(heats)/len(heats):.1f}")
    else:
        print(f"  {level}: 0条")
print(f"  archive: {items['archive']['count']}条")
print()

# ─── 2. 意图分布 ───
print("─── 2. 意图分布 ───")
intent_counts = Counter(i["intent"] for i in all_items)
intent_avg_heat = defaultdict(list)
for i in all_items:
    intent_avg_heat[i["intent"]].append(i["heat"])
for intent, count in intent_counts.most_common():
    avg_h = sum(intent_avg_heat[intent]) / len(intent_avg_heat[intent])
    pct = count / len(all_items) * 100
    print(f"  {intent:10s}: {count:2d}条 ({pct:4.1f}%) | 平均热度 {avg_h:.1f}")
print()

# ─── 3. 热度分布（三级分档） ───
print("─── 3. 热度分布 ───")
hot = sum(1 for i in all_items if i["heat"] >= 20)
warm = sum(1 for i in all_items if 10 <= i["heat"] < 20)
cold = sum(1 for i in all_items if i["heat"] < 10)
print(f"  高热区(>=20): {hot}条 ({hot/len(all_items)*100:.1f}%)")
print(f"  中热区(10-20): {warm}条 ({warm/len(all_items)*100:.1f}%)")
print(f"  低热区(<10):  {cold}条 ({cold/len(all_items)*100:.1f}%)")
print()

# ─── 4. 每层级内热度分档 ───
print("─── 4. 每层级内热度分布 ───")
for level in ["L1", "L2", "L3"]:
    level_items = items.get(level, [])
    h = sum(1 for i in level_items if i["heat"] >= 20)
    w = sum(1 for i in level_items if 10 <= i["heat"] < 20)
    c = sum(1 for i in level_items if i["heat"] < 10)
    print(f"  {level}: 高热{h} | 中温{w} | 低热{c}")
print()

# ─── 5. 意图 × 热度交叉分析 ───
print("─── 5. 意图 × 热度区交叉 ───")
intent_heat_dist = defaultdict(lambda: {"hot": 0, "warm": 0, "cold": 0})
for i in all_items:
    cat = "hot" if i["heat"] >= 20 else ("warm" if i["heat"] >= 10 else "cold")
    intent_heat_dist[i["intent"]][cat] += 1
for intent in sorted(intent_heat_dist.keys()):
    d = intent_heat_dist[intent]
    print(f"  {intent:10s}: 高热{d['hot']} | 中温{d['warm']} | 低热{d['cold']}")
print()

# ─── 6. 层级跃迁分析 ───
print("─── 6. 层级跃迁倾向 ───")
# Check if items in each level match their heat level
level_mismatch = {"L1": 0, "L2": 0, "L3": 0}
for level in ["L1", "L2", "L3"]:
    for item in items.get(level, []):
        h = item["heat"]
        if level == "L1" and h < 25:
            level_mismatch["L1"] += 1
        elif level == "L2" and (h < 15 or h >= 25):
            level_mismatch["L2"] += 1
        elif level == "L3" and (h < 5 or h >= 15):
            level_mismatch["L3"] += 1
for level in ["L1", "L2", "L3"]:
    total = len(items.get(level, []))
    mismatch = level_mismatch[level]
    if total > 0:
        print(f"  {level}: {mismatch}/{total} 条热度与层级不匹配 ({mismatch/total*100:.0f}%)")
print()

# ─── 7. 按意图统计衰退/留存 ───
print("─── 7. 意图留存倾向 ───")
# Per intent, how many rounds since creation (proxy for "staying power")
for intent in sorted(intent_counts.keys()):
    items_of_intent = [i for i in all_items if i["intent"] == intent]
    avg_freq = sum(i.get("freq", 1) for i in items_of_intent) / len(items_of_intent)
    avg_heat = sum(i["heat"] for i in items_of_intent) / len(items_of_intent)
    print(f"  {intent:10s}: {len(items_of_intent):2d}条 | 平均freq={avg_freq:.1f} | 平均heat={avg_heat:.1f}")

print()
print("═══ 报告结束 ═══")
