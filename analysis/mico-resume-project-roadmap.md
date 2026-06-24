# Mico 实用型 Local Coding Agent 路线

> 日期：2026-06-24
> 状态：后续主执行路线
> 说明：`analysis/mico-improvement-framework.md` 保留为历史技术分析；`analysis/claude code.md` 和 Opus 4.8 架构评审作为本次重定位参考。后续功能迭代、Claude Code 实现任务和 Codex 审查，优先以本文为准。

## 1. 项目定位

`mico` 的目标是做一个**能在本地仓库里实际完成代码任务的 CLI coding agent**。

它首先要能用，其次才是好测试、好复盘、好写进简历。当前项目已有模型调用、工具循环、workspace 沙箱、运行工件和 benchmark 基础，但缺少两个实际 coding agent 的最低能力：

- 创建新文件。
- 运行项目命令并根据失败输出继续修复。

目标闭环：

```text
用户任务
  -> 模型理解任务
  -> 工具读取/搜索代码
  -> 创建或修改文件
  -> 运行测试或验证命令
  -> 根据失败输出继续修复
  -> 生成 trace/state/report/verification 工件
```

当前应避免继续扩大评测框架。benchmark 和 metrics 保留为回归质量证明，但不再主导产品方向。

## 2. 产品原则

### 2.1 先做能工作的 agent

路线图优先级按“真实编码任务是否必须”排序：

1. 能创建和修改文件。
2. 能运行测试、lint 或脚本。
3. 能看懂失败输出并继续修复。
4. 能留下可审计的运行记录。
5. 能通过 demo 证明真实可用。

上下文治理、结构化记忆、checkpoint/resume 和行区间编辑等能力暂缓，只有当 P1-P2 跑真实任务或录制 demo 时暴露出明确痛点，再进入 Backlog 实现。

### 2.2 工具能力要受控，不要因安全焦虑取消能力

`write_file` 和 `run_command` 是 P1 核心能力。安全边界通过工具治理实现：

- 所有文件路径必须限制在 workspace 内。
- 修改型或副作用型工具必须 `requires_approval=True`。
- `approval=never` 必须阻断写文件和命令执行。
- 命令执行固定 cwd 为 workspace root。
- 命令执行必须有 timeout、exit code、duration 和输出截断。
- trace/report 中记录工具调用摘要，并对敏感信息脱敏。

### 2.3 真实 provider 是使用路径，fake provider 是测试工具

- 有 `MICO_API_KEY` 时，CLI 应默认选择 OpenAI-compatible provider。
- `MICO_BASE_URL` 和 `MICO_MODEL` 应有合理默认值。
- `--provider fake` 必须保留，用于离线测试、deterministic benchmark 和 CI。

### 2.4 文档和演示比复杂架构更重要

P1-P2 完成后，应优先做 P6：README、demo guide、录屏和 safety model。一个能展示 mico 完成真实任务的 2 分钟录屏，比提前实现高级编辑、memory 或 checkpoint 更有价值。

## 3. 核心架构

### 3.1 Interface & Config

职责：

- 解析 one-shot prompt、workspace、provider、approval、max steps、verify command。
- 读取 `.env` 和系统环境变量。
- 默认 fake provider 不需要网络；真实 provider 通过 `MICO_API_KEY` 自动启用。

P1 目标：

- 有 API key 即可使用真实模型。
- 缺少 base URL 时默认 `https://api.openai.com/v1`。
- 缺少 model 时默认一个轻量可用模型，例如 `gpt-4o-mini`。
- 显式 `--provider fake` 时强制离线 fake provider。

### 3.2 Agent Runtime

职责：

- 组装 model client、prompt builder、tool executor、workspace、run store。
- 执行模型请求、解析 `<tool>` / `<final>`、调用工具、记录 history。
- 控制 step limit，避免真实模型无限循环。
- 将模型异常、解析失败、工具失败、命令失败都归入 report。

P1-P2 目标：

- 支持短链路：读文件 -> 写文件 -> 运行命令 -> 读取失败 -> 再修改。
- 工具失败必须返回清晰、可供模型重试的错误文本。
- report 能回答：改了哪些文件、运行了哪些命令、最终验证是否通过。

### 3.3 Tool System

当前工具：

