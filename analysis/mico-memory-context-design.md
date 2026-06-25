# mico 面试记忆系统与任务内上下文治理设计

> 日期：2026-06-25  
> 状态：当前优先设计，作为下一阶段实现依据  
> 作者角色：Claude Code 可负责初稿实现；上下文策略、记忆边界和安全策略由 Codex 审查定稿  
> 范围：面向面试准备的本地记忆系统 + 单次 run 内上下文治理  
> 参考：`pico/analysis/memory-and-context-management.md`、`claude-code/analysis/memory-and-context-management.md`

---

## 〇、当前决策

文档/演示包装不再作为当前主线。mico 当前最主要目标是做一个**切实可用的面试记忆系统**，支撑以下真实需求：

- 记住用户背景、技术栈、项目经历、简历版本和目标岗位。
- 针对 JD、简历和面试反馈，在后续任务中自动带入相关上下文。
- 在长任务里避免重复读文件、重复塞历史、prompt 无控制膨胀。
- 让能力可测试、可解释、可展示，而不是只做炫技式 memory 架构。

本设计替代原先“仅任务内上下文治理”的窄方案。新的方向是：

```text
长期面试记忆（跨 run，本地 Markdown）
        +
任务内工作记忆（单 run，文件摘要与 freshness）
        +
ContextManager（预算、压缩、相关记忆注入）
```

仍然不做 Claude Code 级别的重型 Auto Memory，不做 embedding，不做后台子代理记忆抽取，不做远程 memory store。

---

## 一、设计原则

1. **面试场景优先**  
   记忆系统首先服务简历优化、JD 匹配、项目复盘、模拟面试、面试反馈沉淀，而不是泛化成知识库。

2. **显式、可控、可查看**  
   跨 run 记忆存为 Markdown，用户能直接打开 `.mico/memory/` 查看和修改。模型不应把隐私信息写进不可见数据库。

3. **轻量召回，不上向量库**  
   v1 使用 topic、tag、关键词和固定面试主题召回。中英文都要可用，但不引入 embedding、SQLite FTS 或额外服务。

4. **当前请求永不裁剪**  
   无论历史和记忆多长，用户本轮请求必须 100% 保留。

5. **记忆与工具历史分离**  
   稳定事实进入 memory；工具输出、命令结果、临时推理留在 history/run artifact。不要把可从文件或 git 推导的信息长期写入 memory。

6. **安全和隐私默认收敛**  
   trace/report 只记录命中的 memory topic、字符数和压缩统计，不记录完整个人背景、简历正文或面试反馈全文。

---

## 二、mico 当前实现基线

| 维度 | 现状 | 文件位置 |
|------|------|----------|
| 历史存储 | `Mico.history` 在同一个 `Mico` 实例内持续累积，`ask()` 每次创建新 run | `mico/mico/runtime.py` |
| prompt 构建 | `PromptBuilder.build()` 直接拼接所有 section | `mico/mico/prompt.py` |
| 历史裁剪 | 仅 `history[-6:]`，无预算、无摘要、无去重 | `mico/mico/prompt.py` |
| 工具结果 | 进 history 前按工具 `max_result_chars` 截断 | `mico/mico/agent_loop.py` |
| 文件摘要 | 无 | - |
| 长期记忆 | 无 | - |
| prompt metadata | 有 `prompt_chars/history_items_used/current_request_chars` 等基础字段 | `mico/mico/prompt.py` |

需要特别注意：`Mico.history` 不是严格“单 run 内”历史。REPL 模式下同一个 agent 会连续调用多次 `ask()`，history 会跨 run 留存；report 通过 `_last_run_history_start` 只统计当前 run。记忆设计必须明确 run 边界，不能误把跨 run history 当成长期记忆。

**裁决：ContextManager 的 history section 默认只使用当前 run history。**

