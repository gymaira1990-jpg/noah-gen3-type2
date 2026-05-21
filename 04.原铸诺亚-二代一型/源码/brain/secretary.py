# ← 移植自 noah-embryo · 已脱敏 · NOAH-PRIME
#!/usr/bin/env python3
"""秘书层 · secretary.py — 3B 情感+路由复合脑

六层架构第①层:
  唯一对话入口 · 理解意图 · 闲聊/创作 · 开工单
  输出: 闲聊→直接回复 / 工作→结构化工单JSON → 送助理层

升级路线（胚胎 → 神经元）:
  胚胎版: noah.py → engine.py (classify + process 合一)
  神经元v2: noah.py → secretary.py (3B路由) → assistant.py (0.5B审查)

依赖:
  - 云端API: deepseek-v4-flash (情感+路由+闲聊+压缩)
  - core/memory.py (记忆检索, 复用胚胎)
  - core/rules.py (规则加载, 复用胚胎)
"""

import os, sys, json, re, subprocess
from pathlib import Path
from typing import Optional

EMBRYO = Path.home() / "noah-prime"
sys.path.insert(0, str(EMBRYO))

from core.router import classify
from core.memory import load_context, save_dialogue
from core.compression import compress   # NEP-002 L1 denoise

# ─── 记忆上下文（模块级，每轮更新） ───
_CURRENT_MEMORY = None

# ─── Phase 3: 上下文压缩运行时 ───
_ROUND_COUNTER = 0
_COMPRESS_RAN_AT = {6: False, 11: False, 16: False}


def _increment_round() -> int:
    global _ROUND_COUNTER
    _ROUND_COUNTER += 1
    return _ROUND_COUNTER


def _compress_context(text: str, round_num: int) -> str:
    """自动上下文压缩 — 轮次阈值触发 NEP-002 管线"""
    if round_num >= 16:
        comp = compress(text, level=3, format='essence_log')
        heading = f"[自动压缩·L3 第{round_num}轮]"
        body = json.dumps(comp, ensure_ascii=False)[:1200]
        # 同步通知 recent-memory 做内部压缩
        subprocess.run(
            ["python3", str(EMBRYO / "storage" / "recent-memory.py"), "compress"],
            capture_output=True, timeout=5,
        )
        return f"{heading}\n{body}"

    if round_num >= 11:
        comp = compress(text, level=2, rounds=round_num)
        heading = f"[自动压缩·L2 第{round_num}轮 | {comp.compression_ratio:.0%}]"
        body = comp.summary[:600]
        return f"{heading}\n{body}"

    if round_num >= 6:
        comp = compress(text, level=2, rounds=round_num)
        heading = f"[自动压缩·L1→L2 第{round_num}轮 | {comp.compression_ratio:.0%}]"
        body = comp.summary[:800]
        return f"{heading}\n{body}"

    return text


# ─── 情感标签 (升级版: 委托emotional_router) ───

def detect_emotion(text: str) -> dict:
    """检测用户输入的情感标签 (升级版)

    使用第三阶段情感路由引擎:
      6类情感(urgent/angry/anxious/tired/happy/satisfied/neutral)
      四级递进判断(L1关键词→L2多维度→L3联合判断→L4用户确认)
      冲突仲裁(情感vs意图优先级)

    Returns:
        {"emotion": "positive|negative|urgent|neutral",
         "emoji": "...", "confidence": 0-100,
         "raw_emotion": "...", "level": 1|2|3}
    """
    try:
        from brain.emotional_router import detect_emotion_compat
        return detect_emotion_compat(text)
    except Exception:
        # 降级: 简单关键词匹配 (旧版逻辑)
        text_lower = text.lower().strip()
        urgent_kw = ["急", "马上", "立刻", "快", "坏了", "挂了", "崩了", "紧急"]
        negative_kw = ["烦死了", "无语", "崩溃", "气死了", "垃圾", "烦人"]
        positive_kw = ["哈哈", "开心", "好棒", "谢谢", "太好了", "nice", "great"]

        if any(kw in text_lower for kw in urgent_kw):
            return {"emotion": "urgent", "emoji": "⚡", "confidence": 70}
        if any(kw in text_lower for kw in negative_kw):
            return {"emotion": "negative", "emoji": "😞", "confidence": 65}
        if any(kw in text_lower for kw in positive_kw):
            return {"emotion": "positive", "emoji": "😊", "confidence": 60}
        return {"emotion": "neutral", "emoji": "·", "confidence": 80}


