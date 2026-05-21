#!/usr/bin/env python3
"""路由分类器 · router.py

原铸诺亚的意图分类模块。
从 noah-embryo 移植，适配原铸独立环境。

用法:
    from core.router import classify
    result = classify("帮我写一段Python代码")
"""

import re

# ─── 意图模式 ───

CHAT_PATTERNS = [
    (r"你好|嗨|hi|hello|在吗|你是谁|聊聊|今天|心情", "chat"),
    (r"谢谢|再见|好的|ok|好的吧|行吧|可以", "chat"),
    (r"你.*叫.*什么|你多大了|你来自", "chat"),
    (r"哈哈|呵呵|晚安|早安", "chat"),
]

WORK_PATTERNS = [
    (r"写[一个段篇]|改|修|创建|部署|配置|实现|重构|优化|调试|生成", "work"),
    (r"运行|启动|停止|备份|迁移|执行|开发|编码|代码", "work"),
    (r"做个|搞个|搭个|整个|写个", "work"),
]

KNOWLEDGE_PATTERNS = [
    (r"搜索|查[一下找]|什么是|怎么也办]|为什么|如何|区别|对比", "knowledge"),
    (r"新闻|天气|最近|消息|价格|排名|推荐|介绍", "knowledge"),
    (r"定义|概念|原理|教程|指南|文档|API", "knowledge"),
]

FIX_PATTERNS = [
    (r"报错|错误|bug|故障|坏了|挂了|崩了|崩溃|异常|修复|修一下", "fix"),
    (r"不工作了|出问题了|有问题|不对劲", "fix"),
]


def classify(text: str) -> dict:
    """意图分类主入口

    Args:
        text: 用户输入文本

    Returns:
        {"intent": "chat|work|knowledge|fix",
         "confidence": 0-100,
         "theme": "..."}
    """
    text_lower = text.lower().strip()

    # 先查修复
    for pat, intent in FIX_PATTERNS:
        if re.search(pat, text_lower):
            return {"intent": intent, "confidence": 80, "theme": "fix"}

    # 工作
    for pat, intent in WORK_PATTERNS:
        if re.search(pat, text_lower):
            return {"intent": intent, "confidence": 75, "theme": "work"}

    # 知识
    for pat, intent in KNOWLEDGE_PATTERNS:
        if re.search(pat, text_lower):
            return {"intent": intent, "confidence": 70, "theme": "knowledge"}

    # 闲聊
    for pat, intent in CHAT_PATTERNS:
        if re.search(pat, text_lower):
            return {"intent": intent, "confidence": 85, "theme": "chat"}

    # 默认
    return {"intent": "chat", "confidence": 50, "theme": "general"}