- `AgentLoop.run()` 记录本轮 user message 后，`Mico._last_run_history_start` 指向当前 run 的第一条工具/助手记录位置；ContextManager 构建 history 时应使用当前 run 切片，而不是完整 `Mico.history`。
- 推荐接口：`build_prompt_bundle(user_message, history_start=None)`，默认使用 `self._last_run_history_start`；实际传入 ContextManager 的 history 为 `self.history[history_start:]`。
- 当前 run 的 user request 不依赖 history section 重复展示，而是由 `current_request` section 单独展示。
- 跨 run 需要保留的稳定信息必须通过 `InterviewMemory` 写入 `.mico/memory/`，不能依赖历史对话继续塞进 prompt。
- 如未来要支持“REPL 上下文延续”，应单独设计 `session_summary` 或 `conversation_memory`，不能直接把全部旧 history 注入。

---

## 三、目标能力

### 3.1 面试长期记忆

让 mico 能记住这些稳定信息：

- `profile`：用户背景、学历、年限、技术栈、求职目标。
- `resume`：当前简历版本、关键卖点、需要避免的表述。
- `projects`：项目经历、技术难点、STAR 叙述素材、可量化成果。
- `targets`：目标公司、岗位 JD、岗位关键词、投递状态。
- `feedback`：模拟面试反馈、真实面试复盘、回答风格偏好。
- `preferences`：用户偏好的简历语气、中文/英文、面试回答长度和结构。

### 3.2 任务内工作记忆

在一次 run 内自动追踪：

- 当前任务摘要。
- 最近访问/修改的文件。
- 文件摘要和 freshness hash。
- 旧工具输出的压缩表示。

### 3.3 上下文预算

让 prompt 有明确预算和 metadata：

- 总字符预算默认 10000。
- current request 永不裁剪。
- 先压缩 history，再压缩 relevant memory，再压缩 working memory，最后才压 prefix。
- 超预算时记录 `over_budget=true`，不要静默失败。

---

## 四、总体架构

```text
                    user_message
                         |
                         v
+--------------------------------------------------+
|                    Mico Runtime                   |
|  - ask() 建立 run 边界                             |
|  - execute_tool() 执行后更新 working memory         |
|  - build_prompt_bundle() 调 ContextManager          |
+------------------------+-------------------------+
                         |
             +-----------+-----------+
             |                       |
             v                       v
+------------------------+   +---------------------------+
|     InterviewMemory     |   |       WorkingMemory        |
|  .mico/memory/*.md      |   |  task_summary              |
|  MEMORY.md index        |   |  recent_files              |
|  topic/tag retrieval    |   |  file_summaries+freshness  |
+------------+-----------+   +-------------+-------------+
             |                             |
             +-------------+---------------+
                           |
                           v
                 +------------------+
                 |  ContextManager  |
                 |  section render  |
                 |  budget/reduce   |
                 |  metadata        |
                 +------------------+
                           |
                           v
                      prompt text
```

核心拆分：

| 模块 | 职责 |
|------|------|
| `InterviewMemory` | 管理 `.mico/memory/`，加载索引、写入 topic、检索相关面试记忆 |
| `WorkingMemory` | 管理单 run 内任务摘要、最近文件、文件摘要和 freshness |
| `ContextManager` | 组装 prompt section、执行预算和压缩、输出 metadata |
| `PromptBuilder` | 保留现有静态文案和 section 文本工厂，不再拥有裁剪决策 |

---

## 五、长期面试记忆设计

### 5.1 存储位置

默认存储在 workspace 内部：

```text
.mico/
  memory/
    MEMORY.md
    profile.md
    resume.md
    projects.md
    targets.md
    feedback.md
    preferences.md
```

说明：

- `.mico/` 仍然是 mico 内部目录，普通 `write_file` 不允许写入。
- 记忆写入由专门的 memory API/tool 完成，不走通用文件写入路径。
- 文件使用 Markdown，便于用户直接审查。
- v1 使用固定 topic 文件，不支持模型随意创建任意文件名，降低路径和膨胀风险。

### 5.2 `MEMORY.md` 索引

`MEMORY.md` 常驻注入较短索引，限制 100 行或 20KB，格式固定：

