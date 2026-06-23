# Mico 改进框架：基于 pico 与 claude-code 的取舍重构

> 日期：2026-06-23
> 输入来源：`claude-code/analysis/mico-borrowing-analysis.md`、`claude-code/CLAUDE.md`、`pico/docs/architecture/agent-harness-v1-overview.md`、`pico/docs/review-pack/README.md`、`mico/analysis/pico-author-notes.md`、`mico/analysis/pico-security-and-tools.md`、`mico` 当前源码和测试。

## 1. 总体定位

`mico` 不应定位为一个功能堆叠型 coding agent，而应定位为一个小而完整的本地 **Agent Harness**。

核心目标不是马上复刻 Claude Code，而是把以下链路做稳：

1. 用户请求进入 CLI。
2. Harness 构造带工具目录和运行策略的 prompt。
3. 模型返回结构化动作。
4. 工具调用经过统一安全边界。
5. 结果回写历史与状态。
6. 运行工件落盘，支持复盘、测试和后续评测。

这个定位来自 pico 的三层架构：控制面、状态面、证据面；也吸收 claude-code 的主循环、工具协议、权限流水线和错误恢复思想。

## 2. 当前基线判断

`mico` 当前已经具备一个可运行的 v0.1 Harness 闭环：

| 能力 | 当前状态 | 依据 |
|---|---|---|
| Agent loop | 已有，支持 tool/final/retry 分流、step limit、retry limit | `mico/mico/agent_loop.py` |
| 模型协议 | 已有 XML block 协议：`<tool>` / `<final>` | `mico/mico/runtime.py` |
| 工具目录 | 已有 `ToolSpec`，包含 `description/schema/risky` | `mico/mico/tools.py` |
| 工具审批 | 已有 `approval=auto/never`，risky 工具可被拒绝 | `mico/mico/tool_executor.py` |
| 路径沙箱 | 已改为 `resolve()` + `commonpath` | `mico/mico/workspace.py` |
| 精确补丁 | `patch_file` 要求 `old_text` 恰好一次 | `mico/mico/tools.py` |
| 重复调用检测 | 已有连续相同 name+args 拦截 | `mico/mico/tool_executor.py` |
| trace 脱敏 | 已有 `redact_artifact` | `mico/mico/security.py` |
| trace 截断 | `tool_executed` 对 args/result 截断 | `mico/mico/agent_loop.py` |
| 运行工件 | 已有 `state.json`、`trace.jsonl`、`report.json` | `mico/mico/state.py` |

因此下一步不是再补零散安全小点，而是把 `mico` 的改进路线重构为三个阶段：v1 稳固、v1.5 架构化、v2 长链路能力。

### 2.1 框架与当前代码的校准

本框架的判断已逐条对照 `mico/mico` 源码核实。下面记录**与代码不完全一致的措辞**和**原框架遗漏的真实缺口**，避免后续按过时假设施工。

#### 措辞校准

- **工具结果预算**：trace 其实已经截断（`agent_loop.py:59` 用 `clip_artifact(..., 500)` 和 `clip(..., 500)`）。真正未截断的是写入 `history` 的 `result.content`（`agent_loop.py:46-55`）。v1.5.4 的目标应明确为「截断进入 history 的结果」，而不是泛泛地说「工具结果会完整进入 history」。
- **report 字段**：`build_report()`（`runtime.py:81-97`）已产出 `task_state`、`history_items`、`workspace_root`、`approval_policy`、`available_tools`、`restricted_tools`、`tool_call_summary`。v1.2 实际只差 `failure_category` 和 `artifacts_version` 两个字段，以及把 schema 文档化。
- **失败标识已有三套**：当前代码里已存在三组互不协调的状态/错误标识，详见 v1.3。后续工作应是**统一**它们，而不是新增第四套枚举。

#### 原框架遗漏的真实缺口

