# mico 子仓库协作规则

## 定位

- 本文件只记录 `mico` 子仓库的差异化规则；全局协作规则见父目录 `../AGENTS.md`。
- `mico` 是一个独立 git 仓库；所有 git 命令都必须在 `mico/` 目录内执行。
- 当前目标是先做一个小而完整、可本地跑通的 coding agent demo。
- git commit 信息建议使用中文说明，并保留 Conventional Commits 类型前缀，例如 `feat: 增加安全补丁工具`。

## 当前实现边界

- 默认 provider 是 `FakeModelClient`，可选真实模型 provider 是 `openai-compatible`。
- 当前闭环：
  - CLI 接收任务；
  - agent loop 构造 prompt 并调用模型；
  - 模型返回 `<tool>{...}</tool>` 或 `<final>...</final>`；
  - agent 经过工具执行边界调用工具；
  - 运行记录写入 `.mico/runs/<run_id>/`。
- 当前允许的工具：
  - `list_files`
  - `read_file`
  - `search`
  - `patch_file`：精确文本替换，受 approval policy 控制。

## 暂不实现

- 不把真实模型 API 作为默认配置。
- 不加入 `write_file` 工具或 shell 工具。
- 不做 git 自动提交。
- 不做交互式 REPL、Web UI、后台任务或任务队列。
- 不做长期记忆、多 agent、复杂权限 UI 或上下文压缩。

## 参考项目使用

- 未经用户或 Codex 明确要求，不要主动全量分析父目录参考项目。
- 需要借鉴时，优先参考 `pico` 和 `claude-code`，再按需参考 `learn-claude-code-main`、`nanobot-main`。
- 参考项目结论应先写入对应分析文档，再由 Codex 决定是否进入 `mico`。

## Claude Code 协作

- Claude Code 负责实现初稿、补测试、根据失败修复和整理说明。
- Codex 负责任务边界、范围控制、架构审查、测试验收和最终接受。
- Codex 调用 Claude Code 时必须给出明确、可执行、范围有限的任务。
- 不要把本机 Claude Code session id、固定 resume 命令或一次性运行句柄写入仓库文件；这类信息属于本地运行态。
- 如果需要从新会话继续，先阅读本文件、`CLAUDE.md`、`analysis/mico-improvement-framework.md`，再查看 `git status --short` 和 `git diff`。

## 验收

- 每次主要实现后至少运行：
  - `python -m pytest`
  - `python -m mico "列出当前目录"`
- 验收时确认默认 fake provider 不需要 API key 或网络访问。
- 验收时确认 `.mico/runs/` 下生成：
  - `trace.jsonl`
  - `state.json`
  - `report.json`
