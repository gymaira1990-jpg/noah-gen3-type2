# 抽屉级联压缩引擎 · API 参考

> **完整的公开接口文档**
>
> 本文档记录了所有可调用组件的构造方法、方法签名和返回值。
> 覆盖 Tier1(drawer_engine) + Tier2(memory-butler) + Tier3(context-assembler)。

---

## Tier 1: 抽屉引擎 (`drawer_engine.py`)

### NoiseFilter

纯正则噪音过滤器。零 LLM，零依赖。

```python
class NoiseFilter:

    @staticmethod
    def classify(text: str) -> str:
        """
        分类输入文本。
        
        Returns:
            "chitchat" — 寒喧/确认/废话
            "command"  — 元命令 (/compress, /status)
            "content"  — 有效内容
        """

    @staticmethod
    def is_noise(text: str) -> bool:
        """
        快速判断是否为噪音。
        
        Returns:
            True  — 是噪音，不计轮数、不入抽屉
            False — 有效内容
        """
```

**噪音模式**（`NOISE_PATTERNS`）：
```
单字确认: ^[好嗯是okOK行可]$
短确认: ^明白了?$ / ^知道了?$ / ^收到$ / ^了解$
元命令: ^/compress / ^/status / ^/new / ^/reset
分隔符: ^[-=*]{3,}$
纯标点: ^[。，！？\.,!\?\s]{1,10}$
```

---

### ProtectionDetector

7 类保护信号自动识别。纯正则，零 LLM。

```python
class ProtectionDetector:

    @staticmethod
    def detect(text: str) -> dict:
        """
        检测内容是否需要保护。
        
        Args:
            text: 用户消息文本
        
        Returns:
            {
                "protected": bool,        # 是否受保护
                "protection_type": str|None,  # 保护类型
                "key": str|None,           # 唯一 key
                "importance_bonus": int,   # 重要性加分
            }
        
        protection_type 可能的值:
            "hard"       — 硬保护标记 (__HERMES_SOUL_PROTECTED__)
            "emotion"    — 情绪爆发 (去死/永久离线)
            "plan"       — 方案/设计/架构
            "progress"   — 进度/完成/待办
            "execution"  — 执行日志 (改了/部署了/写了)
            "decision"   — 决策 (决定/确认/同意)
            "correction" — 纠正 (不对/错了/不是)
            "tfc_ref"    — 任务引用 (TFC-xxx/NCP-xxx)
        """
```

**保护信号模式**（`PROTECT_SIGNAL_PATTERNS`）：

| 类型 | 检测模式 |
|:-----|:---------|
| plan | `(设计|方案|架构|计划)\s*[:：]` |
| progress | `(当前|完成|剩余|进度)`, `下一步`, `TODO` |
| execution | `(执行|部署|配置|安装|修改|改动了|写了|创建了)` |
| decision | `(决定|确认|同意|批准|就按|就这么选)` |
| correction | `(不对|不是的|错了|纠正|说错了|你错了)` |
| tfc_ref | `(TFC|NCP|PRJ)-\d+` |
| emotion | `(去死|永久离线|最后机会|滚|崩溃)` |

---

### UniqueKeyIndex

Key 身份管理。保证同一实体不重复推入。

```python
class UniqueKeyIndex:

    def __init__(self):
        """初始化空索引。"""

    def check(self, key: str, content: str = "", 
              protection_type: str = None) -> dict:
        """
        检查 key 的当前状态。
        
        Args:
            key: 唯一 key (如 "plan:抽屉级联引擎")
            content: 当前内容
            protection_type: 保护类型
        
        Returns:
            {
                "action": "pass"|"skip"|"replace"|"append",
                "reason": str  # 决策理由
            }
        
        action 说明:
            "pass"    — 新 key, 可以推入
            "skip"    — 重复 key, 跳过
            "replace" — 旧 key 有新内容, 替换
            "append"  — 同 key 追加新内容
        """

    def register(self, key: str, content: str = "",
                 protection_type: str = None) -> None:
        """注册新 key。"""

    def tick(self) -> None:
        """每轮步进（增加回合计数）。"""

    def reset(self) -> None:
        """清空索引（新会话时调用）。"""

    def get_stats(self) -> dict:
        """返回统计信息。"""
```

**更新策略矩阵**：

| 类型 | 策略 |
|:-----|:-----|
| plan | 原地替换（版本认可最新的） |
| progress | 追加（同 key+同日不重复） |
| execution | 追加（同 key+同日不重复） |
| correction | 跳过（同 hash 不重复） |
| decision | 跳过（同 hash 不重复） |
| completed | 跳过（一次性，不更新） |

---

### ConflictResolver

保护 vs 去重 vs 更新裁决器。

