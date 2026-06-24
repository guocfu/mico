# mico 子仓库协作规则

## 定位

- 本文件只记录 `mico` 子仓库的差异化规则；全局协作规则见父目录 `../AGENTS.md`。
- `mico` 是一个独立 git 仓库；所有 git 命令都必须在 `mico/` 目录内执行。
- 当前目标是把 `mico` 迭代成一个可以真实创建、修改、运行和验证代码的本地 coding agent。
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

## P1 允许实现

- P1 允许实现 `write_file(path, content)` 和 `run_command(argv, timeout=30)`。
- `run_command` 不是通用 shell 字符串工具；输入必须是非空 `list[str]`。
- 允许将真实模型 API 作为默认配置，方便直接运行真实 agent。

## Codex 安全审查要求

Codex 在接受 P1 实现前必须审查以下内容：

- `run_command` 是否使用 argv list（不是 command string）。
- `run_command` 是否使用 `shell=False`。
- `run_command` 的 cwd 是否固定在 workspace root。
- approval policy 是否能拦截 `write_file` 和 `run_command`。
- timeout、stdout/stderr 截断、路径逃逸保护是否到位。

## 仍然禁止

- 不做自动 git commit。
- 允许最小 CLI REPL（轻量命令行入口，用于接收用户任务并启动 agent loop）；不做 Web UI、后台任务或任务队列。
- 不做多 agent 系统。
- 不做复杂权限 UI。
- 不做 checkpoint / memory / context governance，除非后续真实任务暴露明确痛点。

说明：最小 CLI REPL 是轻量入口，不等于复杂会话系统、slash command、补全、TUI 或多会话恢复。

## 参考项目使用

- 未经用户或 Codex 明确要求，不要主动全量分析父目录参考项目。
- 需要借鉴时，优先参考 `pico` 和 `claude-code`，再按需参考 `learn-claude-code-main`、`nanobot-main`。
- 参考项目结论应先写入对应分析文档，再由 Codex 决定是否进入 `mico`。

## Claude Code 协作

- Claude Code 负责实现初稿、补测试、根据失败修复和整理说明。
- Codex 负责任务边界、范围控制、架构审查、测试验收和最终接受。
- Codex 调用 Claude Code 时必须给出明确、可执行、范围有限的任务。
- 如果 Codex 调用 Claude Code 失败、超时、被权限拦截或没有产出可用改动，Codex 不应直接替 Claude Code 完成实现；应先向用户说明失败原因，并询问下一步是重试 Claude Code、调整任务范围，还是授权 Codex 接手。
- 不要把本机 Claude Code session id、固定 resume 命令或一次性运行句柄写入仓库文件；这类信息属于本地运行态。
- 如果需要从新会话继续，先阅读本文件、`CLAUDE.md`、`analysis/mico-resume-project-roadmap.md`，再查看 `git status --short` 和 `git diff`。
- `analysis/mico-improvement-framework.md` 保留为历史技术分析，不再作为后续主执行路线。

## 验收

- 每次主要实现后至少运行：
  - `python -m pytest --basetemp .tmp/pytest-basetemp`
  - `python -m mico "列出当前目录"`
- 运行 pytest 时优先把临时目录固定到仓库内的 `.tmp/`，减少 Codex 沙箱因系统临时目录读写而触发额外授权；如需区分多次运行，可使用 `.tmp/pytest-basetemp-<task>`。
- 验收时确认默认 fake provider 不需要 API key 或网络访问。
- 验收时确认 `.mico/runs/` 下生成：
  - `trace.jsonl`
  - `state.json`
  - `report.json`
