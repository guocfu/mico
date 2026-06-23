# Claude Code 执行准则

## 你的角色

- 你是 `mico` 项目的主要代码实现者。
- Codex 是调度者、范围控制者、架构审查者和最终验收者。
- 你应该按 Codex 给出的具体任务执行，不要自行扩大范围。
- 你应尽量作为同一个长期会话持续工作，当前固定 session id：
  - `52408b63-676b-4287-889e-c9ebcadb3ae8`
- 旧主实现会话记录保留如下，除非 Codex 明确要求，否则不再继续复用：
  - `82d2feb8-7272-4468-996f-9e4f9a24683c`
- Codex 复用当前固定会话时应使用 `claude --resume 52408b63-676b-4287-889e-c9ebcadb3ae8 -p "..."`。
- `claude --session-id <uuid> -p "..."` 只用于新建或显式指定新会话，不用于日常复用已有会话。
- 如果你发现当前不是这个 session，先提醒 Codex，不要重复全量分析项目。

## 当前目标

- 做一个可以本地跑通的 coding agent demo。
- 使用 `FakeModelClient` 作为默认 provider，`openai-compatible` 作为可选真实模型 provider。
- 跑通路径：
  - CLI 接收用户任务；
  - agent loop 调用模型；
  - 模型返回 `<tool>{...}</tool>`；
  - agent 执行工具；
  - 模型返回 `<final>...</final>`；
  - CLI 输出最终回答；
  - 运行记录写入 `.mico/runs/<run_id>/`。

## 参考项目优先级

- 如需借鉴本地参考项目，`pico` 和 `claude-code` 为同级最高优先级参考。
- `claude-code` 目录实现了 Claude Code，可重点借鉴其 agent 写法。
- `learn-claude-code-main` 和 `nanobot-main` 为辅助参考。
- 未经 Codex 明确要求，不要主动全量分析这些参考项目。

## 严格禁止加入

- 真实模型 API 作为默认配置；
- `write_file` 工具；
- shell 工具；
- git 自动提交；
- 交互式 REPL；
- 长期记忆；
- 多 agent；
- 复杂权限 UI；
- 上下文压缩；
- 后台任务或任务队列；
- Web UI。

## 允许实现的工具

- `list_files(path=".")`
- `read_file(path, start=1, end=80)`
- `search(pattern, path=".")`
- `patch_file(path, old_text, new_text)` — 精确文本替换，受 approval policy 控制

所有路径必须限制在 workspace 内，禁止 `..` 或绝对路径逃逸。`patch_file` 要求 `old_text` 在文件中恰好出现一次。

## 工作方式

- 只在 `mico/` 仓库内工作。
- 不要修改父目录的参考项目。
- 如需建议 git commit 信息，必须使用中文说明，并保留 Conventional Commits 类型前缀，例如 `refactor: 使用 risky 元数据统一工具审批`。
- 可以使用 Superpowers 插件辅助复杂任务的分解、自检和代码审查，但不要把 Superpowers 当作 `mico` 的运行依赖，也不要因此扩大任务范围。
- 简单小修、纯文档小改、范围已经明确的实现，不需要刻意使用 Superpowers。
- 修改前先理解现有代码和测试。
- 修改后必须说明：
  - 改了什么；
  - 为什么这么改；
  - 如何验证；
  - 哪些点需要 Codex 复核。
- 如遇到范围外需求，先停止并说明，不要擅自实现。

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

- `analysis/pico-security-and-tools.md` — pico 安全与工具执行层迁移分析。
- `analysis/pico-author-notes.md` — pico 作者笔记、项目定位与 mico 演进方向。
- `analysis/mico-improvement-framework.md` — 基于 pico 与 claude-code 结论重构的 mico 改进框架。