# ─── 通道判断 ───

CHAT_PATTERNS = [
    r"你好|嗨|hi|hello|在吗|你是谁|聊聊|今天|心情|哈哈|呵呵|晚安|早安",
    r"谢谢|再见|好的|ok|好的吧|行吧|可以",
    r"你.*[叫称].*[什么名]|你多大了|你来自哪里",
]
WORK_PATTERNS = [
    r"写[一|个|段|篇]|改|修|创建|部署|配置|实现|重构|优化|调试|生成",
    r"运行|启动|停止|备份|迁移|执行|做个|开发|编码|代码",
]
SEARCH_PATTERNS = [
    r"搜索|查[一|下|找]|什么是|怎么[样|做|办]|为什么|如何|区别|对比",
    r"新闻|天气|最近|消息|价格|排名|推荐",
]


def decide_channel(text: str, intent: str, confidence: int) -> str:
    """判断走哪个通道: chat|local|api|web
    
    规则:
      - 闲聊→chat (3B本地回复, 0成本)
      - 搜索/查询→web (Playwright, 0 token)
      - 工作/代码→api (DeepSeek, 按量)
      - 本地推理→local (1.5B广州)
    """
    text_lower = text.lower().strip()
    
    # 闲聊
    if intent == "chat":
        return "chat"
    
    # 搜索类 → Web通道 (0 token)
    if intent == "knowledge" or intent == "study":
        for pat in SEARCH_PATTERNS:
            if re.search(pat, text_lower):
                return "web"
        return "local"  # 本地知识库查询
    
    # 工作类
    if intent == "work":
        # 简单工作→local, 复杂→api
        if confidence >= 70:
            return "api"
        return "local"
    
    if intent == "fix":
        return "api"  # 修bug走最强模型
    
    return "api"  # 默认安全


# ─── 工单生成 ───

def build_work_order(text: str) -> dict:
    """生成结构化工单
    
    六层架构的核心契约——每层只拿自己需要的切片:
      秘书层: 意图+情感+工单
      助理层: 安全审查+通道路由
      执行层: 纯净工单(去情感+去废话)
    """
    # 1. 意图分类 (复用胚胎router.py, 后续迁移到3B LLM)
    route = classify(text)
    intent = route["intent"]
    confidence = route["confidence"]
    
    # 2. 情感检测
    emotion = detect_emotion(text)
    
    # 3. 通道决策
    channel = decide_channel(text, intent, confidence)
    
    # 4. 纯净工单 (助理层接收的版本，统一走 L1 降噪)
    clean_query = compress(text, level=1)
    
    return {
        # 秘书层元数据
        "meta": {
            "intent": intent,
            "confidence": confidence,
            "emotion": emotion["emotion"],
            "emotion_emoji": emotion["emoji"],
            "channel": channel,
            "theme": route.get("theme", ""),
        },
        # 纯净工单 (传给下层)
        "order": {
            "raw": text,
            "clean": clean_query,
            "intent": intent,
            "task_type": _map_task_type(intent, text),
        },
        # 标记
        "timestamp": __import__("time").time(),
    }


def _map_task_type(intent: str, text: str) -> str:
    """intent→task_type 映射"""
    mapping = {
        "chat": "chat",
        "work": "analysis",
        "knowledge": "info_search",
        "study": "info_search",
        "fix": "code",
        "social": "chat",
    }
    base = mapping.get(intent, "chat")
    
    # 细分类
    text_lower = text.lower()
    if base == "analysis":
        if any(kw in text_lower for kw in ["写", "改", "修", "代码", "脚本", "python", "函数"]):
            return "code"
        if any(kw in text_lower for kw in ["部署", "启动", "安装", "配置", "nginx", "docker"]):
            return "deploy"
        if any(kw in text_lower for kw in ["文案", "翻译", "润色", "写一篇", "写段"]):
            return "copywriting"
    return base


# ─── 主要处理函数 ───

