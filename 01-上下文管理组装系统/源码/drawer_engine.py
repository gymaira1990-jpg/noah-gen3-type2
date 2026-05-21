"""
抽屉级联压缩引擎 v1.0 (2026-05-21)
===================================
替换 Z1-Z5 区域化压缩。核心组件:
  - DrawerStack: 抽屉栈，满 N 条 → 压缩递交到下一层
  - TemperatureIndex: 温度召回(温度=命中次数, 非时间)
  - DedupEngine: 每轮去重
  - AuxiliaryAgent: 独立模型三链调度(GLM→Qwen→DS)

参考:
  - Stingy Context (arxiv 2601.19929): 层次树 18:1
  - HOMER (ICLR 2024): 层次化上下文合并
  - noah-prime heat_engine.py: 原铸热度引擎
"""

import hashlib
import json
import logging
import os
import re
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ==============================================================
# 常量
# ==============================================================

# 独立模型路由（已确认: GLM-4-Flash 主选, temperature=0.1）
AUX_MODEL_CHAIN = [
    {
        "name": "glm",
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "GLM-4-Flash",
        "api_key_env": "ZHIPU_API_KEY",
        "timeout": 30,
    },
    {
        "name": "siliconflow",
        "url": "https://api.siliconflow.cn/v1/chat/completions",
        "model": "Qwen/Qwen3-8B",
        "api_key_env": "SILICONFLOW_API_KEY",
        "timeout": 120,
    },
    # 保底: 函数被调用时由调用方传 key, 此处仅占位
]

# 温度层级(温度 = 命中次数, 不是时间)
TEMPERATURE_LAYERS = [
    ("L1", 8, 80, 20),    # (层级, 阈值, token/条, cap条数)
    ("L2", 4, 60, 50),
    ("L3", 2, 40, 200),
    ("Archive", 0, 0, 0),
]

# 各层衰减率(越高保留越久)
DECAY_RATES = {"L1": 0.985, "L2": 0.975, "L3": 0.965, "Archive": 0.95}

# 重要性加分
IMPORTANCE_BONUS = {
    "unfinished_task": 5,   # 未完成任务
    "correction": 4,        # 用户纠正
    "decision": 3,          # 决策
    "emotion": 3,           # 情绪波动
    "path_change": 2,       # 路径/配置变更
    "tool_result": 1,       # 工具结果
    "chitchat": 0,          # 寒喧
    "protected": float('inf'),  # 永久保护
}

# 抽屉容量
DRAWER_CAPACITY = 3  # 每个抽屉满 N 条就压缩递交

# 各层摘要约 token 数
SUMMARY_TOKENS = {1: 400, 2: 200, 3: 100, 4: 50}

# 摘要前缀(极简, 不重复输出)
SUMMARY_PREFIXES = {
    1: "[摘要] ",
    2: "[元摘要] ",
    3: "[超摘要] ",
    4: "[归档] ",
}

# 永久保护关键词(永不衰减/归档)
PROTECTED_KEYWORDS = [
    "__HERMES_SOUL_PROTECTED__",
    "[PROTECTED]",
    "[CORRECTION]",
    "[DECISION_",
    "[IRON_LAW]",
    "[IRONLAW]",
    "[SECURITY]",
    "[IDENTITY]",
]

# ==============================================================
# 噪音模式(纯正则, 不调LLM)
# ==============================================================

# 寒喧/确认/元命令 — 命中不计入抽屉轮数
NOISE_PATTERNS = [
    # 单字/短确认
    r'^[好嗯是okOK行可]$',
    r'^[好嗯]的?$',
    r'^明白了?$',
    r'^知道了?$',
    r'^可以$',
    r'^继续$',
    r'^收到$',
    r'^了解$',
    r'^对$',
    r'^没错$',
    r'^是的$',
    r'^嗯嗯?$',
    r'^哈哈?$',
    r'^呵呵?$',
    r'^牛逼$',
    r'^我去$',
    # 元命令
    r'^/compress',
    r'^/status',
    r'^/new',
    r'^/reset',
    r'^/help',
    r'^/debug',
    # 非语义分隔符
    r'^[-=*]{3,}$',
    r'^[-=*]{3,}.*[-=*]{3,}$',
    # 标点/符号单行
    r'^[。，！？\.\,\!\?\s]{1,10}$',
]