- `list_files(path=".")`
- `read_file(path, start=1, end=80)`
- `search(pattern, path=".")`
- `patch_file(path, old_text, new_text)`

P1 新增工具：

- `write_file(path, content)`：创建或覆盖 UTF-8 文件。
- `run_command(argv, timeout=30)`：在 workspace root 执行命令。

`run_command` 必须采用明确 argv 设计：

```python
subprocess.run(
    argv,
    cwd=str(workspace.root),
    timeout=timeout,
    capture_output=True,
    text=True,
    shell=False,
)
```

约束：

- `argv` 必须是非空 `list[str]`。
- 不在 P1 支持管道、重定向、命令字符串或系统 shell。
- `timeout` 默认 30 秒，允许范围 1 到 300 秒。
- stdout/stderr 只返回 tail，建议每个最多 2000 chars。
- 返回 exit code、timed_out、duration_ms、stdout_tail、stderr_tail。

如未来确实需要 shell 语义，应新增单独的 `run_shell` 设计和安全说明，不把它混入 P1。

### 3.4 Workspace Safety

职责：

- 阻止 `..`、绝对路径和 workspace 外路径。
- 控制工具输出长度。
- 对 trace/report 进行敏感信息脱敏。
- 记录 changed files、files written、patches applied、commands run。

写入规则：

- `write_file` 可以创建父目录，但路径仍必须在 workspace 内。
- `patch_file` 继续用于精确替换。
- `replace_range` 进入 Backlog，不要在 P1 扩大编辑系统。

### 3.5 Tool Result Format

工具结果要简单、稳定、适合模型阅读。

建议格式：

```text
ok=true tool=write_file path=src/foo.py bytes=123
```

```text
ok=false tool=patch_file error_kind=ambiguous_match message="old_text appears 2 times"
```

`run_command` 返回建议：

```text
ok=false tool=run_command exit_code=1 timed_out=false duration_ms=842
stdout_tail:
...
stderr_tail:
...
```

要求：

- 不返回原始 JSON 大对象给模型。
- 错误必须有 `error_kind` 或等价短标签。
- 命令失败不等于工具调用失败；命令 exit code 非 0 应作为模型可继续修复的信息。

### 3.6 Verification Strategy

`run_command` 和 `--verify-cmd` 分工明确：

- `run_command` 是模型工具，用于任务过程中运行测试、读取失败输出并继续修复。
- `--verify-cmd` 是 CLI 最终验收门，由用户显式传入，在 agent 结束后执行。

因此 P1/P2 不删除 `--verify-cmd`。两者共同构成：

```text
模型自主迭代验证：run_command
用户最终外部验收：--verify-cmd
```

### 3.7 Prompt Strategy

系统提示应聚焦实际 coding agent 行为：

- 先理解任务和现有文件，再修改。
- 需要新文件时使用 `write_file`。
- 需要验证时使用 `run_command`。
- 不要声称测试通过，除非已经看到命令或验证结果。
- 工具失败后根据错误信息调整策略。
- final answer 只总结实际完成的工作和验证结果。

P1 只更新静态前缀和工具说明，不做复杂 prompt 优化。

### 3.8 Evaluation

保留现有 benchmark，但只作为回归安全网：

- fake provider 用于 deterministic tests。
- benchmark 覆盖工具治理和基础能力。
- live smoke 用于真实 provider 可用性。

不要为了指标去设计功能。功能先服务真实使用，再用测试证明没有退化。

## 4. 推荐执行顺序

### P0：同步路线和协作规则

目标：

- 本文成为后续主路线。
- 同步 `AGENTS.md`、`CLAUDE.md`、README 中关于工具范围和真实 provider 的描述。

验收：

- 文档不再把简历或评测作为第一目标。
- 禁止范围不再禁止 `write_file` 和命令执行。
- 明确 `run_command` 使用 argv 和 `shell=False`。
- `AGENTS.md` 删除或修正禁止 `write_file` / 命令执行的旧描述，并说明 Codex 必须审查 `run_command` 安全边界。
- `CLAUDE.md` 删除或修正“严格禁止加入 write_file / shell 工具”的旧描述。
- `README.md` 项目描述从 tiny demo/harness 改成本地 coding agent。

### P1：Minimum Working Agent Core

目标：

