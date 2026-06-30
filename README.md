# mico

`mico` 是一个本地 coding agent，用于在指定 workspace 内创建、编辑、运行和验证代码。

## 当前状态

- 已支持工具：`list_files`、`read_file`、`search`、`patch_file`、`write_file`、`run_command(argv)`、`remember`。
- 支持 `--verify-cmd`，可在任务完成后执行最终验证命令。
- 支持离线 fake provider；真实 OpenAI-compatible provider 可通过环境变量或 CLI 参数配置。
- P1 已完成：实现 `write_file` 和 `run_command`。
- 当前阶段（P2）：真实任务闭环，即创建代码、运行验证、失败后修复，并完成端到端任务。

## 路线图

- **P0**：同步文档和协作规则。
- **P1**：最小可用 Agent Core（`write_file`、`run_command`）。
- **P2**：真实任务闭环与端到端验证。
- **P6**：README 打磨、演示指南、录屏演示和安全模型说明。

## 运行（自动选择 provider）

默认不传 `--provider` 时，mico 会自动选择 provider：

- 如果已配置 `MICO_API_KEY`、`MICO_BASE_URL`、`MICO_MODEL`，默认使用 OpenAI-compatible provider，也就是调用真实大模型。
- 如果没有完整模型配置，则回退到 fake provider，便于离线 smoke test。

```bash
python -m mico "list this workspace"
```

可编辑安装后运行：

```bash
pip install -e .
mico "list this workspace"
```

如需强制使用 fake provider：

```bash
python -m mico --provider fake "list this workspace"
```

## 运行（OpenAI-compatible provider）

设置 API key，并指向 OpenAI-compatible endpoint：

```bash
export MICO_API_KEY="sk-..."
python -m mico --provider openai-compatible --base-url http://localhost:8000/v1 --model gpt-4 "list this workspace"
```

也可以使用 `--api-key-env` 指定其他环境变量名，并用 `--model-timeout` 调整 HTTP 超时时间（默认 120 秒）。

如果需要反复做本地 smoke test，可以创建或编辑本地 `.env` 文件：

```env
MICO_API_KEY=sk-...
MICO_BASE_URL=http://localhost:8000/v1
MICO_MODEL=gpt-4
```

当这三个值都存在时，`python -m mico "list this workspace"` 会自动使用 OpenAI-compatible provider。CLI 参数仍然优先生效，`--provider fake` 会强制使用 fake provider。`.env` 已被 git 忽略，不应提交。

## 工具

已支持工具：

- `list_files`：列出目录内容。
- `read_file`：按行范围读取文件。
- `search`：在 workspace 内搜索文本。
- `patch_file`：对已有文件做精确文本替换（需要 `--approval auto`）。
- `write_file`：写入 UTF-8 文件，必要时创建父目录（需要 `--approval auto`）。
- `run_command`：以 argv list 形式运行命令，阻止 shell interpreter（需要 `--approval auto`）。
- `remember`：写入跨 session 的长期记忆（需要 `--approval auto` 或审批通过）。

所有路径都会被限制在 workspace 内。`patch_file` 要求 `old_text` 在目标文件中恰好出现一次。`run_command` 接收非空字符串列表，而不是 shell 命令字符串。

## 示例任务

可以尝试这个 Python 实战任务：

```bash
python -m mico "Create src/fibonacci.py implementing fib(n) with fib(0)=0, fib(1)=1, then run python verify.py to check it passes" --cwd examples/practical-python-task --max-steps 8
```

## Live Smoke（可选，真实模型）

可选 smoke runner 用于验证真实 OpenAI-compatible provider 的端到端行为。它包含只读和可写（coding task）用例。它不是默认测试套件的一部分，需要可用的模型 endpoint。

1. 创建或编辑本地 `.env`，设置 `MICO_API_KEY`、`MICO_BASE_URL`、`MICO_MODEL`。
2. 运行：

```bash
python -m benchmarks.live
```

runner 会创建临时 workspace，执行四个用例（`list_files`、`read_file`、`search`、`create_and_verify_python_task`），并把摘要写入 `benchmarks/results/live-latest.json`。可写用例会在隔离的临时 workspace 中使用 `approval_policy=auto`。结果文件不会记录 prompt、原始模型输出或 API key。

## 评测（上下文、记忆、恢复）

运行 deterministic ablation benchmark，评测上下文压缩、session memory 复用和 checkpoint/resume 行为：

```bash
python -m benchmarks.eval
```

该评测使用 `FakeModelClient` 和 prompt-aware fake model，不需要 API key，也不需要真实模型 endpoint。评测会写入本地结果文件：

```text
benchmarks/results/eval-latest.json
benchmarks/results/eval-latest.md
```

`benchmarks/results/` 已被 git 忽略。Windows 下查看人类可读摘要：

```powershell
Get-Content benchmarks\results\eval-latest.md
```

摘要包含以下指标：

- 平均和最高 prompt 压缩率。
- 当前用户请求保留率。
- memory 复用前后的 follow-up `read_file` 次数。
- checkpoint/resume 状态识别准确率。
- workspace 漂移识别率。
- stale state 安全率。

验证评测测试：

```bash
python -m pytest tests/test_eval_benchmarks.py
```

## 测试

```bash
python -m pytest
```