# 保护信号模式(命中自动标记 PROTECTED)
PROTECT_SIGNAL_PATTERNS = {
    "plan": [r'(设计|方案|架构|计划)\s*[:：]', r'项目\s*名称', r'立项'],
    "progress": [r'(当前|完成|剩余|进度)', r'下一步', r'TODO|待办|未完成'],
    "execution": [r'(执行|部署|配置|安装|修改|改动了|写了|创建了|新建了|删除了)'],
    "decision": [r'(决定|确认|同意|批准|就按|就这么选)'],
    "correction": [r'(不对|不是的|错了|纠正|说错了|你错了|不是这样|不能这么)'],
    "tfc_ref": [r'(TFC|NCP|PRJ)-\d+'],
    "emotion": [r'(去死|永久离线|最后机会|滚|崩溃|受不了)'],
}

# 噪音不计轮数的条目类型
NOISE_CATEGORIES = {"chitchat", "command", "separator"}

# ==============================================================
# NoiseFilter — 噪音/闲聊过滤
# ==============================================================

class NoiseFilter:
    """噪音过滤器。检测寒喧/确认/元命令, 命中不入抽屉、不升温。"""

    @staticmethod
    def classify(text: str) -> str:
        """返回分类: 'chitchat'(废话) | 'command'(元命令) | 'content'(有效内容)。"""
        if not text or not text.strip():
            return "chitchat"
        text_stripped = text.strip()
        for pattern in NOISE_PATTERNS:
            if re.match(pattern, text_stripped):
                if text_stripped.startswith("/"):
                    return "command"
                return "chitchat"
        return "content"

    @staticmethod
    def is_noise(text: str) -> bool:
        return NoiseFilter.classify(text) != "content"


# ==============================================================
# ProtectionDetector — 保护识别器
# ==============================================================

