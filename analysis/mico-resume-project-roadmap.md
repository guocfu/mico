# Mico 简历项目化架构路线

> 日期：2026-06-23
> 状态：后续主执行路线
> 说明：`analysis/mico-improvement-framework.md` 保留为历史技术分析；后续功能迭代、Claude Code 实现任务和 Codex 审查，优先以本文为准。

## 1. 项目定位

`mico` 不再定位为简单的 tiny local coding agent demo，而应定位为：

**面向本地代码修改任务的 Verified Coding Agent Harness。**

核心目标不是堆叠工具数量，而是建立一条可演示、可测试、可复盘、可写进简历的 agent 工程链路：

用户任务 -> 分层 Prompt -> 模型决策 -> 工具治理 -> 文件修改 -> 验证执行 -> 运行工件 -> Benchmark 指标 -> 简历材料

最终项目应能支撑以下一级简历贡献点：

1. Agent Harness 架构设计。
2. 工具安全与运行治理。
3. 验证型 Coding Agent 闭环。
4. 上下文治理。
5. 结构化记忆系统。
6. Checkpoint / Resume。
7. 评测与审计闭环。

所有简历数字必须来自 benchmark、demo runner 或运行工件汇总，不在文档中手写编造。

旧 `mico-improvement-framework.md` 中经过代码校准的真实约束仍然有效，尤其是：

- `search` 当前通过固定 argv 调用 `rg` 子进程；这是白名单只读实现，不等同于开放 shell 工具。
- 当前 CLI 是一次性运行模式；若后续复用同一个 `Mico` 实例做多轮任务，必须先处理 history 串台问题。
- 重复调用、模型异常、parser malformed 输出等治理点应继续通过 report 和 benchmark 指标化。

## 2. 目标简历描述

**Mico：本地代码智能体 Harness**

核心技术：Python、Agent Harness、Tool Calling、Context Management、Structured Memory、Checkpoint / Resume、Tool Governance、Run Trace、Benchmark

项目描述：

面向本地代码修改任务开发轻量级 coding agent harness，围绕模型接入、工具调用、上下文预算、结构化记忆、任务恢复、工具安全治理、验证执行、运行审计和评测闭环做系统化设计，重点解决多步代码任务中 prompt 膨胀、重复读文件、工具副作用不可控、修改不可验证、状态丢失和结果难复盘的问题。

## 3. 总体架构

推荐把 `mico` 稳定为六层架构，后续实现按层推进，而不是围绕零散文件补功能。

### 3.1 Interface Layer

负责用户入口和运行配置。

当前核心模块：

- `mico/cli.py`

后续可选模块：

- `mico/commands.py`

职责：

- 解析 prompt、workspace、provider、approval、max steps。
- 后续支持 `--verify-cmd`、`--verify-timeout`、`--resume`、benchmark group 等参数。
- 保持 CLI 是编排入口，不把验证命令暴露给模型作为工具。

简历价值：

- 体现本地 agent 可用性和端到端运行能力。

### 3.2 Harness Runtime Layer

负责 agent 的总装、主循环和生命周期。

核心模块：

- `mico/runtime.py`
- `mico/agent_loop.py`
- `mico/parser.py`
- `mico/providers.py`

职责：

- 组装 model client、workspace、tool executor、prompt builder、run store。
- 控制主循环：model request、parse output、execute tool、update history/state、finish or stop。
- 标准化终止和失败归因：success、step limit、malformed model output、model error、tool error。
- 保证 `state.json`、`trace.jsonl`、`report.json` 在成功和失败路径上都能落盘。

简历价值：

- 对应「Agent Harness 架构设计」。

### 3.3 Tool Governance Layer

工具安全与运行治理是一级核心能力，不是附属安全补丁。

核心模块：

- `mico/tools.py`
- `mico/tool_executor.py`
- `mico/workspace.py`
- `mico/security.py`

职责：

- 用 `ToolSpec` 描述工具能力：read-only、requires approval、concurrency safe、max result chars。
- 统一工具调用流水线：工具存在性检查、参数校验、workspace 沙箱、approval policy、repeated call guard、执行结果标准化、trace/report 脱敏。
- 明确区分只读工具和修改型工具。
- 在 report 中沉淀 `tool_call_summary`、`failure_category`、`changed_files`、`patches_applied`；其中 `changed_files` 和 `patches_applied` 在 P1 新增，不等同于当前已有能力。