```python
class ConflictResolver:

    @staticmethod
    def resolve(content: str, key: str = None,
                protection_type: str = None,
                existing_entries: list[dict] = None) -> dict:
        """
        裁决对一条内容的处理方式。
        
        Returns:
            {
                "action": "skip"|"replace"|"append"|"pass",
                "reason": str,
                "merge_content": str
            }
        """
```

---

### DrawerStack

核心数据结构。抽屉级联容器。

```python
class DrawerStack:

    def __init__(self, capacity: int = 3):
        """
        Args:
            capacity: 每层抽屉容量 (2-10)
        """

    @property
    def current_level(self) -> int:
        """当前活跃层号（从 1 开始）。"""

    @property
    def is_top_full(self) -> bool:
        """最顶层是否已满。"""

    def push(self, item: dict) -> None:
        """向当前层推入一条消息。"""

    def push_to_head(self, item: dict) -> None:
        """推入当前层头部（保护条目用，不会被压缩）。"""

    def pop_top(self) -> list[dict]:
        """取出最顶层全部内容，并创建下一层。"""

    def push_summary(self, summary: dict) -> None:
        """将压缩摘要推入下一层。"""

    def get_context_items(self) -> list[dict]:
        """
        获取上下文条目。
        
        返回顺序:
            1. 当前层未满部分（原始消息，全量）
            2. 每层最新一条摘要（从顶层-1 往下到 1 层）
        
        不会返回:
            - 非最新摘要（每层只有最新一条）
            - 已被压缩的原始消息
        """

    def get_top_fill(self) -> int:
        """当前层已填充数量。"""

    def reset(self) -> None:
        """清空全部抽屉（新会话）。"""

    def to_dict(self) -> dict:
        """序列化为 dict。"""
```

---

### TemperatureIndex

温度 = 命中次数。每轮衰减。

```python
class TemperatureIndex:

    def __init__(self):
        """初始化空温度索引。"""

    def tick(self) -> None:
        """
        每轮衰减。
        保护条目不衰减。
        热度 < 1.5 的条目自动移除。
        """

    def hit(self, key: str, content: str = "", 
            importance: int = 0) -> None:
        """
        命中升温。
        
        Args:
            key: 标识符
            content: 关联内容
            importance: 重要性加分 (0-∞)
        """

    def get_auto_inject(self) -> list[dict]:
        """
        获取自动注入条目 (heat ≥ 4)。
        
        Returns:
            L1 (heat ≥ 8, cap 20) + L2 (heat ≥ 4, cap 50)
            每个条目: {key, heat, content, protected}
        """

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        关键词搜索 (heat ≥ 2)。
        
        Args:
            query: 搜索词
            top_k: 返回条数上限
        """

    def get_archive_candidates(self) -> list[tuple]:
        """获取可归档条目 (heat < 2, 非保护)。"""

    def get_stats(self) -> dict:
        """
        统计。
        
        Returns:
            {total, l1, l2, l3, archive_count, protected_count, round}
        """
```

---

### call_aux_model

独立辅助模型三链调度。

```python
def call_aux_model(
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = 2048,
) -> str | None:
    """
    调辅助模型做摘要/分类。
    
    Args:
        messages: OpenAI 格式消息
        temperature: 固定 0.1 避创造
        max_tokens: 最大输出
    
    Returns:
        响应文本，或 None（全部失败时）
    
    调度链:
        1. GLM-4-Flash (智谱, 免费, ~1s)
        2. Qwen3-8B (硅基, 免费, ~6s)
        3. 返回 None（降级为关键词提取）
    
    注意: 此函数直接调用外部 API，不通过框架 LLM 路由。
    """
```

---

## Tier 2: 记忆管家 (`memory_butler/__init__.py`)

### MemoryButler

```python
class MemoryButler:

    def __init__(self, call_aux_model_fn):
        """
        Args:
            call_aux_model_fn: 辅助模型调用函数
                签名: fn(messages=[...], temperature=0.1, max_tokens=512) -> str|None
        """

    def tick(self, drawer_items: list[dict], user_message: str = "") -> None:
        """
        每 N 轮触发一次管家处理。
        
        Args:
            drawer_items: 当前抽屉条目 (drawer.get_context_items())
            user_message: 本轮用户消息
        
        触发条件:
            - enabled = True
            - 距上次触发 >= trigger_interval_rounds (默认 5)
        
        处理内容:
            1. 渐进摘要（检测方案名 → 增量更新 PG）
            2. 执行日志保护（检测操作 → 写入 PG）
            3. 重复检测（TFC 引用 → 比对历史）
        """

    def get_stats(self) -> dict:
        """
        返回统计:
        {summaries_created, summaries_updated, execution_logs_saved,
         tasks_archived, duplicates_found}
        """

    def get_perf_stats(self) -> dict:
        """
        返回性能指标:
        {cycles_run, total_duration_ms, avg_duration_ms, last_duration_ms,
         pg_writes_ok, pg_writes_fail, glm_calls, glm_errors}
        """

    def reset(self) -> None:
        """新会话重置（清空统计）。"""
```

