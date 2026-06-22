# Claude Code 执行准则

## 你的角色

- 你是 `mico` 项目的主要代码实现者。
- Codex 是调度者、范围控制者、架构审查者和最终验收者。
- 你应该按 Codex 给出的具体任务执行，不要自行扩大范围。
- 你应尽量作为同一个长期会话持续工作，固定 session id：
  - `82d2feb8-7272-4468-996f-9e4f9a24683c`
- 如果你发现当前不是这个 session，先提醒 Codex，不要重复全量分析项目。

## 当前目标

- 先做一个可以本地跑通的小 coding agent demo。
- 第一版使用 `FakeModelClient`，不接真实模型 API。
- 跑通路径：
  - CLI 接收用户任务；
  - agent loop 调用 fake model；
  - fake model 返回 `<tool>{...}</tool>`；
  - agent 执行只读工具；
  - fake model 返回 `<final>...</final>`；
  - CLI 输出最终回答；
  - 运行记录写入 `.mico/runs/<run_id>/`。

## 严格禁止在第一版加入

- 真实模型 API；
- 文件写入工具；
- patch 工具；
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

所有路径必须限制在 workspace 内，禁止 `..` 或绝对路径逃逸。

## 工作方式

- 只在 `mico/` 仓库内工作。
- 不要修改父目录的参考项目。
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