简历价值：

- 对应「工具安全与运行治理」。
- 当前已有基础，应优先转化为 benchmark 指标。

### 3.4 Context & Memory Layer

这层负责让项目具备面试深挖点。

核心模块：

- `mico/prompt.py`
- 后续新增 `mico/memory.py`
- 后续可新增 `mico/context_budget.py`

职责：

- Prompt 分层：stable prefix、tool catalog、runtime policy、workspace summary、structured memory、recent history、current request。
- 上下文预算控制：current request 不裁剪，优先裁 history，再裁 memory，再裁 workspace summary。
- 结构化记忆：`task_summary`、`recent_files`、`file_summaries`、`episodic_notes`。

简历价值：

- 对应「上下文治理」和「结构化记忆系统」。
- 这两项必须通过 benchmark 证明收益，而不是只声明功能存在。

### 3.5 Verification & Recovery Layer

负责把 agent 从「会改文件」升级成「能验证、能恢复」。

后续模块：

- `mico/verification.py`
- `mico/checkpoint.py`

职责：

- `verification.py`：执行用户显式传入的 `--verify-cmd`，生成 `verification.json`，记录 exit code、duration、stdout/stderr tail、timeout。
- `checkpoint.py`：保存 task state、history summary、memory、changed files、workspace fingerprint，支持从 run id resume，并检测 workspace drift。

验证命令属于 CLI 编排能力，不属于模型工具能力。实现时必须满足：

- 不使用 `shell=True`。
- 用 argv 列表执行命令。
- 工作目录固定为 workspace root。
- 设置超时并在超时时终止进程。
- stdout/stderr 只写截断后的 tail，不进入 prompt。

简历价值：

- 对应「验证型 Coding Agent 闭环」和「Checkpoint / Resume」。

### 3.6 Evidence & Benchmark Layer

这是简历数字的来源，优先级要前置。

核心模块：

- `mico/state.py`
- `benchmarks/runner.py`
- 后续新增 `benchmarks/metrics.py`

职责：

- 运行工件：`state.json`、`trace.jsonl`、`report.json`、后续 `verification.json`、`checkpoint.json`。
- Benchmark 分组：harness regression、tool governance、verification、context、memory、resume。
- 指标输出：pass rate、verifier pass rate、artifact completeness、failure attribution coverage、prompt compression ratio、repeated file reads、resume success rate、workspace drift detection rate。
- 区分两类评测：
  - **Harness regression**：使用 `FakeModelClient`，验证 harness、工具治理、工件落盘和错误归因是否稳定。
  - **Quality experiment**：使用真实 OpenAI-compatible provider，产出简历可用的真实模型表现数据，例如 verifier pass rate、重复读文件减少、prompt 压缩收益和 resume 成功率。

简历价值：

- 对应「评测与审计闭环」。
- 所有简历数字都应从这里生成；简历中应明确区分 deterministic regression 数字和 real model experiment 数字。

## 4. 核心贡献点与指标口径

### 4.1 Agent Harness 架构设计

目标：

- 统一 CLI、模型 provider、agent loop、工具执行、状态管理和运行工件。
- 支持 fake provider 和 OpenAI-compatible provider。
- 形成可复盘的运行链路。

候选指标：

- 运行工件完整率。
- 成功/失败路径 report 生成率。
- harness regression pass rate。

### 4.2 工具安全与运行治理

目标：

- 把模型所有文件系统动作收敛到工具边界内。
- 对 path escape、approval denied、unknown tool、validation error、repeated call、model error、malformed output 做稳定归因。

候选指标：

- tool guard pass rate。
- failure attribution coverage。
- artifact completeness。

### 4.3 验证型 Coding Agent 闭环

目标：

- 让 agent 具备「读项目 -> 改代码 -> 运行用户指定验证 -> 生成证据」的可展示闭环。
- 验证命令由 CLI 显式传入，不作为模型工具开放。