- 让 mico 具备真实 coding agent 最小能力。

产物：

- `write_file(path, content)`。
- `run_command(argv, timeout=30)`。
- provider 自动选择优化。
- prompt 前缀更新为 local coding agent。
- 工具单元测试。
- benchmark case：write success/denied、command success/denied。
- live smoke 覆盖 write 和 command。

实施顺序：

1. 先实现 `write_file`，补齐 path、parent directory、overwrite、approval、path escape 测试。
2. 再实现 `run_command(argv, timeout=30)`，补齐 success、stderr、non-zero exit、timeout、invalid argv、approval 测试。
3. 最后优化 provider 自动选择和 prompt 前缀，避免工具能力和 provider 行为混在同一批未验证改动里。

验收：

- `python -m pytest --basetemp .tmp/pytest-basetemp-p1`
- `python -m benchmarks`
- `python -m mico "列出当前目录"`
- `approval=never` 阻断 `write_file` 和 `run_command`。
- `run_command` 使用 `shell=False` 和 argv。
- report 记录 files written、commands run、exit code。

### P2：真实任务闭环

目标：

- mico 能在真实模型下完成一个小型创建/修改/测试任务。

产物：

- `examples/practical-python-task/`。
- 一个 copyable demo command。
- 一个真实 provider smoke task。
- report 增加 command summary 和 verification summary。

验收：

- mico 能创建源码和测试文件。
- mico 能运行测试命令。
- 测试失败时，模型能读取失败输出并再次修改。
- 最终 run artifact 可复盘。

### P6：文档、演示和项目展示

P1-P2 后优先做 P6，而不是继续做复杂编辑、上下文或恢复系统。

产物：

- README：安装、配置、真实使用示例。
- docs/demo-guide.md：3 个可复制场景。
- docs/safety-model.md：工具权限、workspace 沙箱、命令执行边界。
- docs/resume.md：从真实能力自然提炼简历描述。
- 2 分钟录屏或 recorded session：
  - 场景 1：`python -m mico "在当前目录创建 fibonacci 函数和 pytest 测试，运行 pytest 直到通过"`。
  - 场景 2：`python -m mico "修复 examples/buggy-math/add.py 中的加法错误，运行 python verify.py"`。
  - 场景 3：`python -m mico "给 src/utils.py 添加 reverse_string 函数，创建测试，运行 pytest"`。
  - 每个场景展示 `.mico/runs/<run_id>/report.json` 中的 changed files、files written、commands run、exit code 和 verification status。

验收：

- 新用户按 README 可以跑 fake demo。
- 有 API key 时可以跑真实 coding demo。
- demo 能证明 mico 创建、修改、运行测试和修复失败。

## 5. Backlog：只有真实痛点出现后再做

以下能力不是当前主线：

- 编辑能力增强：`replace_range(path, start, end, content)` 或等价行区间替换工具。
- context budget。
- 文件摘要。
- 任务内 structured memory。
- checkpoint/resume。
- workspace fingerprint。
- drift detection。

启动条件：

- P1-P2 已能完成小型真实任务，且 P6 demo 录制已暴露出明确问题。
- 真实 demo 中频繁遇到 `patch_file` 精确匹配失败，并且 `write_file` 小文件整体重写不适合解决。
- 真实使用中反复遇到 prompt 过长、重复读文件或长任务中断问题。
- 能用一个具体 demo 证明这些能力确实解决问题。

每次启动前先问：

```text
pico 是否需要这个能力？如果不需要，mico 当前为什么需要？
```

## 6. 下一步

当前应先完成：

```text
P0：同步路线和协作规则
```

随后进入：

```text
P1：Minimum Working Agent Core
```

P1 是项目能否真正可用的分水岭。没有 `write_file`，mico 无法创建代码或测试；没有 `run_command(argv)`，mico 无法验证真实项目。

## 7. Claude Code 协作要求

- Claude Code 可负责 P1 实现初稿、测试和文档同步。
- Codex 必须审查 `run_command` 的安全边界。
- 如果 Claude Code 实现或建议 `shell=True`，应退回修改为 argv + `shell=False`，除非用户单独批准设计 `run_shell`。
- 如果 Claude Code 调用失败、超时或无产出，按 `AGENTS.md` 询问用户下一步，不直接接手大改。
