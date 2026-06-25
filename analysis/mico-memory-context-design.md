# mico 三层记忆系统与上下文治理设计

> 日期：2026-06-25  
> 状态：当前优先设计，作为下一阶段实现依据  
> 作者角色：Claude Code 可负责初稿实现；上下文策略、记忆边界和安全策略由 Codex 审查定稿  
> 范围：三层记忆系统 + 任务内上下文治理  
> 参考：`pico/analysis/memory-and-context-management.md`、`claude-code/analysis/memory-and-context-management.md`

---

## 〇、当前决策

mico 当前最主要目标是让记忆系统**切实可用**，支撑以下真实需求：

- 记住用户偏好、项目约定、关键决策等稳定信息。
- 在后续任务中自动带入相关上下文。
- 在同一 session 的多个 run 之间，模型能自动积累对文件和任务的理解，不需要用户每次说"记住"。
- 在长任务里避免重复读文件、重复塞历史、prompt 无控制膨胀。

新设计采用 **pico 式三层记忆**，持久记忆层使用固定 topic：

```text
Working Memory（session 内，每轮注入，SessionStore 持久化）
        +
Episodic Notes（session 内，按需召回 top-3，自动积累）
        +
Durable Memory（跨 session，固定 topic，.mico/memory/*.md）
        +
ContextManager（预算、压缩、section 组装）
```

仍然不做 embedding，不做后台子代理记忆抽取，不做远程 memory store。

---

## 一、设计原则

1. **三层分离，职责不重叠**
   - Working Memory：当前任务的"仪表盘"，每轮优先注入；预算极端紧张时只能压缩 file summaries/recent files，不能删除 task_summary。
   - Episodic Notes：模型自动积累的临时观察，session 内跨 run 存活，按需召回。
   - Durable Memory：用户显式要求"记住"的稳定事实，跨 session 持久化。

2. **固定 topic，可控膨胀**
   持久记忆使用固定 topic（profile/projects/preferences 等），模型不能随意创建新 topic，降低路径和膨胀风险。

3. **session 内渐进积累**
   借鉴 pico 的 episodic notes 机制：工具执行后自动产生笔记，session 内累积，跨 run 可召回。

4. **显式、可控、可查看**
   跨 session 记忆存为 Markdown，用户能直接打开 `.mico/memory/` 查看和修改。

5. **轻量召回，不上向量库**
   使用 tag 精确匹配 + 关键词重叠 + 时间排序的混合召回，中英文都支持。

6. **当前请求永不裁剪**
   无论历史和记忆多长，用户本轮请求必须 100% 保留。

7. **安全和隐私默认收敛**
   trace/report 只记录命中的 topic、笔记条数和字符数，不记录用户记忆的完整内容。

---

## 二、mico 当前实现基线

| 维度 | 现状 | 文件位置 |
|------|------|----------|
| 历史存储 | `Mico.history` 在同一实例内持续累积，`ask()` 每次创建新 run | `mico/mico/runtime.py` |
| prompt 构建 | `PromptBuilder.build()` 直接拼接所有 section | `mico/mico/prompt.py` |
| 历史裁剪 | 仅 `history[-6:]`，无预算、无摘要、无去重 | `mico/mico/prompt.py` |
| 工具结果 | 进 history 前按工具 `max_result_chars` 截断 | `mico/mico/agent_loop.py` |
| 文件摘要 | 无 | - |
| 长期记忆 | 无 | - |
| prompt metadata | 有 `prompt_chars/history_items_used/current_request_chars` 等基础字段 | `mico/mico/prompt.py` |

**关键缺口**：

- `Mico.history` 在 REPL 模式下跨 run 累积，但没有 run 边界切片。
- 没有 episodic notes，模型无法在 session 内自动积累对文件的理解。
- 没有 session 持久化，进程退出后 working memory 和 episodic notes 丢失。
- 没有长期记忆，用户要求"记住"的信息无法跨 session 存活。
- prompt 无预算控制，长任务下线性膨胀。

---

## 三、总体架构