候选指标：

- verifier pass rate。
- changed files 记录准确率。
- patches applied 记录准确率。

### 4.4 上下文治理

目标：

- 在 prompt 分层基础上做预算控制，减少长链路任务 prompt 膨胀。
- 保证 current request 不被裁剪。
- 这里的上下文治理是显式分层裁剪，有固定优先级和可测指标；不做无策略的自动压缩或复杂摘要系统。

候选指标：

- 平均 prompt 长度。
- prompt compression ratio。
- 预算内完成率。

### 4.5 结构化记忆系统

目标：

- 用会话内 structured memory 减少 follow-up 任务中重复读文件。
- 暂不做长期知识库。

候选指标：

- repeated file reads。
- follow-up 任务工具调用数。
- memory hit rate。

### 4.6 Checkpoint / Resume

目标：

- 支持从 run id 恢复任务状态。
- 识别 workspace drift，避免基于过期状态继续执行。

候选指标：

- resume success rate。
- workspace drift detection rate。
- checkpoint artifact completeness。

### 4.7 评测与审计闭环

目标：

- benchmark 不只验证能跑，还要生产简历指标。
- README、`docs/resume.md` 和 `docs/demo-guide.md` 引用真实 summary。

候选指标：

- benchmark group pass rate。
- metrics summary 生成率。
- run artifact 可复盘率。

## 5. 目标项目结构

```text
mico/
  mico/
    cli.py
    runtime.py
    agent_loop.py
    prompt.py
    parser.py
    providers.py
    tools.py
    tool_executor.py
    workspace.py
    security.py
    state.py
    verification.py        # P2 新增
    memory.py              # P4 新增
    checkpoint.py          # P5 新增
  benchmarks/
    tasks.json
    verify_tasks.json      # P2 新增
    context_tasks.json     # P3 新增
    memory_tasks.json      # P4 新增
    resume_tasks.json      # P5 新增
    runner.py
    metrics.py             # P1 新增
    results/
  examples/
    tiny-python-bug/       # P2 新增
    multi-file-edit/       # 后续按需新增
    follow-up-memory/      # P4 新增
  docs/
    resume.md              # P6 新增
    demo-guide.md          # P6 新增
  analysis/
    mico-resume-project-roadmap.md
    mico-improvement-framework.md
```

## 6. 推荐执行顺序

### P0：建立新路线文档

产物：

- `analysis/mico-resume-project-roadmap.md`。
- 更新 `AGENTS.md` 和 `CLAUDE.md`，让后续上下文恢复优先读取新路线文档。

验收：

- 新文档明确旧 framework 只作历史技术分析。
- 新文档包含七个一级简历贡献点。
- 后续执行顺序以本文为准。

### P1：Benchmark 指标生产线与工具治理指标化

先做这个，因为后续所有简历数字都依赖它；同时工具治理已有大量基础能力，适合在同一个 PR 中完成指标化，避免 P1 结束后 metrics 缺少治理类数据。

产物：

- `benchmarks/metrics.py`。
- benchmark JSON + Markdown summary。
- benchmark group 概念。
- tool governance benchmark group。
- report 增加 `changed_files`、`patches_applied`。
- report 或 metrics 增加 `parser_retry_count`。
- `prompt_metadata` 明确保留 `prompt_chars`，为后续上下文治理提供 baseline。

初始指标：

- total / passed / failed。
- pass rate。
- artifact completeness。
- failure attribution coverage。
- tool guard pass rate。
- parser retry count。

具体子任务：

- 新增 `benchmarks/metrics.py`，实现 `compute_metrics(result) -> dict`。
- 为 benchmark 结果增加 Markdown summary 输出。
- 给 benchmark task 增加 `group` 字段，默认兼容旧任务。
- 支持按 group 运行任务；未指定 group 时运行全部。
- 给现有任务补充 `harness_regression` 和 `tool_governance` 分组。
- 补齐工具治理场景：unknown tool、repeated call。
- 从成功的 `patch_file` 工具调用中提取 `changed_files` 和 `patches_applied`。
- 明确 `failure_attribution_coverage` 定义为 `failure_category != "unknown"` 的任务比例。
- 保持现有 `python -m benchmarks` 行为兼容。

