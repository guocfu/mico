# Mico 通用记忆系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 `superpowers:subagent-driven-development` 执行本计划；如必须单线程执行，则使用 `superpowers:executing-plans`。每个阶段开始前使用 `superpowers:test-driven-development`，完成前使用 `superpowers:verification-before-completion`，最终交付前使用 `superpowers:requesting-code-review`。Superpowers 只作为执行方法，不得成为 `mico` 运行时依赖。

## Summary

实现 `mico/analysis/mico-memory-context-design.md` 定稿的通用 coding agent 三层记忆系统：

- `Working Memory`：同一 workspace 默认 session 内跨 run 持久化任务理解、近期文件、文件摘要。
- `Episodic Notes`：session 内自动记录关键工具行为，并按当前请求召回。
- `Durable Memory`：跨 session 的显式长期记忆，通过 `remember(topic, note, tags)` 写入 `.mico/memory/*.md`。
- `ContextManager`：统一拼装 prompt，保证 `current_request` 永远最后，且不再把完整旧 `Mico.history` 作为跨 run 理解来源。

执行前 Claude Code 应先阅读：

- `AGENTS.md`
- `mico/CLAUDE.md`
- `mico/analysis/mico-memory-context-design.md`
- 当前相关实现：`mico/mico/runtime.py`、`mico/mico/prompt.py`、`mico/mico/tool_executor.py`、`mico/mico/tools.py`、`mico/mico/state.py`

## Key Changes

### 1. Session Memory

- [ ] 新增 `mico/mico/session_store.py`：
  - 管理 `.mico/sessions/default.json`。
  - 使用 `state.py` 里类似 `_write_json` 的临时文件 + replace 原子写入方式。
  - v1 只支持默认 session id：`default`；不实现 `--session`、`--new-session`。
  - 读取失败、JSON 损坏或 schema 不兼容时返回空状态，并保留可观测错误信息用于测试或日志。

- [ ] 新增 `mico/mico/memory.py`：
  - 定义 `SessionMemoryState`。
  - 字段至少包含：`task_summary`、`recent_files`、`file_summaries`、`episodic_notes`、`updated_at`。
  - 所有文件路径统一保存为 workspace 相对 POSIX 路径：`Path(rel).as_posix()`。
  - `recent_files` 有固定上限，按最近访问排序。
  - `episodic_notes` 有固定上限，按时间追加，超过上限淘汰最旧项。
  - `task_summary` 为 working memory 中最高优先级内容，不因预算压缩优先丢弃。

- [ ] 修改 `mico/mico/runtime.py`：
  - `Mico.__init__` 增加可选 `session_store` 与 `session_id="default"`，保持现有测试可继续用默认参数构造。
  - 初始化时读取 `SessionMemoryState`。
  - `ask()` 开始时只标记当前 run 起点，不清空 session memory。
  - `ask()` 结束时保存 session memory。
  - 跨 run 理解依赖 `SessionMemoryState` 与 episodic notes，不注入完整旧 `self.history`。

- [ ] 修改工具后置 hook：
  - 在 `Mico.execute_tool()` 或 `_after_tool_result()` 内更新 memory。
  - `agent_loop.py` 不直接感知 memory。
  - `read_file` 成功后记录 recent file，并生成或更新简短 file summary。
  - `write_file` / `apply_patch` 成功后使对应 file summary 失效或更新 freshness。
  - `search` / `list_files` 成功后可追加简短 episodic note，但必须受数量上限约束。
  - `run_command` 只记录命令摘要、退出码和关键结果，不保存大段 stdout。

### 2. Durable Memory 与 `remember`

- [ ] 新增 `mico/mico/memory_store.py`：
  - 管理 `.mico/memory/MEMORY.md` 和 topic 文件。
  - v1 固定 topic 白名单：`profile`、`projects`、`preferences`、`decisions`、`conventions`、`notes`。
  - topic 文件路径固定为 `.mico/memory/{topic}.md`。
  - 写入格式使用追加 Markdown 条目，包含时间、tags、note。
  - `note` 做长度上限保护；超限时拒绝或截断必须在结果中明确说明。
  - Durable memory 通过内部 API 写 `.mico/memory`，不经过 `write_file` 工具，因此不受 `.mico` 工具写入禁区影响。

- [ ] 修改 `mico/mico/tools.py`：
  - 注册 `remember` tool。
  - schema：`topic: string`、`note: string`、`tags?: list[string]`。
  - `remember` 必须 `requires_approval=True`。
  - `remember` 的执行应委托给 `Mico` 或 `DurableMemory`，避免把 workspace 内部记忆写入逻辑塞进普通文件工具。