```markdown
# mico Memory Index

- profile: 用户背景、技术栈、求职目标。tags: background, stack, goal
- resume: 当前简历版本、核心卖点、禁用表述。tags: resume, selling-points
- projects: 项目经历、STAR 素材、量化成果。tags: project, star, metrics
- targets: 目标公司、JD 关键词、投递状态。tags: jd, company, role
- feedback: 模拟/真实面试反馈。tags: interview, feedback
- preferences: 输出风格、语言、回答结构偏好。tags: style, preference
```

索引只放摘要和 tags，不放完整隐私内容。

### 5.3 Topic 文件格式

每个 topic 文件采用简单 frontmatter + notes：

```markdown
---
topic: projects
summary: 项目经历、STAR 素材、技术难点和量化成果。
tags: project, star, metrics
updated_at: 2026-06-25T00:00:00Z
---

## Notes

- 项目：mico local coding agent。亮点：工具治理、workspace 沙箱、run artifact、记忆系统。
- STAR：...
```

v1 不做复杂 schema 校验，只保证：

- topic 必须属于固定白名单。
- 单条 note 截断到 1000 字符。
- 单个 topic 文件建议上限 30KB，超过后拒绝写入并提示用户整理。

### 5.4 记忆写入方式

新增一个专用工具：

```json
{
  "name": "remember",
  "args": {
    "topic": "profile|resume|projects|targets|feedback|preferences",
    "note": "str",
    "tags": ["str"]
  }
}
```

规则：

- 只有当用户明确表达“记住、以后都按这个、我的背景是、目标岗位是、这次面试反馈是”等稳定信息时才使用。
- 写入 `.mico/memory/<topic>.md`，并更新 `MEMORY.md` 对应 topic 的 `updated_at/tags`。
- `remember` 是持久化写入，默认 `requires_approval=True`。
- approval UX 裁决：
  - `approval=auto`：允许写入，不再二次打断；前提是用户本轮明确要求“记住”。
  - `approval=ask`：展示 `topic/tags/note` 的短摘要，由用户确认后写入。
  - `approval=never`：阻断写入，返回 `approval_denied`。
- 写入 trace/report 时只记录 `topic/tags/note_chars`，不记录 note 全文。

不做：

- 不自动后台抽取整段对话。
- 不让模型自由创建 memory 文件。
- 不把命令输出、临时代码错误、一次性工具结果写进长期 memory。

### 5.5 记忆召回

v1 使用轻量混合召回：

1. `MEMORY.md` 索引常驻短注入。
2. 根据用户请求和当前任务摘要提取 query tokens。
3. 固定 topic 规则优先：
   - 出现“简历/resume” → `resume + projects + preferences`
   - 出现“JD/岗位/公司/投递” → `targets + resume + projects`
   - 出现“面试/mock/回答/STAR” → `feedback + projects + preferences`
   - 出现“我的背景/技术栈/自我介绍” → `profile + projects + preferences`
4. 再用 tags/关键词重叠补充到最多 3 个 topic。
5. 每个 topic 渲染时截断到 800 字符。

中文支持不能只用 `[A-Za-z0-9_]+`。v1 tokenizer 应同时支持：

- 英文、数字、常见技术符号：`python`、`spring`、`llm`、`gpt-4o`、`c++`。
- 中文 2 字或 3 字滑窗，用于匹配“简历”“项目”“面试”“岗位”“后端”“系统设计”等词。
- 也可以先用一组固定中文关键词表，后续再扩展 tokenizer。

---

## 六、任务内 WorkingMemory

### 6.1 数据结构

```python
{
    "task_summary": str,          # 当前 run 摘要，上限 300
    "recent_files": list[str],    # 最近文件，上限 8，路径统一为 POSIX 风格
    "file_summaries": {
        "<rel_path>": {
            "summary": str,       # 上限 500
            "freshness": str,     # 文件全量内容 SHA-256
            "created_at": str
        }
    }
}
```

### 6.2 更新时机

`agent_loop.py` 不应感知 memory。工具执行后 hook 放在 `Mico.execute_tool()` 或一个 `Mico._after_tool_result()` 私有方法中：