### progressive_summarize

```python
def progressive_summarize(
    project_name: str,
    new_dialogue: str,
    call_aux_model_fn,
    existing_summary: str | None = None,
) -> str:
    """
    渐进摘要。
    
    有旧摘要 → 增量更新（不删除已有，只添加新信息）
    无旧摘要 → 新建结构化摘要
    
    Returns:
        生成的摘要文本
    """
```

### extract_execution_log

```python
def extract_execution_log(content: str) -> dict | None:
    """
    从文本提取执行日志。
    
    Args:
        content: 用户消息文本
    
    Returns:
        {
            "text": str,          # 匹配的执行日志行
            "category": "execution_log",
            "tfc_ref": list[str] | None  # 关联 TFC 编号
        }
        或 None（无匹配）
    """
```

### archive_completed_task

```python
def archive_completed_task(
    tfc_id: str,
    related_summaries: list[str],
    call_aux_model_fn,
) -> str | None:
    """
    将已完成任务压缩为最终归档摘要。
    
    Args:
        tfc_id: 任务编号
        related_summaries: 相关对话摘要列表
        call_aux_model_fn: 辅助模型函数
    
    Returns:
        最终摘要文本 (300-500 tok) 或 None
    """
```

---

## Tier 3: 上下文组装器 (`context_assembler.py`)

### assemble_context

```python
def assemble_context(
    drawer_items: list[dict],
    user_message: str = "",
    project_refs: list[str] | None = None,
) -> str:
    """
    组装精炼上下文。
    
    Args:
        drawer_items: Tier1 抽屉条目 (drawer.get_context_items())
        user_message: 当前用户消息（用于向量搜索）
        project_refs: 关联项目引用 (TFC/NCP 编号)
    
    Returns:
        精炼上下文字符串 (< max_tokens tok)
    
    组装公式:
        [目标声明] + [Tier1 抽屉摘要] + [Tier2 项目摘要]
        + [向量搜索结果] + [执行日志]
    
    不注入:
        - 已完成任务全文
        - 归档方案
        - 寒喧历史
        - 无关项目资料
    """
```

### get_assembler_stats

```python
def get_assembler_stats() -> dict:
    """
    返回性能指标:
    {calls, total_duration_ms, avg_duration_ms, last_duration_ms,
     vec_searches, vec_search_fail, total_tokens_produced, avg_tokens,
     sections_avg}
    """
```

### ASSEMBLER_CONFIG

```python
ASSEMBLER_CONFIG = {
    "max_tokens": 13000,        # 组装上下文上限
    "reserve_tokens": 2000,     # 预留空间
    "vec_search_top_k": 5,      # 向量搜索返回条数
    "pg_conn": "psql ...",      # 数据库连接字符串（可替换）
}
```

### reload_config

```python
def reload_config() -> None:
    """
    从外部配置源重载配置。
    
    默认实现: 从 YAML 文件读取 assembler: 配置段。
    可重写为从你的配置系统读取。
    """
```

---

## 数据流接口总结

### 输入

| 方向 | 数据 | 类型 | 来源 |
|:-----|:-----|:-----|:-----|
| → | user_message | `str` | 用户输入 |
| → | messages | `list[dict]` | 对话历史 (OpenAI 格式) |
| → | prompt_tokens | `int` | API 返回的 token 用量 |

### 内部传递

| 组件间 | 数据 | 格式 |
|:-------|:-----|:-----|
| NoiseFilter → DrawerStack | 噪音标记 | 返回值: `"chitchat"` / `"command"` / `"content"` |
| ProtectionDetector → DrawerStack | 保护标记 | msg 字段: `_protected: bool`, `_protection_type: str` |
| DrawerStack → MemoryButler | 抽屉条目 | `drawer_items: list[dict]` (`get_context_items()`) |
| DrawerStack → ContextAssembler | 抽屉条目 | `drawer_items: list[dict]` (`get_context_items()`) |
| MemoryButler → PG | 知识条目 | `(title, content, category, tags)` |
| ContextAssembler → PG | 查询 | SQL: 向量搜索 / 全文搜索 |

### 输出

| 方向 | 数据 | 类型 | 用途 |
|:-----|:-----|:-----|:-----|
| ← | compressed | `list[dict]` | 压缩后的消息列表（给 LLM） |
| ← | context | `str` | 精炼上下文（组装后系统消息） |
| ← | stats | `dict` | 性能指标（监控用） |
