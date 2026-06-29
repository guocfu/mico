# Mico Session ContextManager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让已持久化的 Working Memory 和 Episodic Notes 真正进入 prompt，并保证 `current_request` 永远是最后的上下文锚点。

**Architecture:** 新增轻量 `ContextManager` 负责 section 组装、session memory 注入、episodic note top-3 召回和基础预算 metadata。`PromptBuilder` 退回静态 section 文本工厂，`Mico.build_prompt_bundle()` 改为传入当前 run history slice，暂不实现 DurableMemory / remember。

**Tech Stack:** Python、pytest、当前 `PromptBundle` / `PromptBuilder` / `SessionMemoryState` / `Mico`。

---

## Summary

下一步不做 `remember`，先完成 session 内记忆闭环：

- 现在 `SessionMemoryState` 已经能保存 Working Memory 和 Episodic Notes。
- 但 `PromptBuilder.build()` 没有注入这些记忆。
- `Mico.build_prompt_bundle()` 仍传全量 `self.history`，跨 run 会污染 prompt。
- `current_request` 当前不在最后，后面还有 history 和 format reminder。

本计划实现最小可用 ContextManager：

```text
prefix
working_memory
relevant_memory
history
current_request
```

`current_request` 不裁剪、永远最后。`relevant_memory` 只从 session episodic notes 里召回 top-3；Durable Memory 留到下一阶段。

## Key Changes

### 1. PromptBuilder 拆成 section 工厂

**Files:**
- Modify: `mico/prompt.py`
- Update tests: `tests/test_prompt.py`

- [ ] 保留 `PromptBundle`。
- [ ] 保留 `PromptBuilder.build()` 作为兼容 API，但让它使用新的 section 顺序。
- [ ] 新增或公开以下 section 方法，复用现有静态文案：
  - `prefix_text(tool_catalog, approval_policy, workspace_root)`
  - `history_text(history)`
  - `current_request_text(user_message)`
- [ ] `prefix_text()` 包含：
  - static prefix
  - response contract
  - runtime policy
  - tool catalog
  - system context
  - workspace context
  - format reminder
- [ ] `format_reminder` 移入 prefix 尾部，不再出现在 current request 后。
- [ ] `PromptBuilder.build()` 的最终文本顺序改为：
  - prefix
  - history
  - current request
- [ ] 更新测试断言：
  - `User request: ...` 是 `bundle.text.strip()` 的最后一段。
  - `Reminder:` 出现在 `User request:` 之前。
  - 旧的 section 内容仍存在。

### 2. 新增 ContextManager

**Files:**
- Create: `mico/context_manager.py`
- Create: `tests/test_context_manager.py`

- [ ] 新增 `ContextManager`，构造参数：
  - `prompt_builder=None`
  - `total_budget=10000`
  - `section_budgets=None`
- [ ] 新增 `build(...) -> PromptBundle`：
  - `tool_catalog`
  - `approval_policy`
  - `workspace_root`
  - `user_message`
  - `history`
  - `session_memory`
- [ ] 组装 section：
  - `prefix`
  - `working_memory`
  - `relevant_memory`
  - `history`
  - `current_request`
- [ ] `working_memory` 使用 `session_memory.render_memory_text()`。
- [ ] `relevant_memory` 从 `session_memory.episodic_notes` 召回 top-3。
- [ ] v1 召回规则保持简单：
  - 查询 token 来自 `user_message.lower()` 的英文/数字下划线词。
  - note 命中条件：query token 命中 note text/source/tags 任一项。
  - 排序：命中数多优先；`note_index` 大优先。
  - 如果没有命中，不注入 note。
- [ ] `current_request` 永远最后，不参与裁剪。
- [ ] metadata 至少包含：
  - `prompt_chars`
  - `total_budget`
  - `over_budget`
  - `section_chars`
  - `history_items_total`
  - `history_items_used`
  - `episodic_notes_available`
  - `episodic_notes_used`
  - `current_request_chars`
  - `current_request_preserved_rate: 1.0`
- [ ] 预算 v1 只做可观测，不做复杂压缩：
  - 如果总字符数超过 `total_budget`，设置 `over_budget=True`。
  - 不裁剪 current request。
  - 历史仍复用 `PromptBuilder.history_text()` 的最近 6 条策略。

### 3. Mico 接入 ContextManager

**Files:**
- Modify: `mico/runtime.py`
- Update tests: `tests/test_agent_loop.py` 或新增 `tests/test_runtime_context.py`

