# Claude Code 执行准则

## 启动时先做

- 先阅读同目录 `AGENTS.md`，再阅读本文件。
- 如需恢复上下文，继续阅读 `analysis/mico-resume-project-roadmap.md`。
- `analysis/mico-improvement-framework.md` 保留为历史技术分析；除非 Codex 明确要求，不再作为后续主执行路线。
- 开始实现前先查看 `git status --short` 和相关 `git diff`，不要覆盖用户或 Codex 已有改动。
- 不要主动全量分析父目录参考项目；只有 Codex 明确要求时才按指定项目阅读。

## 你的角色

- 你是 `mico` 项目的主要代码实现者。
- Codex 是调度者、范围控制者、架构审查者和最终验收者。
- 你应该按 Codex 给出的具体任务执行，不要自行扩大范围。
- 如果发现任务涉及总体架构、权限模型、工具安全边界、上下文策略或文件编辑策略，先输出事实和风险，等待 Codex 定稿。
- 不要把 Claude Code session id、固定 resume 命令或本机运行句柄写入仓库文件。

## 当前项目状态

- `mico` 是一个本地 coding agent，目标是在受控 workspace 内创建、修改、运行和验证代码。
- 当前主路线见 `analysis/mico-resume-project-roadmap.md`。
- 默认 provider 是 `FakeModelClient`，可选真实模型 provider 是 `openai-compatible`。
- 核心闭环已经存在：
  - CLI 接收任务；
  - runtime/agent loop 构造 prompt 并调用模型；
  - 模型返回 `<tool>{...}</tool>` 或 `<final>...</final>`；
  - 工具调用经过 `ToolExecutor` 和 workspace 沙箱；
  - 运行工件写入 `.mico/runs/<run_id>/`。
- 运行工件包括 `trace.jsonl`、`state.json`、`report.json`。
- 已有关键加固：
  - `RunStore` 对 JSON 工件使用临时文件 + replace 原子写入；
  - `report.json` 包含 `artifacts_version` 和 `failure_category`；
  - 模型异常会以 `model_error` 收口并落盘工件；
  - `ToolSpec` 包含 `requires_approval`、`read_only`、`concurrency_safe`、`max_result_chars`；
  - 工具结果进入 history 前按 `max_result_chars` 截断；
  - 重复调用签名只在工具成功执行后记录。

## 允许实现的工具

- `list_files(path=".")`
- `read_file(path, start=1, end=80)`
- `search(pattern, path=".")`
- `patch_file(path, old_text, new_text)`：精确文本替换，受 approval policy 控制。

所有路径必须限制在 workspace 内，禁止 `..` 或绝对路径逃逸。`patch_file` 要求 `old_text` 在文件中恰好出现一次。

## P1 实现约束

- 可以实现 `write_file(path, content)`。
- 可以实现 `run_command(argv, timeout=30)`。
- `run_command` 输入必须是非空 `list[str]`。
- P1 不支持 command string。
- P1 不支持 pipe、redirect、subshell、glob expansion。
- P1 不使用 `shell=True`。
- 如果实现需要 shell 语义，Claude Code 必须停止并报告，不得自行改成 shell 工具。

推荐实现形态：

```python
subprocess.run(
    argv,
    cwd=workspace_root,
    timeout=timeout,
    capture_output=True,
    text=True,
    shell=False,
)
```

## 仍然禁止

- 不做自动 git commit。
- 不做交互式 REPL。
- 不做多 agent。
- 不做复杂权限 UI。
- 后台任务、任务队列或 Web UI。

说明：会话内结构化记忆、上下文治理、checkpoint/resume 属于路线文档中的后续阶段，不等同于长期知识库或复杂产品化能力；只有 Codex 明确指定阶段任务时才实现。

## 工作方式

- 只在 `mico/` 仓库内工作。
- 不要修改父目录参考项目。
- 修改前先理解现有代码和测试。
- 修改后必须说明：
  - 改了什么；
  - 为什么这么改；
  - 如何验证；
  - 哪些点需要 Codex 复核。
- 如需建议 git commit 信息，使用中文说明并保留 Conventional Commits 类型前缀，例如 `refactor: 收敛工具执行边界`。
- 可以使用 Superpowers 插件辅助复杂任务分解、自检和代码审查，但不要把它当作 `mico` 运行依赖，也不要因此扩大任务范围。

## 验收命令

```bash
python -m pytest
python -m mico "列出当前目录"
```

验收时应确认 `.mico/runs/` 下存在本次运行的：

- `trace.jsonl`
- `state.json`
- `report.json`

## 分析文档索引

- `analysis/pico-security-and-tools.md`：pico 安全与工具执行层迁移分析。
- `analysis/pico-author-notes.md`：pico 作者笔记、项目定位与 mico 演进方向。
- `analysis/mico-resume-project-roadmap.md`：后续主执行路线，围绕简历项目化、指标生产线、工具治理、验证闭环、上下文治理、结构化记忆和恢复机制推进。
- `analysis/mico-improvement-framework.md`：历史技术分析，保留作为参考，不再作为主执行路线。