| 编号 | 缺口 | 证据 | 风险 | 建议归属 |
|---|---|---|---|---|
| G1 | 模型调用未捕获异常 | `agent_loop.py:34` 的 `model_client.complete()` 未包 try/except | 真实 provider 抛 `RuntimeError`（`providers.py:69/74`）会直接中断 run：`state.json` 已写但缺 `report.json` 与 `run_finished`，**破坏 §3.4「运行工件必须落盘」不变量** | 提到 v1（见 v1.6） |
| G2 | 步数/重试上限语义隐式 | `agent_loop.py:27` 的 `max_attempts = max_steps + 3`；`attempts` 与 `tool_steps` 分别计数 | 两个上限关系不透明，stop_reason 难解释 | v1.3 一并文档化 |
| G3 | `search` 调用子进程 | `tools.py:122-130` 通过 `subprocess.run(["rg", ...])` 执行 | 本身安全（argv 非 `shell=True`，pattern 作为参数、path 已沙箱），但 §3.3「信任边界」未声明，审查时易误判违反「禁止 shell」 | §3.3 增加说明 |
| G4 | 同实例多次 `ask()` 不重置 history | `runtime.py:19-21` 的 `ask()` 只调 `reset_run_state()`（仅清工具签名），`self.history` 不清空 | 当前 CLI 一次性调用不受影响；一旦复用实例或进入多轮就会串台 | 记录为已知约束，进入多轮前处理 |
| G5 | 重复调用签名记录时机 | `tool_executor.py:70-82`：签名在 approval 检查**之前**写入；validation_error 路径不更新签名 | 被 approval 拒绝的调用仍占用签名位；非法调用可被无限重试 | v1.5.3 守卫流水线一并理顺 |

## 3. 设计原则

### 3.1 以 pico 为主骨架

pico 对 `mico` 最有价值的是 Harness 思维：

- 控制面：CLI、runtime、agent loop、model provider、tool executor。
- 状态面：task state、history、run store、memory。
- 证据面：trace、report、benchmark、metrics。

`mico` 应优先沿这个结构扩展，而不是先追求 Claude Code 的完整产品形态。

### 3.2 以 claude-code 补关键工程机制

claude-code 对 `mico` 最有价值的是成熟 coding agent 的关键机制：

- 主循环状态机。
- Tool 接口的能力标记：read-only、risky/destructive、concurrency-safe。
- 只读并发、写入串行的工具调度。
- 多步权限检查流水线。
- prompt-too-long、max-output、malformed-output 的恢复策略。
- 系统提示词静态/动态分离。

但这些机制要被压缩成适合 Python demo 的小实现，不能照搬 Ink UI、多 provider、remote control、computer use、子代理 worktree 等重量级设计。

### 3.3 工具层是信任边界

模型不能直接接触文件系统。所有副作用必须经过：

1. 工具存在性检查。
2. 参数校验。
3. 路径沙箱。
4. 重复调用检测。
5. 风险分类。
6. 审批策略。
7. 结构化结果和 trace 记录。

这一点来自 pico 的五阶段工具守卫，也对应 claude-code 的多步权限流水线。

注意：`search` 当前会在 `rg` 存在时调用 `subprocess.run(["rg", ...])`（`tools.py:122-130`）。这**不是** AGENTS 禁止的「shell 工具」：它用 argv 列表而非 `shell=True`，pattern 作为独立参数传入无 shell 注入面，path 已过沙箱，`cwd` 固定为 workspace root。框架在此显式声明这一点，避免审查时误判为违反「禁止 shell」。若后续要进一步收紧，可加 `--max-filesize`、超时和 `rg` 退出码处理，但不改变其只读定位。

### 3.4 运行工件必须服务评测

`trace.jsonl`、`state.json`、`report.json` 不能只是日志。它们应该逐步变成后续 benchmark、失败归因、回归对比的证据基础。

## 4. 目标架构

推荐把 `mico` 的内部结构稳定为六个边界：

| 边界 | 职责 | 当前模块 | 下一步方向 |
|---|---|---|---|
| CLI 边界 | 参数解析、provider 选择、workspace 初始化 | `cli.py` | 保持轻量，补 help 文档即可 |
| Runtime 边界 | 组装 agent 依赖、prompt、parse、report | `runtime.py` | 拆出 prompt builder 和 parser |
| Loop 边界 | 控制循环、终止条件、错误恢复 | `agent_loop.py` | 引入明确 stop reason 和恢复事件 |
| Tool 边界 | 工具定义、校验、执行、审批 | `tools.py`、`tool_executor.py` | 扩展 read_only/concurrency_safe 元数据 |
| State 边界 | task state、run store、trace、report | `state.py` | 原子写入、report schema 稳定化 |
| Security 边界 | 路径沙箱、脱敏、危险动作判断 | `workspace.py`、`security.py` | 统一 security metadata |

## 5. 分阶段改进路线

### 5.1 v1：稳固最小闭环

目标：保持 demo 简洁，但让它具备可审计、可解释、可回归的工程质量。