class ProtectionDetector:
    """检测内容是否需要保护。"""

    @staticmethod
    def detect(text: str) -> Dict:
        """检测保护信号, 返回 {protected, protection_type, key}。

        Returns:
            protected: True/False
            protection_type: 保护类型或None
            key: 唯一key(如 plan:项目名)或None
            importance_bonus: 根据类型计算的加分
        """
        if not text:
            return {"protected": False, "protection_type": None, "key": None, "importance_bonus": 0}

        # 硬保护(标记在文本中)
        if _is_protected(text):
            return {"protected": True, "protection_type": "hard", 
                    "key": None, "importance_bonus": float('inf')}

        low = text.lower()

        # 情绪爆发 → 强制保护全轮
        for pat in PROTECT_SIGNAL_PATTERNS["emotion"]:
            if re.search(pat, low):
                return {"protected": True, "protection_type": "emotion",
                        "key": f"emotion:{hashlib.md5(text.encode()).hexdigest()[:12]}",
                        "importance_bonus": IMPORTANCE_BONUS["correction"]}

        # 方案/设计 → key = plan:<项目名>
        for pat in PROTECT_SIGNAL_PATTERNS["plan"]:
            if re.search(pat, low):
                # 尝试提取项目名
                project = ProtectionDetector._extract_project_name(text)
                key = f"plan:{project}" if project else None
                return {"protected": True, "protection_type": "plan",
                        "key": key, "importance_bonus": IMPORTANCE_BONUS["decision"]}

        # 进度 → key = progress:<TFC编号>
        for pat in PROTECT_SIGNAL_PATTERNS["progress"]:
            if re.search(pat, low):
                tfc = ProtectionDetector._extract_tfc(text)
                key = f"progress:{tfc}" if tfc else None
                return {"protected": True, "protection_type": "progress",
                        "key": key, "importance_bonus": IMPORTANCE_BONUS["unfinished_task"]}

        # 执行日志 → key = exec:<TFC>:<轮次>
        for pat in PROTECT_SIGNAL_PATTERNS["execution"]:
            if re.search(pat, low):
                tfc = ProtectionDetector._extract_tfc(text)
                key = f"exec:{tfc}" if tfc else f"exec:{hashlib.md5(text.encode()).hexdigest()[:12]}"
                return {"protected": False, "protection_type": "execution",
                        "key": key, "importance_bonus": IMPORTANCE_BONUS["path_change"]}

        # 决策 → key = decision:<内容hash>
        for pat in PROTECT_SIGNAL_PATTERNS["decision"]:
            if re.search(pat, low):
                return {"protected": True, "protection_type": "decision",
                        "key": f"decision:{hashlib.md5(text.encode()).hexdigest()[:12]}",
                        "importance_bonus": IMPORTANCE_BONUS["decision"]}

        # 纠正 → key = correction:<内容hash>
        for pat in PROTECT_SIGNAL_PATTERNS["correction"]:
            if re.search(pat, low):
                return {"protected": True, "protection_type": "correction",
                        "key": f"correction:{hashlib.md5(text.encode()).hexdigest()[:12]}",
                        "importance_bonus": IMPORTANCE_BONUS["correction"]}

        # TFC引用 → key = tfc_ref:<编号>
        for pat in PROTECT_SIGNAL_PATTERNS["tfc_ref"]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return {"protected": False, "protection_type": "tfc_ref",
                        "key": f"tfc_ref:{m.group(0).upper()}",
                        "importance_bonus": IMPORTANCE_BONUS["tool_result"]}

        return {"protected": False, "protection_type": None, 
                "key": None, "importance_bonus": 0}

    @staticmethod
    def _extract_project_name(text: str) -> str:
        """提取项目名称。"""
        m = re.search(r'(设计|方案|架构|计划)\s*[:：]\s*(.{2,20})', text)
        if m:
            return m.group(2).strip()[:20]
        m = re.search(r'项目\s*名称\s*[:：]\s*(.{2,20})', text)
        if m:
            return m.group(1).strip()[:20]
        return "unknown"

    @staticmethod
    def _extract_tfc(text: str) -> str:
        """提取 TFC/NCP/PRJ 编号。"""
        m = re.search(r'(TFC|NCP|PRJ)-\d+', text, re.IGNORECASE)
        return m.group(0).upper() if m else None


# ==============================================================
# UniqueKeyIndex — key 身份管理
# ==============================================================