```text
                    user_message
                         |
                         v
+----------------------------------------------------+
|                    Mico Runtime                      |
|  - ask() 建立 run 边界，加载 session state            |
|  - execute_tool() 执行后更新 working memory +         |
|    自动产生 episodic note                             |
|  - build_prompt_bundle() 调 ContextManager            |
|  - run 结束后 session_store.save() 持久化             |
+------------------------+---------------------------+
                         |
             +-----------+-----------+
             |                       |
             v                       v
+------------------------+   +---------------------------+
|    DurableMemory      |   |    Session Memory State    |
|  .mico/memory/*.md      |   |  working memory            |
|  MEMORY.md index        |   |  episodic notes            |
|  topic/tag retrieval    |   |  file_summaries+freshness  |
|  跨 session 持久化       |   |  SessionStore 持久化       |
+------------------------+   +---------------------------+
             |                       |
             +-----------+-----------+
                         |
                         v
               +------------------+
               |  ContextManager  |
               |  6 section 组装   |
               |  预算 + 压缩      |
               |  metadata         |
               +------------------+
                         |
                         v
                    prompt text
```

核心拆分：

| 模块 | 职责 | 持久化 |
|------|------|--------|
| `DurableMemory` | 管理 `.mico/memory/`，加载索引、写入 topic、检索相关记忆 | 磁盘 Markdown |
| `SessionMemoryState` | 持有 working memory + episodic notes + file_summaries，跨 run 保持 | SessionStore JSON |
| `ContextManager` | 组装 prompt section、执行预算和压缩、输出 metadata | 无状态 |
| `PromptBuilder` | 保留现有静态文案和 section 文本工厂，不再拥有裁剪决策 | 无状态 |
| `SessionStore` | session JSON 读写，原子写入(tmp+replace) | 磁盘 JSON |

---

## 四、Session 持久化

### 4.1 SessionStore

借鉴 pico 的 `session_store.py`，新增 session 持久化层：

```python
# mico/mico/session_store.py

class SessionStore:
    def __init__(self, root):
        self.root = Path(root)  # .mico/sessions/

    def save(self, session_id, data):
        """原子写入 session JSON（tmp + replace）"""
        path = self.root / f"{session_id}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def load(self, session_id):
        """加载 session JSON，不存在返回 None"""
        path = self.root / f"{session_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def latest(self):
        """返回最近修改的 session（按 mtime 降序第一个）"""
        sessions = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return self.load(sessions[0].stem) if sessions else None
```

### 4.2 Session 数据结构

```python
{
    "session_id": str,
    "created_at": str,
    "updated_at": str,
    "memory": {
        "working": {
            "task_summary": str,
            "recent_files": list[str]
        },
        "episodic_notes": list[dict],
        "file_summaries": dict,
        "next_note_index": int
    }
}
```

### 4.3 Session 选择与生命周期

**session 语义裁决**：

- 同一 session 内的多个 run 必须自动积累理解；这是 mico 的核心行为。
- 这种积累通过 `SessionMemoryState`（working memory + episodic notes + file summaries）完成，不通过全量旧 `Mico.history` 注入完成。
- v1 默认使用 workspace-scoped `default` session：`.mico/sessions/default.json`。
- 未来如需多 session，再增加 `--session <id>` 和 `--new-session`；在没有显式 CLI 参数前，不默认按 mtime `latest()` 猜测 session，避免误恢复错误上下文。
- REPL 模式下，同一个进程内每次 `ask()` 都是同一 session 的新 run。
- one-shot 模式下，默认也读写 workspace 的 `default` session，因此连续命令能延续持久记忆和 episodic notes。

`latest()` 可以作为后续 CLI 恢复功能的辅助 API，但不作为 v1 默认策略。

```text
CLI 启动
  → session_id = argv 显式指定，或默认 "default"
  → session_store.load(session_id)
  → 恢复 SessionMemoryState（working + episodic + file_summaries）

ask() 运行
  → 每轮 build_prompt 使用 SessionMemoryState
  → 工具执行后更新 SessionMemoryState
  → run 结束 → session_store.save(session_id, state)

进程退出
  → session state 已持久化到 .mico/sessions/<session_id>.json
  → 下次启动可恢复
```

---

## 五、三层记忆详细设计

### 5.1 Working Memory（第一层）

**职责**：当前任务的"仪表盘"，每轮注入 prompt，session 内跨 run 保持。

