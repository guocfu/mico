# Pico 安全与工具执行层分析

> 分析日期：2026-06-22
> 分析范围：pico 工具定义/执行层、workspace 路径安全、approval 机制、patch 文件修改、trace/report 记录、相关测试
> 不涉及：learn-claude-code-main、nanobot-main

---

## 1. 读过的 pico 关键文件

| 文件 | 关注点 |
|---|---|
| `pico/tools.py` | `BASE_TOOL_SPECS` 工具定义（含 `risky` 标记）、`validate_tool` 逐工具校验、`patch_file` 精确替换逻辑 |
| `pico/tool_executor.py` | `ToolExecutor.execute` 五阶段守卫管线（allowlist → 存在性 → 校验 → 重复调用 → approval） |
| `pico/workspace.py` | `clip()`、`IGNORED_PATH_NAMES`、`WorkspaceContext`（git 状态、文档预加载） |
| `pico/security.py` | `looks_sensitive_env_name`、`redact_text`、`redact_artifact` 递归脱敏、`shell_env` 环境过滤 |
| `pico/runtime.py` | `Pico.path()` 路径沙箱（`commonpath`）、`approve()` 审批策略、workspace snapshot diff |
| `pico/agent_loop.py` | trace 事件发射点、tool result metadata 记录、checkpoint 创建 |
| `pico/run_store.py` | `RunStore._write_json_atomic` 原子写入（tempfile+rename）、trace JSONL 追加 |
| `tests/test_safety_invariants.py` | 路径逃逸、符号链接穿越、risky 工具拒绝、shell 环境过滤、delegate 只读、secret redact |
| `tests/test_tools.py` | `ToolContext` 解耦、`build_tool_registry` 构建、delegate 深度限制 |
| `tests/test_security.py` | 敏感环境变量名检测、`redact_artifact` 递归、`shell_env` allowlist |
| `tests/test_allowed_tools.py` | 工具白名单过滤 prompt 和执行 |
| `tests/test_tool_executor.py` | `ToolExecutionResult` 结构、metadata 字段验证 |

---

## 2. pico 安全/工具执行设计摘要

### 2.1 工具定义层（tools.py）

- 每个工具有 `schema`（类型化参数）、`risky`（布尔）、`description` 三个字段
- `risky` 工具：`run_shell`、`write_file`、`patch_file`
- 只读工具：`list_files`、`read_file`、`search`、`delegate`
- `patch_file` 校验最严格：文件必须存在、`old_text` 非空、`new_text` 必须存在、`old_text` 必须恰好出现一次
- 工具通过 `build_tool_registry(context)` 显式注册，非动态发现
- delegate 工具受深度限制，`depth >= max_depth` 时不暴露
- 提供 `TOOL_EXAMPLES` 字典，校验失败时附加示例帮助模型修正

### 2.2 工具执行层（tool_executor.py）

五阶段守卫管线：

1. **白名单检查** — `allowed_tools` 不为 None 时，工具名必须在白名单内
2. **存在性检查** — 工具名必须在 registry 中
3. **参数校验** — 调用 `validate_tool`，检测到路径逃逸时记录 `security_event_type="path_escape"`
4. **重复调用检测** — 连续两次相同 name+args 则拒绝，防止死循环
5. **审批门控** — `risky` 工具需通过 `approve()` 检查

通过所有守卫后，risky 工具执行前捕获 workspace snapshot（SHA-256），执行后 diff，记录 `affected_paths`、`diff_summary`、`workspace_changed`。

返回 `ToolExecutionResult(content, metadata)`，metadata 包含：`tool_status`、`tool_error_code`、`security_event_type`、`risk_level`、`read_only`、`affected_paths`、`workspace_changed`、`diff_summary`、`workspace_fingerprint`。

### 2.3 路径安全（runtime.py）

```python
def path(self, raw_path):
    path = Path(raw_path)
    path = path if path.is_absolute() else self.root / path
    resolved = path.resolve()
    if os.path.commonpath([str(self.root), str(resolved)]) != str(self.root):
        raise ValueError(f"path escapes workspace: {raw_path}")
    return resolved
```

- `.resolve()` 跟随 symlink，能防 symlink 逃逸
- `commonpath` 检查比 `candidate.parents` 更严格（处理根目录边界）
- 测试覆盖：`../` 逃逸、symlink 逃逸

### 2.4 审批策略（runtime.py）

- `auto`：risky 工具自动放行
- `never`：risky 工具全部拒绝
- `ask`：交互式 stdin 确认
- `read_only=True`（delegate 子 agent）覆盖所有策略，一律拒绝 risky 工具

### 2.5 patch_file 机制