- [ ] `Mico.__init__` 初始化：
  - `self._context_manager = ContextManager(self._prompt_builder)`
- [ ] `build_prompt_bundle()` 改为调用 `ContextManager.build()`。
- [ ] 传入 history slice：
  - `self.history[self._last_run_history_start:]`
- [ ] 保持 `build_prompt()` API 不变。
- [ ] `_last_prompt_metadata` 继续记录 bundle metadata。
- [ ] 不修改 `agent_loop.py` 的 memory 逻辑。
- [ ] 新增集成测试：
  - 第一次 `ask()` 读文件，session memory 产生 file summary / episodic note。
  - 第二次 `ask()` 的模型 prompt 包含 `Working memory:` 和文件摘要。
  - 第二次 prompt 包含相关 episodic note。
  - 第二次 prompt 不包含第一次 run 的完整旧 history，如旧 user message 或旧 final。
  - 第二次 prompt 最后一段是当前用户请求。

### 4. Claude Code 执行约束

Claude Code 执行时必须：

- [ ] 读取：
  - `AGENTS.md`
  - `CLAUDE.md`
  - `analysis/mico-memory-context-design.md`
  - 本计划文件
- [ ] 使用 Superpowers：
  - `superpowers:executing-plans` 或 `superpowers:subagent-driven-development`
  - 每个任务用 `superpowers:test-driven-development`
  - 完成前用 `superpowers:verification-before-completion`
- [ ] 不实现：
  - DurableMemory
  - `remember`
  - `.mico/memory/*.md`
  - checkpoint/resume
  - embedding/vector DB
  - 后台自动记忆抽取
- [ ] 不提交 git commit，除非用户另行明确要求。
- [ ] 不修改父目录参考项目。

## Test Plan

- [ ] RED/GREEN 运行 prompt section 测试：

```bash
python -m pytest tests/test_prompt.py -v
```

- [ ] RED/GREEN 运行 ContextManager 单测：

```bash
python -m pytest tests/test_context_manager.py -v
```

- [ ] RED/GREEN 运行 runtime/session memory 集成测试：

```bash
python -m pytest tests/test_agent_loop.py -k "session_memory or context" -v
```

- [ ] 完整回归：

```bash
python -m pytest
```

- [ ] 如果全量测试失败，必须报告失败用例，并区分是否为本次变更引入。

## Acceptance Criteria

- `current_request` 是 prompt 最后一段。
- `format_reminder` 不再出现在 `current_request` 后。
- `working_memory` 出现在 prompt，且包含 task summary / recent files / file summaries。
- `read_file` 产生的 episodic note 能在后续 run 中被当前请求召回。
- 新 run 的 prompt 不自动注入上一 run 的完整 `Mico.history`。
- prompt metadata 能看出各 section 字符数、episodic note 使用数量和是否 over budget。
- `python -m pytest` 通过，或明确报告非本变更导致的既有失败。

## Claude Code Handoff Prompt

```text
你在 E:\Project\ai\my-coding-agent\mico 仓库工作。必须始终使用简体中文回复。

任务：执行 “Mico Session ContextManager Implementation Plan”。

硬性要求：
1. 必须使用 Superpowers：先使用 superpowers:executing-plans 或 superpowers:subagent-driven-development 读取计划并分任务执行；每个任务使用 superpowers:test-driven-development；完成前使用 superpowers:verification-before-completion。
2. 只实现 ContextManager + session memory prompt 注入闭环。
3. 不实现 DurableMemory、remember、.mico/memory、checkpoint/resume、embedding/vector DB、后台自动记忆抽取。
4. 不要 git commit，不要切换分支。
5. 必须先写失败测试，确认失败，再写实现。
6. 保证 current_request 永远最后，format_reminder 不在 current_request 后。
7. Mico.build_prompt_bundle() 必须只传当前 run history slice：self.history[self._last_run_history_start:]。
8. 完成后报告：修改文件、RED/GREEN 证据、测试命令和结果、是否有全量测试失败。
```

## Assumptions

- 当前分支 `feature/mico-memory-system` 可以继续使用。
- 当前工作树应保持干净后再执行。
- v1 不做复杂预算裁剪，只提供 `over_budget` 和 `section_chars` 可观测性。
- v1 只召回 session episodic notes；Durable Memory 是下一份计划。
- 召回不做中文 tokenizer，本阶段先用英文/路径/扩展名/tag 命中，避免扩大范围。