```text
AgentLoop
  -> agent.execute_tool(name, args)
       -> ToolExecutor.execute()
       -> Mico._after_tool_result(name, args, result)
       -> return result
```

这样保持主循环简单，也解决原设计中“agent_loop 零改动”和“在 agent.record 后 hook”之间的矛盾。

具体规则：

- `ask()` 开始：`working_memory.reset(user_message)`，run 之间不继承 working memory。
- `read_file` 成功：记录 recent file，生成文件摘要，计算完整文件 hash。
- `write_file/patch_file` 成功：失效该文件旧摘要，记录 recent file。
- `search` 成功：可记录搜索路径，但不生成文件摘要。
- `run_command` 成功或失败：不写 working memory，只由 history 压缩保留摘要。

### 6.3 Freshness

freshness 以当前磁盘文件全量内容 SHA-256 为准，不使用 history 中已截断的 tool result。

渲染时策略：

- 如果文件不存在或 hash 不一致，跳过旧摘要。
- 单次 render 中同一文件只计算一次 hash。
- `freshness=None` 的摘要不注入 prompt。

### 6.4 路径规范化

所有 memory key 使用 workspace 相对 POSIX 路径：

```python
Path(rel).as_posix()
```

Windows 下不能直接用 `workspace.relative()` 返回值作为 key，否则 `a\b.py` 和 `a/b.py` 会出现 freshness miss。

---

## 七、ContextManager 设计

### 7.1 Section 顺序

```text
prefix
memory_index
relevant_memory
working_memory
history
current_request
```

说明：

- `prefix` 包含身份、response contract、runtime policy、工具目录，并在 prefix 尾部包含 format reminder。
- `memory_index` 是 `.mico/memory/MEMORY.md` 的短索引。
- `relevant_memory` 是召回的 topic 摘要。
- `working_memory` 是当前 run 的任务摘要、recent files、file summaries。
- `history` 是工具和对话历史的压缩视图。
- `current_request` 必须最后出现，且永不裁剪。

原 `format_reminder` 不再放在 `current_request` 后面，避免破坏“当前请求最后锚点”。实现时它不是独立 section，而是 `PromptBuilder.prefix_text()` 的尾部内容，随 prefix 一起预算和压缩。

### 7.2 预算参数

```python
DEFAULT_TOTAL_BUDGET = 10000
DEFAULT_SECTION_BUDGETS = {
    "prefix": 2400,
    "memory_index": 1000,
    "relevant_memory": 1800,
    "working_memory": 1000,
    "history": 3800,
}
DEFAULT_SECTION_FLOORS = {
    "prefix": 1400,
    "memory_index": 300,
    "relevant_memory": 300,
    "working_memory": 300,
    "history": 1000,
}
DEFAULT_REDUCTION_ORDER = (
    "history",
    "relevant_memory",
    "working_memory",
    "memory_index",
    "prefix",
)
```

`current_request` 不在任何预算和 reduction order 中。

如果所有 section 触底后仍超预算：

- 保留 current request。
- 记录 `over_budget=true`。
- 继续返回 prompt，而不是为了硬裁剪破坏用户请求。

### 7.3 History 压缩

```python
RECENT_WINDOW = 6
RECENT_ITEM_LIMIT = 900
OLDER_TOOL_LIMIT = 80
OLDER_MSG_LIMIT = 80
MAX_OLDER_READ_RANGES_PER_FILE = 3
MAX_OLDER_READ_FILE_ENTRIES = 12
```

规则：

1. 最近 6 条保留较完整内容，但工具参数必须摘要化。
2. `write_file.content`、`patch_file.old_text/new_text` 永远不能完整进入 prompt。
3. older `read_file` 按 `(path,start,end)` 去重；同一文件不同 range 不可简单合并。
4. 同一文件 older `read_file` 最多保留 3 个 range；全局 older read 条目最多 12 个。超出部分折叠为 `read_file {path} -> N ranges omitted; see file summary if available`。
5. older `run_command` 渲染为 `argv/exit_code/timed_out` + stderr 前 2 行 + stdout 摘要。
6. older 用户/助手文本截断到 80 字符。