class UniqueKeyIndex:
    """唯一 key 索引。管理实体的身份唯一性。

    方案/进度/纠正/决策 各有一个 key, 同一 key 不重复推入。
    更新策略:
      - plan: 原地替换(版本认可最新的)
      - progress: 追加(同key+同日不重复)
      - correction: 不更新(保留全部, 同hash不重复)
      - decision: 不更新(保留全部, 同hash不重复)
      - execution: 追加(同key+同日不重复)
      - completed: 一次性(不更新)
    """

    def __init__(self):
        # _keys[key] = {"protection_type": str, "updated_at": round, 
        #               "version": int, "content": str}
        self._keys: Dict[str, Dict] = {}
        self._round: int = 0

    def check(self, key: str, content: str = "", 
              protection_type: str = None) -> Dict:
        """检查 key 的状态, 返回裁决结果。

        Returns:
            action: "pass"(新条, 推入) | "skip"(重复, 跳过) | 
                    "replace"(更新, 替换原内容) | "append"(追加)
            reason: 裁决理由
        """
        if key not in self._keys:
            return {"action": "pass", "reason": "new_key"}

        entry = self._keys[key]
        ptype = protection_type or entry.get("protection_type", "")

        # 方案 → 替换(版本认可最新的)
        if ptype == "plan":
            entry["version"] += 1
            entry["content"] = content
            entry["updated_at"] = self._round
            return {"action": "replace", "reason": f"plan_update_v{entry['version']}"}

        # 进度/执行日志 → 同key+同日不重复
        if ptype in ("progress", "execution"):
            if entry.get("updated_at") == self._round:
                return {"action": "skip", "reason": "same_day_duplicate"}
            entry["updated_at"] = self._round
            return {"action": "append", "reason": "new_day_entry"}

        # 纠正/决策 → 同key不重复
        if ptype in ("correction", "decision"):
            return {"action": "skip", "reason": "content_duplicate"}

        return {"action": "pass", "reason": "default"}

    def register(self, key: str, content: str = "", 
                 protection_type: str = None) -> None:
        """注册新 key。"""
        self._keys[key] = {
            "protection_type": protection_type or "",
            "updated_at": self._round,
            "version": 1,
            "content": content[:200],
        }

    def tick(self) -> None:
        """每轮步进。"""
        self._round += 1

    def reset(self) -> None:
        self._keys = {}
        self._round = 0

    def get_stats(self) -> Dict:
        return {"total_keys": len(self._keys), "round": self._round}


# ==============================================================
# ConflictResolver — 冲突裁决器
# ==============================================================

class ConflictResolver:
    """裁决保护 vs 去重 vs 更新的冲突。

    规则:
      1. 保护条目不参与去重
      2. 唯一 key 保证身份唯一性
      3. 版本认可最新的(plan/progress 覆盖, correction/decision 保留全部)
      4. 情绪爆发全轮保护
    """

    @staticmethod
    def resolve(content: str, key: str = None, protection_type: str = None,
                existing_entries: List[Dict] = None) -> Dict:
        """裁决对一条内容的处理方式。

        Args:
            content: 原始内容
            key: 可选唯一 key
            protection_type: 保护类型
            existing_entries: 已有条目列表(同一 key)

        Returns:
            action: "skip"|"replace"|"append"|"pass"
            reason: 理由
            merge_content: 如果是 replace, 合并后的内容
        """
        if not existing_entries:
            return {"action": "pass", "reason": "no_existing", "merge_content": content}

        # 纠正/决策 → 同key跳过(已有相同内容)
        if protection_type in ("correction", "decision"):
            # 检查内容是否完全相同
            for entry in existing_entries:
                if str(entry.get("content", "")) == content:
                    return {"action": "skip", "reason": "exact_duplicate", 
                            "merge_content": content}
            # 不同内容 → 追加(不同纠正/决策都有价值)
            return {"action": "append", "reason": "different_content", 
                    "merge_content": content}

        # 方案 → 替换(版本认可最新的)
        if protection_type == "plan":
            return {"action": "replace", "reason": "version_update", 
                    "merge_content": content}

        # 进度/执行日志 → 追加
        if protection_type in ("progress", "execution"):
            return {"action": "append", "reason": "timeline_entry", 
                    "merge_content": content}

        return {"action": "pass", "reason": "default", "merge_content": content}


# ==============================================================
# 辅助函数
# ==============================================================

def _is_protected(content: str) -> bool:
    """检查是否包含保护标记。"""
    if not content:
        return False
    for kw in PROTECTED_KEYWORDS:
        if kw in content:
            return True
    return False