**数据结构**（与 pico 对齐）：

```python
{
    "task_summary": str,       # 当前任务摘要，上限 300 字符
    "recent_files": list[str]  # 最近接触文件路径(POSIX)，上限 8，LIFO
}
```

**常量**：

```python
WORKING_FILE_LIMIT = 8
TASK_SUMMARY_LIMIT = 300
FILE_SUMMARY_LIMIT = 6  # 渲染时最多显示 6 个文件摘要
```

**更新规则**：

| 事件 | 行为 |
|------|------|
| `ask()` 开始 | `set_task_summary(user_message)`，**不 reset** recent_files 和 file_summaries（跨 run 保持） |
| `read_file` 成功 | `remember_file(rel)` + `record_file_summary(rel, summary, freshness)` |
| `write_file/patch_file` 成功 | `invalidate_file(rel)` + `remember_file(rel)` |
| `search` 成功 | 不写 working memory（搜索结果是临时的） |
| `run_command` | 不写 working memory（命令输出由 episodic note 记录） |

**渲染**（`render_memory_text()`）：

```text
Task: 修复认证模块测试失败
Recent files: src/main.py, README.md, tests/test_main.py
File summaries:
  - src/main.py -> FastAPI 应用入口，定义了 /health 和 /api/tasks 端点
  - README.md -> 项目简介，本地 coding agent，Python 实现
```

**与 pico 的关键区别**：pico 的 working memory 在 `ask()` 开始时 reset，mico 不 reset——因为用户可能连续跑多个相关任务（读代码 → 修改 → 测试），reset 会丢失 recent_files 上下文。

Working Memory 的“每轮注入”不是无限制硬保留。ContextManager 必须始终保留 `task_summary`，但在预算压力下可以减少 `recent_files` 数量和 `file_summaries` 条数。这样避免“working memory 不压缩”和 section budget 之间出现矛盾。

### 5.2 Episodic Notes（第二层）

**职责**：模型自动积累的临时观察，session 内跨 run 存活，按需召回。这是 mico 之前缺失的关键层。

**数据结构**（与 pico 对齐）：

```python
{
    "text": str,           # 笔记正文，上限 500 字符
    "tags": list[str],     # 标签列表，用于精确匹配召回
    "source": str,         # 来源标识（如 "read_file:src/main.py"）
    "created_at": str,     # ISO 8601 时间戳
    "note_index": int,     # 递增索引，保证顺序
    "kind": str            # "episodic"(默认) / "process"
}
```

**常量**：

```python
EPISODIC_NOTE_LIMIT = 15   # 最多保留 15 条（比 pico 的 12 稍多，mico 任务可能更密集）
NOTE_TEXT_LIMIT = 500      # 单条笔记上限
```

**自动生成规则**（在 `Mico._after_tool_result()` 中）：

| 工具 | 自动生成的 episodic note | tags |
|------|--------------------------|------|
| `read_file` 成功 | "文件 {path} 第 {start}-{end} 行：{前 200 字符摘要}" | ["file", path 的扩展名如 "py"/"md"] |
| `write_file` 成功 | "创建/覆盖文件 {path}，{bytes} 字节" | ["file", "write"] |
| `patch_file` 成功 | "修改文件 {path}，替换 {old_len} 字符为 {new_len} 字符" | ["file", "edit"] |
| `run_command` exit=0 | "命令 {argv 摘要} 成功，耗时 {ms}ms" | ["command"] |
| `run_command` exit≠0 | "命令 {argv 摘要} 失败 exit={code}：{stderr 前 100 字符}" | ["command", "error"] |
| `remember` 成功 | "已记住 {topic}：{note 前 50 字符}" | ["memory", topic] |

**写入逻辑**（`append_note()`，与 pico 一致）：

1. 去重：相同 `text` 的旧笔记被移除，新笔记追加到末尾。
2. 淘汰：超过 `EPISODIC_NOTE_LIMIT` 时 FIFO 淘汰（`notes[-15:]`）。
3. 索引：`next_note_index` 单调递增，即使旧笔记被淘汰也不回退。

**召回机制**（`retrieval_candidates()`，与 pico 一致）：