### 7.4 Prompt metadata

新增或保留以下字段：

```python
{
    "prompt_chars": int,
    "total_budget": int,
    "over_budget": bool,
    "section_chars": {
        "prefix": int,
        "memory_index": int,
        "relevant_memory": int,
        "working_memory": int,
        "history": int,
        "current_request": int
    },
    "history_items_total": int,
    "history_items_used": int,
    "memory_topics_available": int,
    "memory_topics_used": list[str],
    "current_request_chars": int,
    "current_request_preserved_rate": 1.0
}
```

trace/report 只记录 topic 名称和长度，不记录 memory 正文。

---

## 八、与现有代码的集成点

### 8.1 新增文件

| 文件 | 职责 |
|------|------|
| `mico/mico/memory.py` | `WorkingMemory`、路径规范化、freshness、文件摘要 |
| `mico/mico/memory_store.py` | `InterviewMemory`，管理 `.mico/memory/` 和 topic 检索 |
| `mico/mico/context_manager.py` | section 组装、预算、压缩、metadata |
| `mico/tests/test_memory.py` | WorkingMemory 单测 |
| `mico/tests/test_memory_store.py` | 长期面试记忆单测 |
| `mico/tests/test_context_manager.py` | 预算和压缩单测 |

### 8.2 改造文件

**`mico/mico/tools.py`**

- 新增 `remember` 工具 spec。
- `remember` 只接受固定 topic、note、tags。
- 工具本身不直接写任意路径，调用 memory store API。

**`mico/mico/tool_executor.py`**

- 让 `remember` 走 approval 流程：`auto` 允许、`ask` 询问、`never` 阻断。
- 若保留现有 shell 专用 `approval_callback(argv)`，需要先扩展为通用 approval request，避免把 memory 审批硬塞进命令审批接口。
- `approval=never` 阻断持久记忆写入。
- 返回 metadata：`ok/error_kind/topic/note_chars`。

**`mico/mico/runtime.py`**

- `__init__` 初始化 `InterviewMemory`、`WorkingMemory`、`ContextManager`。
- `ask()` 开始 reset working memory。
- `execute_tool()` 执行后调用 memory hook。
- `build_prompt_bundle()` 改为由 `ContextManager` 组装，并默认只传入当前 run history：`self.history[self._last_run_history_start:]`。

**`mico/mico/prompt.py`**

- 保留现有静态文案方法。
- 拆出 section 文本工厂。
- `build()` 保留公开签名，用于兼容现有测试；内部可委托 `ContextManager` 或作为 legacy path。

### 8.3 尽量不改

- `agent_loop.py`：不直接感知 memory。
- `parser.py`、`providers.py`、`cli.py`：不因本阶段改变核心行为。
- `workspace.py`：只在必要时补一个 POSIX relative helper；优先在 memory 模块内部规范化。

---

## 九、测试方案

### 9.1 `tests/test_memory_store.py`

| 测试 | 验证点 |
|------|--------|
| 初始化 `.mico/memory/` | 自动创建固定 topic 文件和 `MEMORY.md` |
| topic 白名单 | 非法 topic 被拒绝 |
| 路径安全 | topic 不能路径穿越 |
| remember 追加 note | 写入目标 topic，更新 `updated_at` |
| 单条 note 截断 | 超长 note 不撑爆 memory |
| topic 文件上限 | 超过大小拒绝写入 |
| 中文关键词召回 | “简历/项目/面试/JD”能命中对应 topic |
| trace 安全字段 | 不输出 note 全文 |

### 9.2 `tests/test_memory.py`

| 测试 | 验证点 |
|------|--------|
| recent_files LIFO 淘汰 | 最多 8 个，重复 path 移到最新 |
| POSIX key | Windows 风格路径转为 `a/b.py` |
| file summary freshness | 文件修改后旧摘要不展示 |
| invalidate_file | 写入后摘要失效 |
| task_summary 截断 | 超长摘要截断到 300 |