- `old_text` 必须在文件中恰好出现一次（validate 和 execute 双重检查）
- 使用 `text.replace(old_text, new_text, 1)` — 字面量精确替换，非 diff 格式
- deterministic、explanable

### 2.6 Secret Redaction（security.py）

- `looks_sensitive_env_name`：启发式检测 `_API_KEY`、`_TOKEN`、`_SECRET`、`_PASSWORD` 后缀
- `redact_artifact`：递归遍历 dict/list/tuple，替换敏感 key 和包含 secret 值的字符串
- 所有 trace 和 report 写入前经过 `redact_artifact` 过滤
- shell 执行环境通过 allowlist 过滤，只保留 `HOME/LANG/PATH/PWD` 等安全变量
- 测试验证 trace 和 report 中无 secret 值泄露

### 2.7 RunStore（run_store.py）

- `_write_json_atomic`：先写 tempfile 再 `replace`，防止半截 JSON
- trace.jsonl 逐条追加，crash-safe
- 测试覆盖 trace 中无 secret 值泄露

---

## 3. 适合迁移到 mico 的设计

### 3.1 patch_file 的 "恰好一次" 校验（已迁移）

mico 已实现相同逻辑：`old_text` 必须在文件中恰好出现一次。这是确定性替换的关键约束。

### 3.2 ToolExecutor 的 ValueError 捕获模式（已迁移）

pico 的 `ToolExecutor` 用 try/except 捕获所有异常，返回结构化 `ToolExecutionResult`。mico 已采用类似模式：`ValueError` 被捕获为 `ToolResult(content="error: ...", ok=False)`。

### 3.3 `new_text` 字段必须存在的校验（已迁移）

pico 的 `validate_tool` 检查 `"new_text" not in args`，mico 已同步实现。

### 3.4 `risky` 标记分类（可迁移，优先级：中）

pico 每个工具有 `risky` 标记，mico 目前用 `WRITE_TOOLS` 集合硬编码。可改为在 `ToolSpec` 中增加 `risky` 字段，让审批逻辑更通用。改动量约 15 行。

### 3.5 重复调用检测（可迁移，优先级：低）

pico 的 `repeated_tool_call` 防止连续相同工具调用。mico 目前无此机制，但 `max_steps=4` 已隐式约束循环。可在 `ToolExecutor` 或 `AgentLoop` 中增加轻量检测。

### 3.6 secret redaction（可迁移，优先级：中）

pico 的 `security.py` 提供完整的 secret 检测和脱敏。mico 目前 trace 中不记录 API key（`OpenAICompatibleModelClient._api_key` 是私有字段），但没有主动脱敏机制。如果未来接入更多 provider，应迁移此设计。

### 3.7 atomic write（可迁移，优先级：低）

pico 的 `_write_json_atomic` 用 tempfile + rename 防止写入中断产生损坏 JSON。mico 的 `RunStore._write_json` 直接 `write_text`，存在 crash 时 state.json 损坏的风险。demo 阶段可接受。

### 3.8 workspace snapshot diff（暂不迁移）

pico 在 risky 工具执行前后做 SHA-256 快照 diff。mico 当前只有 `patch_file` 一个写工具，直接检查返回值即可，暂不需要 snapshot 机制。

---

## 4. 现在不适合迁移的设计

### 4.1 delegate 子 agent

mico 范围明确禁止多 agent。delegate 的深度控制、read_only 隔离等设计与 mico 无关。

### 4.2 run_shell 工具

mico 范围禁止 shell 工具。shell env allowlist 过滤、timeout 约束等设计不需要。

### 4.3 write_file 工具

mico 范围禁止通用写文件工具，只允许 `patch_file`。

### 4.4 checkpoint/resume 机制

pico 有完整的 checkpoint 创建和 session 恢复。mico 当前是单次运行，不需要。

### 4.5 ToolContext 解耦

pico 用 `ToolContext` dataclass 解耦工具函数和 runtime，支持独立测试。mico 工具函数直接接收 `workspace` 对象，耦合度可接受（工具少、无动态注册需求）。

### 4.6 interactive approval（ask 模式）

pico 支持 `--approval ask` 通过 stdin 交互确认。mico 当前是 one-shot CLI，无交互式 REPL，`ask` 模式无意义。

---

## 5. mico 当前实现风险点

### 5.1 路径检查：`candidate.parents` vs `commonpath`（风险：中）

mico 的 `Workspace.path()`:
```python
candidate = (self.root / str(value)).resolve()
if candidate != self.root and self.root not in candidate.parents:
    raise ValueError(f"path escapes workspace: {value}")
```