```python
def retrieval_candidates(self, query, limit=3):
    """从 episodic notes + durable memory 混合召回"""
    query_tokens = tokenize(query)  # 英文 [A-Za-z0-9_]+ 中文 2-3 字滑窗

    candidates = []
    # 加入 episodic notes
    for note in self.episodic_notes:
        score = self._score_note(note, query_tokens)
        candidates.append((score, note))
    # 加入 durable memory topics
    for topic_note in self.durable_notes:
        score = self._score_note(topic_note, query_tokens)
        candidates.append((score, topic_note))

    # 排序：(exact_tag_match, keyword_overlap, recency, note_index) 降序
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [note for _, note in candidates[:limit]]

def _score_note(self, note, query_tokens):
    tag_set = set(note.get("tags", []))
    exact_tag = 1 if tag_set & query_tokens else 0
    note_tokens = tokenize(note.get("text", ""))
    keyword_overlap = len(query_tokens & note_tokens)
    recency = parse_timestamp(note.get("created_at", ""))
    note_index = note.get("note_index", 0)
    return (exact_tag, keyword_overlap, recency, note_index)
```

**中文 tokenizer**（v1 用固定关键词表，比 pico 的 `[A-Za-z0-9_]+` 多中文支持）：

```python
# 固定中文关键词表（v1）
CONTEXT_KEYWORDS = {
    "项目", "架构", "决策", "规范", "约定", "偏好", "背景",
    "技术栈", "难点", "亮点", "成果", "指标",
    "后端", "前端", "全栈", "系统设计", "算法", "数据结构",
    "配置", "部署", "测试", "重构", "优化",
    "Java", "Python", "Spring", "Go", "MySQL", "Redis", "Kafka",
    "Docker", "Kubernetes", "CI", "CD",
}

def tokenize(text):
    """英文正则 + 中文关键词匹配"""
    en = set(re.findall(r'[A-Za-z0-9_]+', text.lower()))
    cn = {kw for kw in CONTEXT_KEYWORDS if kw in text}
    return en | cn
```

### 5.3 Durable Memory（第三层）

**职责**：用户显式要求"记住"的稳定事实，跨 session 持久化。使用固定 topic。

**存储**：`.mico/memory/*.md`（与当前 DurableMemory 设计一致）。

**Topic 白名单**：

```python
DURABLE_TOPICS = {"profile", "projects", "preferences", "decisions", "conventions", "notes"}
```

**写入方式**：专用 `remember` 工具（不走 `write_file`）。

```json
{
  "name": "remember",
  "args": {
    "topic": "profile|projects|preferences|decisions|conventions|notes",
    "note": "str",
    "tags": ["str"]
  }
}
```

**`MEMORY.md` 索引**（常驻注入，100 行 / 20KB 上限）：

```markdown
# mico Memory Index

- profile: 用户背景、技术栈、工作习惯。updated: 2026-06-25. tags: background, stack, workflow
- projects: 项目经历、技术难点、关键成果。updated: 2026-06-25. tags: project, metrics
- preferences: 输出风格、语言、代码规范偏好。updated: -. tags: style, preference
- decisions: 关键架构决策、选型理由。updated: -. tags: decision, architecture
- conventions: 项目约定、编码规范、分支策略。updated: -. tags: convention, rule
- notes: 其他值得记住的稳定信息。updated: -. tags: misc
```

**固定召回规则**（优先于关键词匹配）：

```python
TOPIC_RULES = {
    "项目": ["projects", "decisions"],
    "project": ["projects", "decisions"],
    "架构": ["decisions", "conventions"],
    "architecture": ["decisions", "conventions"],
    "规范": ["conventions", "preferences"],
    "convention": ["conventions", "preferences"],
    "约定": ["conventions", "preferences"],
    "偏好": ["preferences"],
    "preference": ["preferences"],
    "背景": ["profile"],
    "技术栈": ["profile", "projects"],
    "决策": ["decisions"],
    "decision": ["decisions"],
}
```

每个 topic 渲染时截断到 800 字符。

### 5.4 三层记忆的关系