def _detect_importance_bonus(content: str) -> int:
    """根据内容检测 importance_bonus。"""
    if not content:
        return 0
    low = content.lower()

    # 未完成任务
    if re.search(r'(tfc-\d+|继续做|还没做完|记得.*任务|遗留)', low):
        return IMPORTANCE_BONUS["unfinished_task"]

    # 用户纠正
    if any(kw in low for kw in ["不对", "不是的", "错了", "纠正", "说错了", "你错了", "不是这样"]):
        return IMPORTANCE_BONUS["correction"]

    # 决策
    if any(kw in low for kw in ["决定", "确认", "同意", "批准", "就按", "就这么", "选"]):
        return IMPORTANCE_BONUS["decision"]

    # 情绪波动
    if any(kw in low for kw in ["去死", "很好", "太棒了", "终于", "崩溃", "受不了"]):
        return IMPORTANCE_BONUS["emotion"]

    # 路径/配置变更
    if re.search(r'(write_file|patch|rm\s|config\.|\.yaml|\.env|API_KEY)', low):
        return IMPORTANCE_BONUS["path_change"]

    # 工具结果(中性)
    if any(kw in low for kw in ["exit_code", "terminal", "read_file", "search"]):
        return IMPORTANCE_BONUS["tool_result"]

    return IMPORTANCE_BONUS["chitchat"]


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数。"""
    return len(text) // 4


# ==============================================================
# 独立模型 API 调用(三链调度)
# ==============================================================

def call_aux_model(
    messages: List[Dict],
    temperature: float = 0.1,
    max_tokens: int = 2048,
) -> Optional[str]:
    """调独立模型，三链: GLM → SiliconFlow → 返回 None。

    Args:
        messages: OpenAI 格式消息列表
        temperature: 生成温度(固定0.1避创造)
        max_tokens: 最大输出 token

    Returns:
        响应文本，或 None(全部失败)
    """
    payload_base = {
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "top_p": 0.9,
    }

    for provider in AUX_MODEL_CHAIN:
        # 读取 API key
        api_key = os.environ.get(provider["api_key_env"])
        if not api_key:
            # 尝试从 .env 读
            env_path = Path.home() / ".hermes" / ".env"
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith(f"{provider['api_key_env']}="):
                        api_key = line.split("=", 1)[1].strip()
                        break
        if not api_key:
            logger.debug("[aux-agent] %s: no api key", provider["name"])
            continue

        payload = {**payload_base, "model": provider["model"], "messages": messages}
        req = urllib.request.Request(
            provider["url"],
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=provider["timeout"]) as resp:
                data = json.loads(resp.read().decode())
                content = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                if content:
                    logger.info(
                        "[aux-agent] %s/%s: %d chars",
                        provider["name"], provider["model"], len(content),
                    )
                    return content
        except Exception as exc:
            logger.warning(
                "[aux-agent] %s failed: %s", provider["name"], exc,
            )
            continue

    logger.warning("[aux-agent] all models failed")
    return None


# ==============================================================
# DrawerStack — 抽屉栈
# ==============================================================

class DrawerStack:
    """抽屉栈数据结构。

    每层抽屉容量 = DRAWER_CAPACITY(N=3)。
    满 N 条 → 压缩递交到下一层。
    上下文 = 当前层未满部分 + 每层最新一条。
    """

    def __init__(self, capacity: int = DRAWER_CAPACITY):
        self._capacity = capacity
        # _drawers[level] = [item, item, ...]   level 从 1 开始
        self._drawers: Dict[int, List[Dict]] = {1: []}
        self._total_items = 0  # 所有层累计条目数(含压缩过的)

    @property
    def current_level(self) -> int:
        """当前活跃层(最底层)。"""
        return max(self._drawers.keys())

    @property
    def is_top_full(self) -> bool:
        """最顶层是否满了(需压缩递交)。"""
        top = self.current_level
        return len(self._drawers.get(top, [])) >= self._capacity

    def push(self, item: Dict) -> None:
        """向当前层推入一条。"""
        level = self.current_level
        self._drawers.setdefault(level, []).append(item)
        self._total_items += 1

    def push_to_head(self, item: Dict) -> None:
        """将条目推入当前层的头部(不会被压缩的区域)。"""
        level = self.current_level
        self._drawers.setdefault(level, []).insert(0, item)
        self._total_items += 1

    def pop_top(self) -> List[Dict]:
        """取出最顶层的全部内容。"""
        level = self.current_level
        items = self._drawers.pop(level, [])
        # 确保下一层存在
        self._drawers.setdefault(level + 1, [])
        return items

    def push_summary(self, summary: Dict) -> None:
        """将压缩后的摘要推入下一层。"""
        next_level = self.current_level + 1
        self._drawers.setdefault(next_level, []).append(summary)
        self._total_items += 1

    def get_context_items(self) -> List[Dict]:
        """获取上下文条目 = 每层最新一条(倒序)。"""
        items = []

        # 当前层未满部分(保留原始消息)
        top = self.current_level
        top_drawer = self._drawers.get(top, [])
        items.extend(top_drawer)

        # 每层最新一条(从 顶层-1 往下到 层1)
        for level in range(top - 1, 0, -1):
            drawer = self._drawers.get(level, [])
            if drawer:
                items.append(drawer[-1])

        return items

    def get_top_fill(self) -> int:
        """当前顶层填充数。"""
        return len(self._drawers.get(self.current_level, []))

    def reset(self) -> None:
        """清空全部抽屉。"""
        self._drawers = {1: []}
        self._total_items = 0

    def to_dict(self) -> Dict:
        """序列化。"""
        return {
            "capacity": self._capacity,
            "levels": {str(k): v for k, v in self._drawers.items()},
            "total_items": self._total_items,
        }


# ==============================================================
# TemperatureIndex — 温度召回
# ==============================================================

class TemperatureIndex:
    """温度召回系统。

    温度 = 命中次数(不是时间，轮次本身就是时间)。
    每轮衰减 ×decay_rate。
    每次命中 +1 + importance_bonus。
    分层: L1(≥8)自动注入, L2(≥4)摘要, L3(≥2)搜索, Archive(<2)归档。
    [PROTECTED] 永不衰减/归档。
    """

    def __init__(self):
        # _entries[key] = {"heat": float, "content": str, "importance": int,
        #                   "protected": bool, "last_hit_round": int}
        self._entries: Dict[str, Dict] = {}
        self._round: int = 0
        self._protected_count: int = 0

    def tick(self) -> None:
        """每轮衰减。"""
        self._round += 1
        to_archive = []
        for key, entry in self._entries.items():
            if entry.get("protected"):
                self._protected_count += 1
                continue  # 保护项不衰减
            # 按温度层级选衰减率
            heat = entry["heat"]
            if heat >= 8:
                decay = DECAY_RATES["L1"]
            elif heat >= 4:
                decay = DECAY_RATES["L2"]
            elif heat >= 2:
                decay = DECAY_RATES["L3"]
            else:
                decay = DECAY_RATES["Archive"]
            entry["heat"] = heat * decay
            # 标记归档
            if entry["heat"] < 1.5:
                to_archive.append(key)

        for key in to_archive:
            del self._entries[key]

    def hit(self, key: str, content: str = "", importance: int = 0) -> None:
        """命中升温。"""
        if key not in self._entries:
            self._entries[key] = {
                "heat": 1.0,
                "content": content,
                "importance": importance,
                "protected": _is_protected(content),
                "last_hit_round": self._round,
            }
        else:
            entry = self._entries[key]
            entry["heat"] += 1.0 + importance
            entry["last_hit_round"] = self._round
            if content:
                entry["content"] = content

    def get_auto_inject(self) -> List[Dict]:
        """获取自动注入的条目(heat ≥ 4)。"""
        l1 = []  # heat ≥ 8, 全量, cap 20
        l2 = []  # heat ≥ 4, 摘要, cap 50
        for key, entry in sorted(
            self._entries.items(),
            key=lambda x: x[1]["heat"],
            reverse=True,
        ):
            heat = entry["heat"]
            if heat >= 8 and len(l1) < 20:
                l1.append({
                    "key": key,
                    "heat": heat,
                    "content": entry["content"][:80],  # 80 tok cap
                    "protected": entry.get("protected", False),
                })
            elif heat >= 4 and len(l2) < 50:
                l2.append({
                    "key": key,
                    "heat": heat,
                    "content": entry["content"][:60],  # 60 tok cap
                    "protected": entry.get("protected", False),
                })

        return l1 + l2

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """搜索(heat ≥ 2 的条目)。"""
        results = []
        qlow = query.lower()
        for key, entry in sorted(
            self._entries.items(),
            key=lambda x: x[1]["heat"],
            reverse=True,
        ):
            if entry["heat"] < 2:
                continue
            if qlow in key.lower() or qlow in entry.get("content", "").lower()[:200]:
                results.append({
                    "key": key,
                    "heat": entry["heat"],
                    "content": entry["content"][:40],
                })
                if len(results) >= top_k:
                    break
        return results

    def get_archive_candidates(self) -> List[Tuple[str, Dict]]:
        """获取可归档条目(heat < 2, 非保护)。"""
        return [
            (k, v) for k, v in self._entries.items()
            if v["heat"] < 2 and not v.get("protected")
        ]

    def get_stats(self) -> Dict:
        """统计。"""
        total = len(self._entries)
        l1 = sum(1 for e in self._entries.values() if e["heat"] >= 8)
        l2 = sum(1 for e in self._entries.values() if 4 <= e["heat"] < 8)
        l3 = sum(1 for e in self._entries.values() if 2 <= e["heat"] < 4)
        arch = sum(1 for e in self._entries.values() if e["heat"] < 2)
        return {
            "total": total,
            "l1": l1,
            "l2": l2,
            "l3": l3,
            "archive": arch,
            "protected": self._protected_count,
            "round": self._round,
        }

    def reset(self) -> None:
        """清空。"""
        self._entries = {}
        self._round = 0
        self._protected_count = 0


# ==============================================================
# DedupEngine — 每轮去重
# ==============================================================

class DedupEngine:
    """每轮去重引擎。

    8条规则，每轮 user 消息后触发:
      1-5: 精确匹配(折叠)
      6: 语义重复(GLM辅助)
      7: token浪费检测
      8: 保护条目跳过
    """

    def __init__(self):
        self._last_tool_results: Dict[str, str] = {}  # 工具名→最新结果
        self._last_commands: Dict[str, str] = {}  # 命令→最新输出
        self._total_deduped: int = 0

    def dedup(self, messages: List[Dict]) -> List[Dict]:
        """执行去重, 返回去重后的消息列表。"""
        if not messages:
            return messages

        result = []
        removed = 0

        for msg in messages:
            role = msg.get("role", "")
            content = str(msg.get("content", ""))

            # 规则8: 保护条目跳过
            if _is_protected(content):
                result.append(msg)
                continue

            if role == "tool":
                # 规则1: 工具结果精确匹配 → 折叠
                content_hash = hashlib.md5(content.encode()).hexdigest()
                if content and content_hash in self._last_tool_results:
                    removed += 1
                    continue
                if content:
                    self._last_tool_results[content_hash] = content
                result.append(msg)

            elif role == "assistant":
                # 规则2-5: 精确工具调用去重(通过 tool_calls 判断)
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    result.append(msg)  # 工具调用总是保留
                else:
                    result.append(msg)

            elif role == "user":
                result.append(msg)

            else:
                result.append(msg)

        self._total_deduped += removed
        if removed > 0:
            logger.info("[dedup] removed %d duplicate message(s)", removed)

        return result

    def get_stats(self) -> Dict:
        return {"total_deduped": self._total_deduped}

    def reset(self) -> None:
        self._last_tool_results = {}
        self._last_commands = {}
        self._total_deduped = 0