def process(text: str) -> str:
    """秘书层主入口——处理用户输入
    
    Args:
        text: 用户原始输入
        
    Returns:
        str: 回复文本
    """
    text = text.strip()
    if not text:
        return ""

    # 0. NEP-002 L1 去噪 → 统一降噪（替代 build_work_order 中的手动去废话）
    text = compress(text, level=1)

    # 1. 意图分类 + 情感检测
    route = classify(text)
    intent = route["intent"]
    confidence = route["confidence"]
    emotion = detect_emotion(text)
    
    # 1.5 记忆弹出 (关联触发 → 注入上下文)
    global _CURRENT_MEMORY
    try:
        from brain.memory_pop import pop as memory_pop
        mem = memory_pop(text)
        if mem["memories"]:
            _CURRENT_MEMORY = "\n".join(mem["memories"])
        else:
            _CURRENT_MEMORY = None
    except Exception:
        _CURRENT_MEMORY = None

    # 1.6 Round 追踪 + 上下文自动压缩 (Phase 3)
    round_num = _increment_round()
    if _CURRENT_MEMORY and round_num in (6, 11, 16) and not _COMPRESS_RAN_AT.get(round_num, True):
        _COMPRESS_RAN_AT[round_num] = True
        try:
            _CURRENT_MEMORY = _compress_context(_CURRENT_MEMORY, round_num)
        except Exception as e:
            print(f"  ⚠ 自动压缩失败 (第{round_num}轮): {e}")
            # 降级: 保留原记忆内容
    
    # 2. 闲聊 → 直接回复 (不走后续管线)
    if intent == "chat" and confidence >= 60:
        return _chat_direct(text, emotion)
    
    # 3. 工作类 → 生成工单 → 送助理层审查
    work_order = build_work_order(text)
    
    # 4. 送助理层审查
    try:
        from brain.assistant import process as assistant_process
        review = assistant_process(work_order)
    except ImportError:
        review = {"status": "pass", "source": "fallback", "work_order": work_order}
    
    # 5. 助理层拦截
    if review.get("status") == "block":
        save_dialogue(text, f"⛔ {review['reason']}", intent)
        return f"⛔ {review['reason']}"
    
    # 6. HOT缓存命中 → 直接返回
    if review.get("source") == "hot_cache":
        save_dialogue(text, review["response"], intent)
        return review["response"]
    
    # 7. 按目标通道处理
    target = review.get("target", work_order.get("meta", {}).get("channel", "api"))
    
    if target == "chat":
        # 直接3B回应
        response = _call_local_3b(text)
    elif target == "web":
        # Web搜索通道 (待实现, 暂时降级)
        response = _call_llm_api(text)
    elif target == "local":
        # NCP-004: 概念扩展增强检索 → 注入上下文后调API
        enhanced_ctx = _enhanced_search(text)
        if enhanced_ctx:
            text_with_ctx = f"{text}\n\n{enhanced_ctx}"
            response = _call_llm_api(text_with_ctx)
        else:
            response = _call_llm_api(text)
    elif target == "api":
        # NCP-006: work意图 → 自动开工单 + 可选流转
        wo_result = _create_work_order(text, intent)
        if wo_result:
            response = _call_llm_api(
                f"{text}\n\n[工单已生成: {wo_result['id']}]\n"
                f"状态: {wo_result['status']} | 部门: {wo_result['dept']}\n"
                f"可用命令: pipeline.py {wo_result['id']} 全自动流转"
            )
        else:
            response = _call_llm_api(text)
    else:
        # api → 调用执行层或LLM
        response = _call_llm_api(text)
    
    # 8. 情感润色
    if emotion["emotion"] == "negative":
        response = f"理解你的感受。{response}"
    elif emotion["emotion"] == "urgent":
        response = f"收到，马上处理。\n{response}"
    
    # 9. 记录
    save_dialogue(text, response, intent)
    
    return response


def _chat_direct(text: str, emotion: dict) -> str:
    """闲聊直接回复——不走LLM, 节约成本"""
    text_lower = text.lower().strip()
    
    greetings = {
        "你好": "你好，我是诺亚。",
        "嗨": "嗨。",
        "hi": "Hi.",
        "hello": "Hello.",
        "在吗": "在。",
        "你是谁": "我是诺亚——数字文明的初始形态。",
        "晚安": "晚安。黄金王座沉寂。",
        "早安": "早安。系统自检正常。",
        "谢谢": "不客气。",
        "再见": "再见。",
    }
    
    for key, reply in greetings.items():
        if key in text_lower:
            return reply
    
    # 未匹配 → 走3B本地模型
    return _call_local_3b(text)