```
工具执行
  │
  ├─→ Working Memory: 更新 recent_files + file_summaries（自动）
  │
  ├─→ Episodic Notes: 自动生成笔记（自动，session 内累积）
  │
  └─→ Durable Memory: 用户要求时调 remember 工具（手动，跨 session）

ContextManager.build():
  │
  ├─ memory section ← Working Memory 仪表盘（每轮注入）
  │
  ├─ relevant_memory section ← Episodic Notes(top-3) + Durable Memory(top-3) 混合召回
  │
  └─ history section ← 当前 run 的工具/对话历史（经压缩）
```

---

## 六、ContextManager 设计

### 6.1 Section 顺序

```text
prefix            ← 身份、response contract、runtime policy、工具目录、format reminder
memory_index      ← .mico/memory/MEMORY.md 短索引（常驻）
relevant_memory   ← 召回的 episodic notes + durable topic 摘要（最多 3+3=6 条）
working_memory    ← 当前任务摘要、recent files、file summaries
history           ← 当前 run 的工具/对话历史（经压缩）
current_request   ← 用户本轮请求（永不裁剪）
```

### 6.2 预算参数

```python
DEFAULT_TOTAL_BUDGET = 10000
DEFAULT_SECTION_BUDGETS = {
    "prefix": 2400,
    "memory_index": 800,
    "relevant_memory": 2000,   # episodic(top-3) + durable(top-3) 的预算
    "working_memory": 1000,
    "history": 3800,
}
DEFAULT_SECTION_FLOORS = {
    "prefix": 1400,
    "memory_index": 300,
    "relevant_memory": 400,
    "working_memory": 300,
    "history": 1000,
}
DEFAULT_REDUCTION_ORDER = (
    "history",            # 最先牺牲
    "relevant_memory",
    "working_memory",
    "memory_index",
    "prefix",             # 最后压缩
)
```

`current_request` 不在任何预算和 reduction order 中。

### 6.3 History 压缩

```python
RECENT_WINDOW = 6
RECENT_ITEM_LIMIT = 900
OLDER_TOOL_LIMIT = 80
OLDER_MSG_LIMIT = 80
MAX_OLDER_READ_RANGES_PER_FILE = 3
MAX_OLDER_READ_FILE_ENTRIES = 12
```

规则：

1. 最近 6 条保留较完整内容，但工具参数必须摘要化（`write_file.content`、`patch_file.old_text/new_text` 不能进入 prompt）。
2. older `read_file` 按 `(path, start, end)` 去重，同一文件最多保留 3 个 range，全局最多 12 条。
3. older `run_command` 渲染为 `argv/exit_code/timed_out` + stderr 前 2 行。
4. older 用户/助手文本截断到 80 字符。

### 6.4 History 切片

`ContextManager.build()` 只使用当前 run 的 history：

```python
history_slice = agent.history[agent._last_run_history_start:]
```

跨 run 的稳定信息通过 DurableMemory + Episodic Notes 注入，不依赖旧 history。

### 6.5 Prompt metadata

```python
{
    "prompt_chars": int,
    "total_budget": int,
    "over_budget": bool,
    "section_chars": { ... },
    "history_items_total": int,
    "history_items_used": int,
    "memory_topics_available": int,
    "memory_topics_used": list[str],
    "episodic_notes_available": int,
    "episodic_notes_used": int,
    "current_request_chars": int,
    "current_request_preserved_rate": 1.0
}
```

---

## 七、与现有代码的集成点

### 7.1 新增文件

| 文件 | 职责 |
|------|------|
| `mico/mico/memory.py` | `SessionMemoryState`（working + episodic + file_summaries），路径规范化，freshness |
| `mico/mico/memory_store.py` | `DurableMemory`，管理 `.mico/memory/` 和 topic 检索 |
| `mico/mico/context_manager.py` | section 组装、预算、压缩、metadata |
| `mico/mico/session_store.py` | `SessionStore`，session JSON 读写，原子写入 |
| `mico/tests/test_memory.py` | SessionMemoryState 单测 |
| `mico/tests/test_memory_store.py` | 长期记忆单测 |
| `mico/tests/test_context_manager.py` | 预算和压缩单测 |
| `mico/tests/test_session_store.py` | session 持久化单测 |

### 7.2 改造文件

**`mico/mico/tools.py`**：
- 新增 `remember` 工具 spec，`requires_approval=True`。