#### v1.1 原子写入运行工件

- 设计来源：pico `RunStore._write_json_atomic`。
- 当前问题：`mico/mico/state.py` 直接 `write_text()`，进程中断可能留下半截 JSON。
- 建议实现：`tempfile` 写临时文件，然后 `Path.replace()`。
- 影响范围：`RunStore._write_json()`。
- 测试：增加模拟写入成功路径的单测；不强行做 kill 测试。
- 优先级：P0。

#### v1.2 稳定 report schema

- 设计来源：pico 的证据面和 claude-code 的 tool metadata。
- 当前问题：`report.json` 已有摘要，但 schema 尚未文档化。
- 建议字段：`task_state`、`history_items`、`workspace_root`、`approval_policy`、`available_tools`、`restricted_tools`、`tool_call_summary`、`failure_category`、`artifacts_version`。
- 影响范围：`Mico.build_report()`。
- 测试：断言字段稳定存在。
- 优先级：P0。

#### v1.3 统一失败分类（而非新增枚举）

- 设计来源：pico benchmark 失败归因、claude-code 错误恢复分支。
- 当前问题：代码里已有**三套互不协调**的标识，再加字段只会让归因更乱：
  1. `TaskState.stop_reason`（`state.py`）：`final` / `retry_limit` / `step_limit`。
  2. 工具 `metadata.error_kind`（`tool_executor.py`）：`ok` / `unknown_tool` / `validation_error` / `repeated_call` / `approval_denied`。
  3. parser 返回的自由文本 reason（`runtime.py:33-48`），目前全部塌缩成 `kind="retry"`，类型信息丢失。
- 建议：定义**单一** `failure_category` 派生规则，由 `build_report()` 从上面三个来源归并，不在 `TaskState` 上再加一个平行枚举。取值：
  - `success`
  - `step_limit`
  - `malformed_model_output`（来自 retry_limit + parser error_kind）
  - `tool_validation_error` / `unknown_tool` / `approval_denied`（来自最近一次失败工具的 `error_kind`）
  - `model_error`（来自 v1.6 的 provider 异常）
- **派生归属决策**（原 §8 第 4 点）：推荐由 `build_report()` 从「最近一次终止原因 + 最近一次失败工具」推导，`TaskState` 只维护 `stop_reason` 这一既有字段，不新增。
- 同时文档化 G2：`max_attempts = max_steps + 3`（`agent_loop.py:27`），`attempts`（含 malformed 重试）与 `tool_steps`（仅成功工具步）分别计数；`retry_limit` 由 attempts 触顶引发，`step_limit` 由 tool_steps 触顶引发。report 应同时输出这两个计数，让 stop_reason 可解释。
- 影响范围：`runtime.build_report()`，必要时 parser 返回 `error_kind`（见 v1.5.2）。
- 优先级：P0。

#### v1.6 模型调用异常兜底（G1，新增 P0）

- 设计来源：claude-code provider error 分支；本框架 §3.4 运行工件落盘不变量。
- 当前问题：`agent_loop.py:34` 的 `model_client.complete()` 没有任何异常处理。`OpenAICompatibleModelClient` 在网络失败或响应格式异常时抛 `RuntimeError`（`providers.py:69`、`providers.py:74`），会让整个 run 崩在循环中途——`state.json` 停在 `running`，没有 `report.json`，也没有 `run_finished` trace。这违反 §3.4。
- 建议实现：用 try/except 包住 `complete()`；捕获后将 `TaskState` 终止为 `stop_reason="model_error"`，写 `run_finished` trace 和 report，再向上返回错误信息。不做多模型 fallback。
- 影响范围：`AgentLoop.run()`，`TaskState` 增加 `stop_model_error()`，`failure_category` 增加 `model_error`。
- 测试：用一个 `complete()` 抛异常的 fake client，断言 run_dir 下三件工件齐全且 `failure_category == "model_error"`。
- 优先级：P0（先于任何真实 provider 接入）。

#### v1.4 工具元数据补全

- 设计来源：claude-code Tool 接口、pico ToolSpec。
- 当前已有：`risky`。
- 建议 `ToolSpec` 增加：`read_only: bool`、`concurrency_safe: bool`、`max_result_chars: int`。
- 当前阶段不需要并发执行，但先让工具自描述，便于 v1.5 扩展。
- 优先级：P1。

### 5.2 v1.5：架构化 Harness