### 9.3 `tests/test_context_manager.py`

| 测试 | 验证点 |
|------|--------|
| section 顺序 | current_request 最后 |
| current_request 永不裁剪 | preserved rate 恒为 1.0 |
| reduction order | history 先压，prefix 最后 |
| memory topic 注入 | query 命中对应 topic |
| history 参数摘要 | write/patch 大参数不进入 prompt |
| read_file range 去重 | 不同 range 不错误合并 |
| read_file range 上限 | 同一文件超过 3 个 older range 后折叠 |
| over_budget metadata | 触底仍超限时记录 |

### 9.4 集成回归

必须继续通过：

```text
python -m pytest
python -m mico "列出当前目录"
```

新增 smoke：

```text
python -m mico "记住：我的目标岗位是后端开发，主要项目是 mico 本地 coding agent"
python -m mico "根据你记住的信息，帮我准备一段后端开发自我介绍"
```

---

## 十、风险与裁决

| 风险 | 裁决 |
|------|------|
| 跨 run 记忆涉及隐私 | 只写本地 Markdown；`remember` 需要明确工具调用和 approval；trace 不记录正文 |
| 自动记忆容易乱写 | v1 只在用户明确要求记住稳定事实时使用 `remember` |
| 中文召回弱 | 固定面试关键词规则 + 简单中英文 tokenizer，先覆盖主场景 |
| 记忆文件膨胀 | 固定 topic、单条 note 截断、topic 文件大小上限 |
| prompt 变长 | `MEMORY.md` 短索引 + 最多 3 个 relevant topic + section budget |
| agent_loop 复杂化 | hook 放在 `Mico.execute_tool()`，不改主循环 |
| `.mico/` 被 workspace 工具屏蔽 | 长期记忆通过内部 memory store 写入，不走 `write_file` |

---

## 十一、实施顺序

### 阶段 1：长期面试记忆最小闭环

1. 新增 `memory_store.py`。
2. 初始化 `.mico/memory/` 固定 topic 文件。
3. 新增 `remember` 工具和 approval。
4. `PromptBuilder` 注入 `MEMORY.md` 索引 + 相关 topic 摘要。
5. 补 `test_memory_store.py` 和 `remember` 工具测试。

验收：

- 用户能让 mico 记住一条目标岗位/项目经历。
- 下一次 `ask()` 能把相关 memory 注入 prompt。
- trace/report 不泄露 note 全文。

### 阶段 2：任务内 WorkingMemory

1. 新增 `memory.py`。
2. `Mico.execute_tool()` 后更新 recent files、file summary、freshness。
3. prompt 注入 working memory section。
4. 补 freshness 和路径规范化测试。

验收：

- 重复读同一文件不会反复占用历史预算。
- 文件修改后旧摘要不再展示。

### 阶段 3：ContextManager 与预算压缩

1. 新增 `context_manager.py`。
2. `PromptBuilder` 退化为 section 文本工厂。
3. 实现 section budget、history 压缩、metadata。
4. 补 ablation 测试。

验收：

- `current_request_preserved_rate=1.0`。
- 长 history 下 prompt 有可解释压缩。
- write/patch 大参数不会进入 prompt。

---

## 十二、与参考项目的取舍

| 参考设计 | mico 取舍 |
|----------|-----------|
| pico 三层记忆 | 采用 working memory；长期记忆改成面试固定 topic |
| pico context budget | 采用 section 预算和 current_request 不裁剪 |
| pico freshness | 采用 SHA-256 freshness |
| pico 关键词召回 | 采用，但补中文关键词规则 |
| claude-code MEMORY.md 索引 | 采用轻量版，固定 topic，短索引常驻 |
| claude-code Auto Memory | 不采用后台自动抽取 |
| claude-code 四层压缩 | 不采用，只做单层 ContextManager 压缩 |
| embedding/vector DB | 不采用 |
| checkpoint/resume | 不采用，另列未来需求 |