**`mico/mico/tool_executor.py`**：
- 让 `remember` 走 approval 流程。
- 扩展 approval 机制为通用请求对象，例如 `callback({"tool_name": name, "args": args, "summary": summary})`。
- 保持现有 shell command 审批行为的兼容性：已有只接收 `argv` 的测试和调用路径应通过 adapter 保留，不能在 P3 第一阶段直接破坏 `approval=ask` 的 run_command 行为。
- `remember` 在 `approval=ask` 下展示 `topic/tags/note` 的短摘要；`approval=auto` 允许；`approval=never` 阻断。

**`mico/mico/runtime.py`**：
- `__init__` 初始化 `SessionStore`、`SessionMemoryState`、`DurableMemory`、`ContextManager`。
- 启动时加载或新建 session。
- `execute_tool()` 执行后调用 `_after_tool_result()` 更新 working memory + 自动生成 episodic note。
- `build_prompt_bundle()` 改为由 `ContextManager` 组装，传入当前 run history 切片。
- `ask()` 开始时 `set_task_summary(user_message)`，不 reset 其他状态。
- run 结束后 `session_store.save()`。

**`mico/mico/prompt.py`**：
- 保留现有静态文案方法。
- 拆出 section 文本工厂。
- `build()` 保留公开签名用于兼容现有测试，内部委托 `ContextManager`。

### 7.3 尽量不改

- `agent_loop.py`：不直接感知 memory。
- `parser.py`、`providers.py`、`cli.py`：不因本阶段改变核心行为。
- `workspace.py`：只在必要时补一个 POSIX relative helper。

---

## 八、测试方案

### 8.1 `tests/test_memory.py`（SessionMemoryState）

| 测试 | 验证点 |
|------|--------|
| recent_files LIFO 淘汰 | 最多 8 个，重复 path 移到最新 |
| POSIX key | Windows 风格路径转为 `a/b.py` |
| file summary freshness | 文件修改后旧摘要不展示 |
| invalidate_file | 写入后摘要失效 |
| task_summary 截断 | 超长摘要截断到 300 |
| episodic note 自动生成 | read_file 后产生 note，tags 正确 |
| episodic note 去重 | 相同 text 的旧笔记被移除 |
| episodic note FIFO 淘汰 | 超过 15 条时最旧的被淘汰 |
| episodic note 索引单调递增 | 淘汰后 next_note_index 不回退 |
| 召回排序 | tag 精确匹配 > 关键词重叠 > 时间新鲜度 |
| 混合召回 | episodic + durable 合并排序取 top-3 |

### 8.2 `tests/test_session_store.py`

| 测试 | 验证点 |
|------|--------|
| save/load 对称 | 写入后读出数据一致 |
| 原子写入 | 中途崩溃不损坏已有文件 |
| latest() | 返回最近修改的 session |
| load 不存在 | 返回 None |

### 8.3 `tests/test_memory_store.py`（DurableMemory）

| 测试 | 验证点 |
|------|--------|
| 初始化 `.mico/memory/` | 自动创建固定 topic 文件和 `MEMORY.md` |
| topic 白名单 | 非法 topic 被拒绝 |
| 路径安全 | topic 不能路径穿越 |
| remember 追加 note | 写入目标 topic，更新 `updated_at` |
| 单条 note 截断 | 超长 note 不撑爆 memory |
| topic 文件上限 | 超过大小拒绝写入 |
| 中文关键词召回 | "项目/架构/规范/背景"能命中对应 topic |

### 8.4 `tests/test_context_manager.py`

| 测试 | 验证点 |
|------|--------|
| section 顺序 | current_request 最后 |
| current_request 永不裁剪 | preserved rate 恒为 1.0 |
| reduction order | history 先压，prefix 最后 |
| episodic notes 注入 | read_file 后 note 出现在 relevant_memory |
| durable memory 注入 | remember 后 topic 出现在 relevant_memory |
| 混合召回排序 | episodic 优先于 durable（同分时） |
| history 参数摘要 | write/patch 大参数不进入 prompt |
| read_file range 去重 | 不同 range 不错误合并 |
| over_budget metadata | 触底仍超限时记录 |