目标：不增加重功能，先把边界拆清楚，让后续接入上下文治理、评测和真实 provider 时不会改成一团。

#### v1.5.1 PromptBuilder

- 设计来源：pico 分段 prompt；claude-code 静态/动态系统提示词分离。
- 当前问题：`Mico.build_prompt()` 混合了系统规则、工具目录、workspace、history、用户请求。
- 建议新增 `prompt.py`，分出 `static_prefix`、`tool_catalog`、`runtime_policy`、`workspace_context`、`recent_history`、`current_request`、`prompt_metadata`。
- v1.5 只做结构化，不做复杂预算裁剪。
- 优先级：P0。

#### v1.5.2 ModelOutputParser

- 设计来源：claude-code 将模型输出解析为 tool/final/retry 的稳定边界。
- 当前问题：`Mico.parse()` 是静态方法，后续错误分类和 schema 校验会膨胀。
- 建议新增 `parser.py`，返回 `ParsedModelOutput(kind, payload, error_kind=None)`。
- 记录 malformed XML、malformed JSON、empty final、unknown block，并让 `error_kind` 直接喂给 v1.3 的统一 `failure_category`（避免 parser 信息塌缩成无类型的 `retry`）。
- 当前 `Mico.parse()`（`runtime.py:33-48`）已能区分这四类，只是把它们都返回成 `kind="retry"` + 文本；迁移时保留区分即可，不改判定逻辑。
- 优先级：P1。

#### v1.5.3 ToolExecutor 形成完整守卫流水线

- 设计来源：pico 五阶段守卫；claude-code deny/ask/tool-specific/safety/allow。
- 当前已有：存在性、校验、重复调用、approval。
- 建议整理为显式步骤：normalize args、lookup spec、validate input、detect repeated call、check approval、execute、normalize result metadata。
- **顺便修正 G5（签名时机）**：当前 `tool_executor.py:70-82` 在 approval 检查**之前**就写 `_last_tool_signature`，且 validation_error 分支根本不写签名。理顺为：仅在「校验通过且 approval 通过、即将真正执行」时才记录签名，使「被拒绝的调用不占签名位、非法调用不会绕过重复检测」。
- 不增加交互式 ask，不增加 shell。
- 优先级：P1。

#### v1.5.4 轻量工具结果预算

- 设计来源：claude-code `maxResultSizeChars`、pico `clip()`。
- 当前问题：trace **已**截断（`agent_loop.py:59` 用 `clip_artifact`/`clip` 到 500 字符），但写入 `history` 的 `result.content` 是完整文本（`agent_loop.py:46-55`）。长文件读取会污染后续 prompt 的 `Recent history` 段。
- 建议：工具结果进入 `history` 前应用工具级 `max_result_chars`（来自 v1.4 的 `ToolSpec` 元数据）；如需完整结果，后续再写 artifact 文件并在 history 里留指针。
- 优先级：P1。

#### v1.5.5 最小 benchmark

- 设计来源：pico review pack 和 benchmark 方法论。
- 建议新增 `benchmarks/`，包含 `tasks.json`、fixture workspace、deterministic fake model scripts、verifier 函数、metrics 汇总。
- 先覆盖 6 类任务：list/read/search 成功、patch 成功、patch 被 approval 拒绝、path escape 被拒绝、malformed output retry 后成功、**model_error 异常兜底工件齐全**。
- 优先级：P0。

### 5.3 v2：长链路能力

目标：当 `mico` 的最小 Harness 足够稳定后，再引入长上下文、记忆、恢复能力。

#### v2.1 分层上下文管理

- 设计来源：pico prefix/memory/relevant_memory/history/current_request；claude-code auto compact。
- 建议分段：stable prefix、tool catalog、workspace summary、memory、recent history、current request。
- 裁剪顺序：memory、history、workspace summary、stable prefix；current request 永不裁剪。
- 当前阶段暂不实现，等真实 provider 和多轮任务稳定后再做。

#### v2.2 工作记忆

- 设计来源：pico LayeredMemory，claude-code memory 类型。
- 先做会话内工作记忆，不做跨项目知识库：`task_summary`、`recent_files`、`file_summaries`、`episodic_notes`。
- 目标是减少重复读文件，不是做复杂知识图谱。

#### v2.3 错误恢复策略