验收：

- `python -m benchmarks` 仍能运行。
- 生成 `benchmarks/results/latest.json` 和 Markdown summary。
- summary 中的指标来自实际 benchmark 结果。
- 工具治理任务可单独运行。
- failure attribution coverage 有明确统计口径。
- report 与 trace 能支撑复盘。

### P2：Verified Coding Agent Demo

把项目变成能演示的 coding agent。

产物：

- `mico/verification.py`。
- CLI `--verify-cmd` 和 `--verify-timeout`。
- `.mico/runs/<run_id>/verification.json`。
- `examples/tiny-python-bug/`。
- verification benchmark group 和 verifier pass rate 指标。

验收：

- 一条命令能完成：读代码 -> 修改 bug -> 执行验证 -> 生成报告。
- 验证命令不作为模型工具开放。
- verifier pass rate 可被 benchmark 统计。
- fake benchmark 验证 harness 行为；真实模型 demo 使用 OpenAI-compatible provider 产出可写进简历的 quality experiment 数据。

### P3：上下文治理

在 prompt 已结构化的基础上做预算控制。

产物：

- prompt budget config。
- context benchmark group。
- prompt compression metrics。

验收：

- current request 不被裁剪。
- 裁剪顺序明确，优先裁 history，再裁 memory，再裁 workspace summary。
- prompt compression ratio 来自 benchmark。
- 裁剪后任务仍能完成。

### P4：结构化记忆系统

放在上下文治理之后，因为 memory 最终要进入 prompt，并接受预算控制。

产物：

- `mico/memory.py`。
- memory benchmark group。
- `examples/follow-up-memory/`。

前置决策：

- follow-up benchmark 不复用原始 `Mico.history` 作为记忆来源。
- 结构化记忆通过显式 `memory` 对象或工件在 run 之间传递。
- 若后续要复用同一个 `Mico` 实例做多轮 `ask()`，必须先处理 history 串台问题。

验收：

- 记录 task summary、recent files、file summaries、episodic notes。
- follow-up benchmark 能统计 repeated file reads。
- 结构化记忆减少重复读文件的收益可量化。

### P5：Checkpoint / Resume

放在 memory 后面，因为 resume 需要恢复的不只是历史，还包括 memory、changed files 和 workspace fingerprint。

产物：

- `mico/checkpoint.py`。
- CLI `--resume`。
- resume benchmark group。

验收：

- 支持从 run id 恢复。
- 能识别 workspace drift。
- 生成 resume success rate 和 workspace drift detection rate。

### P6：简历与面试材料收口

产物：

- `docs/resume.md`。
- `docs/demo-guide.md`。
- README 改成项目展示入口。

验收：

- 所有数字来自 benchmark summary。
- 简历描述能对应到代码模块、运行工件和实验结果。
- demo guide 能让面试官或用户复现关键能力。

## 7. 禁止范围

近期不做：

- shell tool。
- `write_file` 工具。
- 多 agent。
- Web UI / TUI。
- 长期知识库。
- 自动 git commit。
- 复杂权限 UI。
- 多 provider 完整适配。
- 后台任务或任务队列。

## 8. 后续执行方式

- Claude Code 负责实现初稿、补测试、根据失败修复和整理说明。
- Codex 负责任务边界、架构审查、测试验收和最终接受。
- 每一阶段执行前，Claude Code 应先阅读 `AGENTS.md`、`CLAUDE.md` 和本文。
- 如使用 Superpowers 插件，应限于计划、自检、执行拆分和代码审查，不把 Superpowers 作为 `mico` 运行依赖。
- 每阶段提交后更新本文状态或新增对应总结文档，记录实测指标。

## 9. 当前第一步

下一步应执行 P1：Benchmark 指标生产线与工具治理指标化。

原因：

- P1 是后续所有简历数字的来源。
- 工具治理已有实现基础，和 metrics 骨架合并能最快产出第一组简历指标。
- P2 验证闭环、P3/P4/P5 的指标都需要统一 metrics 输出。
- 先做指标生产线，可以避免后续功能只停留在「实现了」，却无法写成可靠简历数据。