**风险**：当 `self.root` 是根目录（如 `C:\`）时，`candidate.parents` 永远包含 root，检查失效。pico 用 `os.path.commonpath` 更健壮。

**建议**：改为 `os.path.commonpath` 检查。

### 5.2 无 symlink 逃逸测试（风险：中）

mico 的 `test_workspace_blocks_path_escape` 只测 `../` 逃逸，无 symlink 测试。虽然 `Path.resolve()` 会跟随 symlink，但缺少测试覆盖意味着如果改用不跟随 symlink 的方式做路径检查，不会被发现。

### 5.3 trace 无脱敏（风险：中）

`emit_trace` 直接写入 payload。当前 FakeModelClient 不涉及敏感信息，但接入 OpenAI-compatible provider 后，如果模型返回或工具参数中包含 key，可能泄露到 trace.jsonl。

### 5.4 无重复调用检测（风险：低）

mico 的 agent loop 没有检测连续相同工具调用。如果模型反复返回相同的 `<tool>` 调用，会消耗完 `max_steps` 才停止。`max_steps=4` 已隐式约束。

### 5.5 state.json 非原子写（风险：低）

`RunStore._write_json` 直接 `path.write_text()`。如果写入过程中进程被 kill，可能产生半截 JSON。demo 阶段可接受。

### 5.6 trace 中记录完整 args（风险：低）

agent loop 在 `tool_executed` 事件中记录完整 `args`。对于 `patch_file`，`old_text` 和 `new_text` 都会出现在 trace.jsonl 中。虽然不是 secret，但大块文本会使 trace 膨胀。建议对 args 和 result 应用 `clip()`。

### 5.7 approval 逻辑硬编码在 ToolExecutor（风险：低）

`ToolExecutor.execute()` 直接检查 `name in WRITE_TOOLS and approval_policy == "never"`。如果未来增加更多写工具，需要手动维护 `WRITE_TOOLS` 集合。pico 通过 `risky` 标记让每个工具自描述。

---

## 6. 下一步最小改造建议

按优先级排序，每项都是独立的小改动：

### P0：修复路径检查 + 补 symlink 测试（改动量：~15 行）

```python
# workspace.py — 用 commonpath 替代 parents 检查
import os

def path(self, value):
    candidate = (self.root / str(value)).resolve()
    if os.path.commonpath([str(self.root), str(candidate)]) != str(self.root):
        raise ValueError(f"path escapes workspace: {value}")
    return candidate
```

补 symlink 逃逸测试：
```python
def test_symlink_path_escape(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(outside)
    workspace = Workspace.build(tmp_path)
    with pytest.raises(ValueError, match="escapes workspace"):
        workspace.path("link.txt")
```

### P1：ToolSpec 增加 risky 字段（改动量：~15 行）

- `ToolSpec` 增加 `risky: bool = False`
- `patch_file` 的 spec 设 `risky=True`
- `ToolExecutor.execute` 用 `TOOL_SPECS[name].risky` 替代 `WRITE_TOOLS` 硬编码集合

### P2：增加简单 trace 脱敏（改动量：~20 行）

新建 `security.py`，实现简化版 `redact_artifact`，过滤 `API_KEY`/`TOKEN`/`SECRET`/`PASSWORD` 后缀的环境变量名和对应值。`emit_trace` 调用前先脱敏。

### P3：trace 输出截断（改动量：~5 行）

在 agent loop 的 `tool_executed` trace 中对 args 和 result 应用 `clip()`。

### P4：原子写 state.json（改动量：~15 行）

参考 pico 的 `_write_json_atomic`：先写 tempfile 再 `Path.replace()`。

---

## 附录：pico 与 mico 工具安全设计对比

| 维度 | pico | mico 当前 | 差距 |
|---|---|---|---|
| 工具数量 | 6+1（含 delegate） | 4 | 符合范围限制 |
| risky 标记 | spec 内置 `risky` 字段 | 硬编码 `WRITE_TOOLS` 集合 | 可改进 |
| 路径沙箱 | `.resolve()` + `commonpath` | `.resolve()` + `parents` | 可改进，缺 symlink 测试 |
| 审批策略 | auto/never/ask + read_only | auto/never | ask 模式暂不需要 |
| 执行守卫 | 5 阶段管线 | 2 阶段（approval + ValueError） | 可渐进增强 |
| trace 脱敏 | `redact_artifact` 全量脱敏 | 无 | 需补充 |
| 工具输出截断 | 4000 字符 | trace 层面 clip | 暂不需要 |
| 重复调用检测 | 有 | 无 | 暂不需要 |
| workspace 快照 diff | SHA-256 前后对比 | 无 | 暂不需要 |
| 原子写入 | tempfile+rename | 直接 write_text | 暂不需要 |