- 设计来源：claude-code max-output 恢复、prompt-too-long compact、model fallback。
- 注意：provider 异常的**基础兜底已提前到 v1.6**（崩溃安全 + `model_error`）。v2.3 在此之上做的是**主动恢复**：malformed 输出最多重试 N 次，prompt-too-long 时先截断 history 再重试。
- 不做多模型自动 fallback，避免范围膨胀。

#### v2.4 checkpoint/resume

- 设计来源：pico checkpoint/resume。
- 触发条件：真实长任务、用户需要中断后恢复、上下文治理和工作记忆已经稳定。
- 当前 demo 阶段暂缓。

## 6. 暂不纳入 mico 的能力

| 能力 | 暂缓原因 |
|---|---|
| Ink/React TUI | 产品形态过重，mico 当前是 CLI demo |
| Shell 工具 | 安全边界显著扩大，AGENTS 明确禁止 |
| write_file | 通用覆盖写风险高，当前只保留 patch_file |
| 多 agent / delegate | 当前范围禁止多 agent |
| worktree 隔离 | 只有多 agent 并发时才有收益 |
| Remote Control / Bridge | 本地 demo 不需要远程控制面 |
| Computer Use / Chrome Use | 和 coding harness 主线无关 |
| AI 权限分类器 | 额外模型调用和误判风险，不适合早期 |
| 多 provider 完整适配 | 先稳定 openai-compatible 一个扩展点 |
| 复杂自动压缩 | 需真实长上下文任务验证后再做 |

## 7. 推荐实施顺序

### 第一批：1-2 个小 PR

1. `RunStore` 原子写 JSON（v1.1）。
2. `report.json` schema 固化、`failure_category` 派生（v1.2 + v1.3）。
3. `ToolSpec` 增加 `read_only/concurrency_safe/max_result_chars`（v1.4）。
4. **模型调用异常兜底（v1.6）**：`AgentLoop` 包 try/except，`TaskState.stop_model_error()`，写 report + trace。

目标：v1 工件落盘不变量稳固，工具元数据为后续铺路，真实 provider 接入前安全兜底到位。

### 第二批：1 个中等 PR

1. 新增 `prompt.py`，迁移 `build_prompt()`。
2. 输出 `prompt_metadata` 到 trace/report。
3. 保持 prompt 内容基本不变，避免行为大漂移。

目标：把上下文治理入口建起来。

### 第三批：1 个中等 PR

1. 新增 `parser.py`。
2. 结构化 malformed output 错误。
3. report 汇总 parser/tool/model 三类失败。

目标：让失败归因从字符串走向结构化。

### 第四批：1 个中等 PR

1. 新增最小 benchmark。
2. 复用 FakeModelClient 做确定性任务。
3. 输出 metrics JSON/Markdown。

目标：从“跑测试”升级到“评测 Harness 行为”。

## 8. 需要 Codex 审查的关键决策

以下几点框架已给出建议，但需要 Codex 确认：

1. `ToolSpec` 是否使用 Python dataclass 继续演进，还是切换到更严格的 schema 对象（当前建议：dataclass，理由是改动最小，等 v1.5 parser 边界稳定后再评估）。
2. `prompt_metadata` 的字段边界（v1.5.1），避免记录过多敏感或无用内容。重点确认哪些字段需要过一遍 `redact_artifact`。
3. benchmark 是否放在 `mico/benchmarks/`，以及是否纳入默认 pytest run（v1.5.5，当前建议：放 `benchmarks/`，不纳入默认，独立 `python -m benchmarks` 触发）。
4. 何时允许引入上下文预算裁剪和工作记忆（v2.1/v2.2 触发条件，需真实 provider + 多轮任务先验证）。

以下几点框架已通过代码核实后给出明确建议，**无需 Codex 再次决策，除非另有异议**：

- `failure_category` 由 `build_report()` 从现有三套标识派生，不在 `TaskState` 新增平行枚举（v1.3）。
- provider 异常兜底提前到 v1.6，不推迟到 v2.3（G1）。
- 签名记录时机改为「校验 + approval 均通过后」（G5，v1.5.3 一并修）。
- history 截断：进入 `history` 前按 `max_result_chars` 截断，trace 侧已有截断无需改动（v1.5.4）。

## 9. 一句话结论

`mico` 下一阶段应以 pico 的 Harness 三层架构为主线，以 claude-code 的成熟机制做局部加固：先把运行工件、工具元数据、prompt/parser 边界和最小 benchmark 做稳，再考虑长上下文、记忆和恢复；不要提前引入 TUI、shell、多 agent、远程控制等重功能。
