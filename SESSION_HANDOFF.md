# Session Handoff

Updated: 2026-06-22 20:55 local time
Project: mico
Branch: master

## Current Goal
- 继续实现一个本地小型 coding agent，当前阶段目标是保持 demo 可跑通，并逐步补齐安全、trace、工具调用与上下文能力。
- 本次刚完成的计划是：截断 trace 中 `tool_executed` 的工具参数，避免大块 `patch_file.old_text/new_text` 撑爆 trace。

## Completed
- `mico` 已有可运行 CLI demo。
- 已支持 `fake` provider 和 OpenAI-compatible provider。
- 已有工具：`list_files`、`read_file`、`search`、`patch_file`。
- 已有安全能力：workspace 路径沙箱、symlink 逃逸测试、Windows cross-drive 处理、`ToolSpec.risky`、`approval=never` 拒绝 risky 工具、trace/report 脱敏、连续重复工具调用检测。
- 当前未提交变更实现了 `clip_artifact(value, limit=500)`，并在 `tool_executed` trace 中截断 `args`。
- `agent.history` 仍保留原始完整 `args`，没有改变工具执行、CLI、provider 或 approval 行为。

## Current State
- 工作目录：`E:\Project\ai\my-coding-agent\mico`
- `mico` 是独立 git 仓库，所有 git 操作必须在 `mico/` 内执行。
- 当前分支：`master`
- HEAD：`043951a`
- 当前有未提交代码变更，且 `SESSION_HANDOFF.md` 是新建未跟踪文件。
- 用户要求以后 git commit 信息使用中文说明并带 Conventional Commits 前缀，例如 `fix: 截断 trace 中的工具参数`。
- 不要提交 `.mico/`、`.tmp/`、`.claude/` 这类运行产物。

## Workspace Identity
- Project name: mico
- Git root name: mico
- Relative path: `mico`
- Branch: `master`
- HEAD: `043951a`
- Local root observed at save time: `E:\Project\ai\my-coding-agent\mico`
- Dirty files: `mico/agent_loop.py`, `mico/workspace.py`, `tests/test_agent_loop.py`, `tests/test_tools.py`, `SESSION_HANDOFF.md`

## Key Files
- `mico/agent_loop.py`: agent 主循环；当前在 `tool_executed` trace payload 中使用 `clip_artifact(args, 500)`。
- `mico/workspace.py`: workspace 路径沙箱与通用截断 helper；新增 `clip_artifact`。
- `mico/runtime.py`: `emit_trace()` 会对 event 调用 `redact_artifact()`，所以 trace 参数先截断再脱敏。
- `mico/security.py`: trace/report 脱敏逻辑。
- `tests/test_agent_loop.py`: 覆盖 trace 参数截断、history 不截断、脱敏仍生效。
- `tests/test_tools.py`: 覆盖 `clip_artifact` 对字符串、dict、list、tuple、非字符串的递归处理。
- `analysis/pico-security-and-tools.md`: pico 工具、安全、approval、trace 设计分析。
- `analysis/pico-author-notes.md`: pico 作者说明 PDF 的提炼，包含面试/简历表达方向。

## Decisions
- 不使用 LangGraph；此前已确认 `pico` 也未使用 LangGraph。
- Codex 作为调度者、架构决策者和最终审查者；Claude Code 作为高额度执行者，负责主要实现、单项目深读和重复性改动。
- Claude Code 必须尽量复用固定会话，避免重复读项目。
- 固定 Claude Code 会话 ID：`82d2feb8-7272-4468-996f-9e4f9a24683c`
- 调用 Claude Code 示例：
  `claude --resume 82d2feb8-7272-4468-996f-9e4f9a24683c --permission-mode bypassPermissions -p "..."`
- Claude Code 可以使用 Superpowers 辅助复杂任务，但 Superpowers 不能成为 `mico` 的运行依赖，也不能扩大项目范围。
- 当前不新增 LangGraph、REPL、多 agent、shell 工具、`write_file` 或接入 Claude CLI 作为 mico 的运行能力。

## Verification
- 已运行：`$env:TMP = "$PWD\.tmp"; $env:TEMP = "$PWD\.tmp"; New-Item -ItemType Directory -Force -Path .tmp | Out-Null; python -m pytest`
- 结果：`80 passed, 1 skipped`
- 已运行：`$env:TMP = "$PWD\.tmp"; $env:TEMP = "$PWD\.tmp"; python -m mico --provider fake "列出当前目录"`
- 结果：正常返回 `mico inspected the workspace and completed the request.`
- 已运行：`git diff --check`
- 结果：无空白错误；仅有 Windows 换行提示。
- 注意：直接运行 pytest 如果使用用户目录 Temp，可能因沙箱权限报 `PermissionError`；应把 `TMP/TEMP` 指到仓库内 `.tmp`。

## Open Questions
- 是否将当前变更提交到 git。
- 下一阶段优先做哪类能力：上下文压缩、工具 schema/审批提示、run resume、模型错误恢复，或更接近 pico 的 plan/act 循环。
- 是否需要让 Claude Code 进一步分析 `pico` 的具体某个模块；不要在无明确需求时全量分析参考项目。

## Next Steps
- 1. 读取本 handoff 并确认 `git status --short` 与这里记录一致。
- 2. 如继续当前变更，先查看 diff：`git diff -- mico\agent_loop.py mico\workspace.py tests\test_agent_loop.py tests\test_tools.py SESSION_HANDOFF.md`。
- 3. 重新运行验证：`$env:TMP = "$PWD\.tmp"; $env:TEMP = "$PWD\.tmp"; python -m pytest`。
- 4. 如用户要求提交，建议提交信息：`fix: 截断 trace 中的工具参数`。
- 5. 提交后再生成下一步计划，建议从“上下文压缩/历史裁剪策略”或“工具 schema 与审批提示可观测性”中选一个小闭环。

## Next Session Opening Message

### Read Only
```text
Use session-handoff to read SESSION_HANDOFF.md in read-only mode. Do not modify files or run mutating commands. Restate the current goal, current state, risks/blockers, verification status, and recommended next action.
```

### Continue
```text
Use session-handoff to read SESSION_HANDOFF.md, verify local state, then continue from Next Steps. Before changing files, briefly restate the current goal and planned first action.
```

## Notes For Next Session
- 始终使用简体中文回复。
- 用户偏好：执行为主，计划要具体；需要遵守 Codex/Claude Code 分工。
- 项目内 git 操作必须在 `E:\Project\ai\my-coding-agent\mico` 内执行。
- 父目录参考项目：`pico` 是最高优先级参考，`learn-claude-code-main` 和 `nanobot-main` 是辅助参考；不要未经用户明确要求主动全量分析。
- `后端agent开发资料\后端_agent开发资料\2-pico.pdf` 是 pico 作者说明和简历写法资料，后续可按需让 Claude Code 分析。
- 已确认 `.tmp/2-pico.txt` 是临时提取物，不要提交。