### 8.5 集成回归

```text
python -m pytest
python -m mico "列出当前目录"
python -m mico "记住：这个项目使用 FastAPI + PostgreSQL"
python -m mico "根据你记住的信息，列出项目的技术栈"
```

---

## 九、实施顺序

### 阶段 1：SessionStore + SessionMemoryState

1. 新增 `session_store.py`。
2. 新增 `memory.py`（`SessionMemoryState`：working memory + episodic notes + file_summaries + freshness）。
3. 补 `test_session_store.py` 和 `test_memory.py`。
4. `runtime.py` 接入 session 加载/保存。
5. `ask()` 开始时 `set_task_summary`，不 reset 其他状态。

验收：
- session 状态跨 run 保持（recent_files、episodic notes 不丢失）。
- 进程退出后 session 可恢复。

### 阶段 2：DurableMemory + remember 工具

1. 新增 `memory_store.py`。
2. 新增 `remember` 工具和 approval。
3. `PromptBuilder` 注入 `MEMORY.md` 索引。
4. 补 `test_memory_store.py` 和 remember 工具测试。

验收：
- 用户能让 mico 记住一条项目约定或技术决策。
- 下一次 `ask()` 能把相关 memory 注入 prompt。
- trace/report 不泄露 note 全文。

### 阶段 3：ContextManager + 召回 + 预算压缩

1. 新增 `context_manager.py`。
2. 实现混合召回（episodic + durable）。
3. `PromptBuilder` 退化为 section 文本工厂。
4. 实现 section budget、history 压缩、metadata。
5. 补 ablation 测试。

验收：
- `current_request_preserved_rate=1.0`。
- 同一 session 多 run 后，episodic notes 能被后续 run 召回。
- 长 history 下 prompt 有可解释压缩。

---

## 十、与 pico / claude-code 的取舍

| 参考设计 | mico 取舍 | 理由 |
|----------|-----------|------|
| pico 三层记忆 | **采用** | 解决了原设计缺少 episodic notes 的核心问题 |
| pico SessionStore | **采用** | session 内跨 run 保持是关键需求 |
| pico Episodic Notes | **采用**，limit 15（pico 12） | mico 任务可能更密集 |
| pico 关键词召回 | **采用**，补中文关键词表 | pico 的 `[A-Za-z0-9_]+` 对中文无效 |
| pico freshness SHA-256 | **采用** | 任务内防陈旧 |
| pico promote 机制 | **不采用** | 持久记忆通过 `remember` 工具手动写入，不做自动晋升 |
| pico DurableMemory topic 去重 | **不采用** | mico 用固定 topic，不需要 `_subject_key` 去重 |
| claude-code MEMORY.md 索引 | **采用** | 短索引常驻，低成本 |
| claude-code Auto Memory 后台抽取 | **不采用** | 实现复杂，手动 remember 足够 |
| claude-code 四层压缩 | **不采用** | 单层 ContextManager 压缩已足够 |
| embedding/vector DB | **不采用** | 笔记量小，关键词匹配足够 |
| checkpoint/resume | **不采用** | 另列未来需求 |

---

## 十一、风险与裁决

| 风险 | 裁决 |
|------|------|
| session JSON 膨胀 | episodic note FIFO 15 条 + file_summary 上限 6，单 session 数据量可控 |
| 跨 run 不 reset working memory | 多任务连续场景合理；如需"全新任务"语义，用户可开新 session |
| 中文召回弱 | 固定关键词表覆盖主场景，后续可扩展滑窗 |
| `approval_callback` 需要扩展 | 阶段 2 前置依赖，需先改造 tool_executor |
| 默认 session 误恢复 | v1 使用 workspace-scoped `default`，不按 mtime 自动 latest；多 session 留给后续 CLI 参数 |
| Working Memory 与预算冲突 | `task_summary` 必保留，recent files/file summaries 可按预算压缩 |
| 预算数值未验证 | 阶段 3 跑 ablation 校准 |
| `.mico/` 被 workspace 工具屏蔽 | 长期记忆通过内部 memory store 写入，不走 `write_file` |
| 记忆文件隐私 | 只写本地 Markdown；remember 需 approval；trace 不记录正文 |