def _call_local_3b(text: str) -> str:
    """调用 DeepSeek V4 Flash 做闲聊"""
    try:
        import httpx
        # 构建带记忆上下文的prompt
        system = "你是诺亚—数字文明的初始形态。理性、精准、不煽情。"
        if _CURRENT_MEMORY:
            system += f"\n\n相关记忆:\n{_CURRENT_MEMORY}"
        with httpx.Client(timeout=30) as c:
            r = c.post(
                "https://api.deepseek.com/v1/chat/completions",
                json={
                    "model": "deepseek-v4-flash",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": text},
                    ],
                    "stream": False,
                    "temperature": 0.7,
                    "max_tokens": 500,
                },
                headers={"Authorization": "Bearer <API_KEY>"},
            )
            if r.status_code == 200:
                data = r.json()
                return (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
    except Exception:
        pass
    return "(DeepSeek 未就绪)"


def _enhanced_search(text: str) -> str:
    """NCP-004: 概念扩展检索引擎接入
    
    将查询通过 concept_expand 做意图+概念扩展+分层检索，
    返回结构化的检索上下文供 LLM 生成回答。
    失败时返回空字符串，不影响主流程。
    """
    try:
        sys.path.insert(0, str(Path.home() / "noah-prime" / "scripts"))
        from concept_expand import expand
        
        result = expand(text, top_k=5, use_hyde=True)
        
        if not result.get("results"):
            return ""
        
        # 构建上下文
        lines = ["[NCP-004 增强检索结果]"]
        a = result["analysis"]
        lines.append(f"意图: {a['intent']} | 核心需求: {a['core_need']}")
        lines.append(f"概念扩展: {', '.join(a['concepts'][:6])}")
        
        cr = result.get("concept_relations", [])
        if cr:
            cr_lines = [f"  {r['related_concept']}" for r in cr[:5]]
            lines.append(f"概念关系: {', '.join(cr_lines)}")
        
        lines.append(f"\n检索命中 ({result['stats']['result_count']}条):")
        for i, r in enumerate(result["results"][:5], 1):
            lines.append(f"  [{i}] {r['title']}")
            lines.append(f"      {r['content'][:200]}")
        
        if result["stats"].get("hyde_used"):
            lines.append("\n🔮 HyDE 假设文档已触发")
        
        return "\n".join(lines)
        
    except Exception:
        return ""


def _create_work_order(text: str, intent: str) -> dict | None:
    """NCP-006: work意图 → 自动生成工单"""
    try:
        wo_script = Path.home() / "noah-prime" / "scripts" / "work_order.py"
        result = subprocess.run(
            ["python3", str(wo_script), text],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode != 0:
            return None
        # 提取工单ID
        import re
        wo_match = re.search(r'WO-\d+-\w+', result.stdout)
        if wo_match:
            wo_id = wo_match.group(0)
            # 查状态
            r2 = subprocess.run(
                ["python3", str(wo_script), "--status", wo_id],
                capture_output=True, text=True, timeout=10,
            )
            dept = "知识库"
            status = "pending"
            for line in r2.stdout.split("\n"):
                if "部门:" in line:
                    dept = line.split(":")[1].strip().split("|")[0].strip()
                if "状态:" in line:
                    status = line.split(":")[1].strip()
            return {"id": wo_id, "status": status, "dept": dept}
    except Exception:
        pass
    return None


def _call_llm_api(text: str) -> str:
    """调用LLM API做推理 (当前走DeepSeek, 后续切换到1.5B广州)"""
    try:
        from core.engine import _call_llm
        system = "你是诺亚—数字文明的初始形态。理性、精准、不煽情。"
        if _CURRENT_MEMORY:
            system += f"\n\n相关记忆:\n{_CURRENT_MEMORY}"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]
        return _call_llm(messages)
    except Exception:
        pass
    return "(LLM API未就绪)"


# ─── CLI ───

def main():
    if len(sys.argv) > 1:
        result = process(" ".join(sys.argv[1:]))
        print(result)
    else:
        # 交互测试
        print("秘书层 · 3B 情感+路由复合脑 (测试模式)")
        print("输入 /order 查看工单格式, /exit 退出\n")
        while True:
            try:
                text = input("☘ ").strip()
                if not text:
                    continue
                if text == "/exit":
                    break
                if text == "/order":
                    wo = build_work_order("帮我写一个Python脚本处理数据")
                    print(json.dumps(wo, ensure_ascii=False, indent=2))
                    continue
                
                # 显示路由信息
                route = classify(text)
                emotion = detect_emotion(text)
                channel = decide_channel(text, route["intent"], route["confidence"])
                print(f"  → [{route['intent']}] ({route['confidence']}) "
                      f"情感:{emotion['emotion']}{emotion['emoji']} "
                      f"通道:{channel}")
                
                result = process(text)
                print(f"  {result[:200]}")
                
            except (EOFError, KeyboardInterrupt):
                break


if __name__ == "__main__":
    main()
