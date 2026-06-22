# mico 项目记忆

## 必须遵守

- 始终使用简体中文回复。
- `mico` 是一个独立 git 仓库；所有 git 操作都必须在 `mico/` 目录内执行。
- 当前阶段目标是先做一个小的 coding agent demo，可以本地跑通。
- 严格控制范围：先跑通最小闭环，再逐步借鉴 `pico`、`learn-claude-code-main`、`nanobot-main`。

## Codex 与 Claude Code 分工

- Claude Code 是 `mico` 的主要代码实现者。
- Codex 是调度者、任务拆分者、范围控制者、架构审查者和最终验收者。
- Codex 不应直接承担大段主要实现代码，除非：
  - Claude Code 连续失败或超时；
  - 用户明确要求 Codex 直接修改；
  - 只是在做很小的修复、规则文件更新、测试调整或审查反馈落地。
- Claude Code 可以负责：
  - 主要源码实现；
  - 根据 Codex 的明确任务修改代码；
  - 补测试；
  - 根据测试失败修复问题；
  - 整理实现说明。
- Codex 必须负责：
  - 明确任务边界；
  - 防止范围膨胀；
  - 审查 Claude Code 的改动；
  - 运行测试和 CLI 验收；
  - 决定是否接受实现。

## 当前实现策略

- 第一版只做最小 demo，不接真实模型。
- 使用 `FakeModelClient` 跑通：
  - CLI 接收任务；
  - agent loop 构造 prompt；
  - fake model 返回 `<tool>{...}</tool>`；
  - agent 执行只读工具；
  - fake model 返回 `<final>...</final>`；
  - CLI 打印最终答案；
  - 运行记录写入 `.mico/runs/<run_id>/`。
- 第一版只允许只读工具：
  - `list_files`
  - `read_file`
  - `search`
- 第一版不做：
  - 真实模型 API；
  - 文件写入或 patch 工具；
  - 交互式 REPL；
  - 长期记忆；
  - 多 agent；
  - 复杂权限 UI；
  - 上下文压缩；
  - 任务队列或后台任务。

## 对参考项目的使用

- 不要在第一版实现前全量分析三个参考项目。
- 第一版可以轻量参考 `pico/examples/mini-pico` 的模块拆分和最小 agent loop。
- 需要借鉴其他项目时，由 Claude Code 分项目分析，并把结论写入对应项目的 `CLAUDE.md` 或分析文档。
- Codex 负责把参考项目结论筛选后决定是否进入 `mico`。

## Claude Code 调用规则

- Codex 调用 Claude Code 时，必须给出明确、可执行、范围有限的任务。
- `mico` 主实现 Claude Code 会话必须固定复用同一个 session id：
  - `82d2feb8-7272-4468-996f-9e4f9a24683c`
- Codex 后续调用 Claude Code 处理 `mico` 主要实现任务时，必须使用：
  - `claude --session-id 82d2feb8-7272-4468-996f-9e4f9a24683c -p "..."`
- 除非用户明确要求更换会话，不要新建随机 Claude Code 会话来处理 `mico` 主要实现。
- 如果固定 session 调用失败，Codex 应先报告失败原因；只有在用户同意或连续失败阻塞时，才允许改用新 session，并必须把新的 session id 写回本文件和 `CLAUDE.md`。
- Claude Code 每次任务应优先在 `mico/` 内完成，不跨目录改动。
- Claude Code 输出后，Codex 必须复核：
  - 是否符合最小 demo 范围；
  - 是否引入不必要依赖；
  - 是否破坏路径安全；
  - 是否有测试覆盖；
  - 是否能通过 CLI 验收。

## 测试和验收

- 每次主要实现后必须运行：
  - `python -m pytest`
  - `python -m mico "列出当前目录"`
- 验收标准：
  - 测试全部通过；
  - CLI 能打印最终回答；
  - `.mico/runs/` 下生成 `trace.jsonl`、`state.json`、`report.json`；
  - 不需要任何 API key 或网络访问。