- [ ] 修改 `mico/mico/tool_executor.py` 与 `mico/mico/cli.py`：
  - 支持通用 approval request，例如 `{tool_name, args, summary}`。
  - 保留现有 shell command approval 行为兼容性。
  - `approval=auto`：允许 `remember`。
  - `approval=ask`：调用 approval callback，向用户展示这是长期记忆写入。
  - `approval=never`：拒绝 `remember`。
  - 现有 `run_command` shell interpreter 审批逻辑不得回退。

### 3. ContextManager 与 Prompt 拼装

- [ ] 新增 `mico/mico/context_manager.py`：
  - 接收 `tool_catalog`、`approval_policy`、`workspace_root`、`user_message`、当前 run history slice、`SessionMemoryState`、`DurableMemory`。
  - 输出现有 `PromptBundle`。
  - section 顺序固定为：
    1. `prefix`
    2. `memory_index`
    3. `relevant_memory`
    4. `working_memory`
    5. `history`
    6. `current_request`
  - `current_request` 永远最后，永不裁剪。
  - `format_reminder` 移入 `prefix` 尾部，不再放在 `current_request` 后面。

- [ ] 修改 `mico/mico/prompt.py`：
  - 把现有大块 prompt 拼装拆成可复用 section 方法。
  - 保留 `PromptBundle`。
  - `PromptBuilder.build()` 可以作为兼容包装，但 `Mico.build_prompt_bundle()` 应走 `ContextManager`。
  - `history` 只使用当前 run 范围：`agent.history[agent._last_run_history_start:]`，不得把旧 run 的完整 history 自动注入 prompt。

- [ ] 实现 v1 召回与预算：
  - 默认总预算：`10000` 字符级近似预算即可。
  - section 预算：`prefix=2400`、`memory_index=800`、`relevant_memory=2000`、`working_memory=1000`、`history=3800`。
  - 压缩顺序：`history -> relevant_memory -> working_memory -> memory_index -> prefix`。
  - `current_request` 不参与裁剪。
  - `relevant_memory` 使用简单关键词匹配，不引入 embedding/vector DB。
  - Durable memory 与 episodic notes 合并召回 top-3，超过预算时标记 `over_budget`。

## Test Plan

- [ ] 新增 `tests/test_session_store.py`：
  - 空 session 返回默认 `SessionMemoryState`。
  - 保存后可重新读取。
  - JSON 损坏时不崩溃。
  - 路径统一为 POSIX 相对路径。

- [ ] 新增 `tests/test_memory.py`：
  - `recent_files` 排序与上限正确。
  - `episodic_notes` 上限淘汰正确。
  - `write_file` / `apply_patch` 后文件摘要 freshness 正确变化。
  - 同一文件不同 read range 不简单合并，但总量受上限控制。

- [ ] 新增 `tests/test_memory_store.py`：
  - `remember` 写入正确 topic 文件。
  - 非法 topic 被拒绝。
  - tags 与 note 序列化稳定。
  - `.mico/memory/MEMORY.md` 初始化正确。
  - 超长 note 行为可观测。

- [ ] 新增 `tests/test_context_manager.py`：
  - section 顺序正确。
  - `current_request` 永远最后。
  - `format_reminder` 不在 `current_request` 后。
  - 只注入当前 run history slice。
  - 预算裁剪时 `current_request` 保留，metadata 标记 `over_budget`。

- [ ] 更新现有测试：
  - `tests/test_prompt.py`：适配新的 prompt section 顺序。
  - `tests/test_tool_executor.py`：覆盖 `remember` approval 的 `auto`、`ask`、`never`。
  - `tests/test_agent_loop.py` 或新增集成测试：同一 `Mico` 实例多次 `ask()` 后，第二个 run 能通过 session memory 获得前一 run 的文件/任务理解，但 prompt history 不包含完整旧 run。

- [ ] 最终验证命令：
  - `python -m pytest`
  - 如项目已有更窄测试命令，以 `python -m pytest` 全量通过为最终准入。
  - 不提交 git commit，除非用户另行明确要求。

## Assumptions

- v1 是通用 coding agent 记忆系统，不写“面试”作为系统目标。
- 默认 session 是 workspace-scoped `default`，one-shot 与 REPL 都读写 `.mico/sessions/default.json`。
- 不实现 checkpoint/resume、向量数据库、后台自动长期记忆抽取、多 session CLI。
- `agent_loop.py` 保持不承担 memory 逻辑。
- `.mico` 仍然是普通工具写入禁区；内部 session/memory store 可以写入 `.mico/sessions` 与 `.mico/memory`。
- Claude Code 执行本计划时可以拆分子任务，但不得扩大到权限模型、沙箱、checkpoint 或远程 memory store。
