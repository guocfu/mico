# Pico 作者笔记：项目定位、技术亮点与 mico 演进方向

> 分析日期：2026-06-22
> 来源：pico PDF 文档（`.tmp/2-pico.txt`）+ `analysis/pico-security-and-tools.md`
> 面向：mico 后续开发决策和简历包装

---

## 1. Pico 作者如何定位 pico 项目

作者将 pico 定位为 **本地代码智能体 Harness**（Agent Harness），而非简单的 "模型 + 工具" agent。

核心定位差异：
- **Agent** = 模型 + 工具 + 记忆 + 环境反馈的循环系统
- **Agent Harness** = 围绕 agent 搭建的软件脚手架，负责管理上下文、工具调用、提示词、状态和控制流
- **Coding Harness** = Agent 针对软件工程的特化版，管理代码上下文、开发工具、代码执行和迭代反馈

作者用了一个比喻：LLM 是厨师，Harness 是后厨调度系统（点单、备菜、分工、计时、查菜谱、调用设备、摆盘出菜）。厨师决定做菜能力，后厨系统决定这顿饭能不能有条理地做出来。

作者强调的核心观点：**模型外围的配套系统（工具调用、上下文管理、记忆功能）发挥的作用一点不比模型本身小。** Claude Code / Codex 比直接用底层模型更强，原因就在 Harness。

---

## 2. Pico 的核心技术亮点

### 2.1 三层架构

| 层 | 作用 | 对应模块 |
|---|---|---|
| 控制面 | 决定系统怎么跑 | cli.py, runtime.py, context_manager.py, tools.py, models.py |
| 状态面 | 决定系统记住什么、恢复什么 | memory.py, run_store.py, task_state.py, .pico/ |
| 证据面 | 决定系统怎么被验证、比较、复盘 | evaluator.py, metrics.py, trace.jsonl, report.json |

### 2.2 主控制循环（Pico.ask()）

四阶段循环：感知 → 决策 → 行动 → 记录

关键设计点：
- prompt 每轮重建（history/memory/workspace 都可能变）
- 模型输出先经 parse() 分流为 tool / final / retry 三种
- 工具执行统一过 run_tool() 边界，结果回写状态后继续下一轮
- 停机条件明确：final answer / step limit / retry limit

### 2.3 上下文管理

prompt 拆为五段独立管理：prefix / memory / relevant_memory / history / current_request

- current_request 地位最高，默认不裁
- 超预算裁剪顺序：relevant_memory → history → memory → prefix
- 每段有初始预算和最低 floor
- 输出附带 prompt_metadata，可解释 prompt 为什么长成这样

量化结果：12 组长上下文配置，平均 prompt 从 7082 压到 5664，平均压缩率 16.19%，最高 33.28%

### 2.4 结构化记忆

三层记忆：
- **Working Memory（LayeredMemory）**：task_summary, recent_files, file_summaries, episodic_notes
- **Durable Memory（DurableMemoryStore）**：跨会话长期事实，经 promotion gate 筛选后落到 `.pico/memory/`
- **Checkpoint / Resume**：恢复时比较文件 freshness、workspace fingerprint、tool signature、model/approval/flags

量化结果：12 个记忆依赖任务中，重复读文件从 60 次降到 0 次（v2.0）/ 从 8 次降到 3 次（v1.0），正确率从 66.7% 提升到 100%

### 2.5 工具安全治理

五阶段守卫管线：白名单 → 存在性 → 参数校验 → 重复调用 → 审批

- risky 标记内置在工具 spec
- 路径沙箱：`.resolve()` + `commonpath`
- shell 环境变量走 allowlist
- delegate 子 agent 强制 read_only + approval=never + 深度限制

量化结果：11 个治理场景中，3 次路径逃逸拦截、5 次无效参数拒绝、2 次重复调用拦截

### 2.6 评测框架

三层评测链路：
1. 固定 benchmark 任务集（coding_tasks.json）— 任务合同
2. BenchmarkEvaluator — 执行器 + verifier
3. metrics.py — 工件聚合和实验层

关键设计：不只是 pass rate，还拆成 harness regression、上下文治理、记忆收益、恢复正确性几层分别验证。对照实验包含 memory_on / memory_off / memory_irrelevant 三组。

---

## 3. 作者强调的工程/安全/agent 设计点

### 3.1 "Harness 而非 Agent" 思维

作者反复强调：不要把 pico 理解成 "模型 + 工具"，而是 "围绕模型运转的控制循环"。面试时讲项目应从 Harness 架构切入，而非工具清单。

### 3.2 工具是信任边界，不是能力扩展

工具层的重点不在 "接了哪些工具"，而在 "工具层为什么必须做成一条受控执行链"。模型不能直接碰外部世界，所有动作必须经过统一边界。

### 3.3 Prompt 是工作手册，不是拼接字符串

prefix 不只是规则文本，而是包含系统规则 + 工具清单 + 工作区摘要的工作手册。稳定前缀用 fingerprint 控制失效，不是每轮无脑重建。

### 3.4 记忆先解决重复劳动，再做高级能力

记忆层首要目标是减少重复读文件和跨轮确认已知事实，不是做成复杂的知识图谱。先做轻量工作记忆，再逐步扩展。

### 3.5 评测要有任务合同，不能靠体感

每个 benchmark 任务都是可执行合同（fixture repo + allowed tools + step budget + verifier），不是 "我试了几次觉得还行"。

### 3.6 状态分层：session vs run vs memory

- session：面向继续工作（history, memory）
- run artifact：面向回放和审计（task_state.json, trace.jsonl, report.json）
- durable memory：面向跨会话长期事实

---

## 4. 适合迁移到 mico 的设计

### 4.1 已迁移

| 设计 | 状态 |
|---|---|
| patch_file 恰好一次校验 | 已迁移 |
| ValueError 捕获 → ToolResult(ok=False) | 已迁移 |
| new_text 字段必须存在 | 已迁移 |
| commonpath 路径沙箱 | 已迁移 |
| symlink 逃逸测试 | 已迁移 |
| cross-drive ValueError 处理 | 已迁移 |

### 4.2 适合下一步迁移

| 设计 | 优先级 | 改动量 | 说明 |
|---|---|---|---|
| risky 标记内置在 ToolSpec | 中 | ~15 行 | 替代硬编码 WRITE_TOOLS 集合 |
| 重复调用检测 | 低 | ~10 行 | 防止模型死循环消耗 max_steps |
| trace 脱敏（secret redaction） | 中 | ~20 行 | 接入真实 provider 后必要 |
| trace 输出截断 | 低 | ~5 行 | 对 args/result 应用 clip() |
| 原子写 state.json | 低 | ~15 行 | tempfile + rename 防 crash 损坏 |
| workspace snapshot diff | 低 | ~30 行 | risky 工具执行前后 SHA-256 比对 |

### 4.3 暂不适合迁移

| 设计 | 原因 |
|---|---|
| 分层上下文管理 + 预算裁剪 | mico 当前 max_steps=4，prompt 不会膨胀 |
| 结构化记忆（LayeredMemory） | mico 是 one-shot，无跨轮需求 |
| checkpoint / resume | mico 是单次运行，无恢复需求 |
| delegate 子 agent | mico 范围禁止多 agent |
| 评测框架 + benchmark | mico 是 demo，不需要 |
| prompt cache / stable prefix | mico 当前轮次少，cache 收益不大 |

---

## 5. 哪些点适合写进简历

### 5.1 高价值关键词

- Agent Harness（而非 Agent）
- Tool Calling 安全边界
- Context Management / 上下文治理
- Checkpoint / Resume
- Layered Memory
- Run Trace / 运行审计
- Prompt Cache

### 5.2 简历亮点提炼

1. **架构思维**：不是堆功能，而是分控制面 / 状态面 / 证据面三层设计
2. **安全意识**：工具执行五阶段守卫、路径沙箱、risky 分类、审批策略、secret 脱敏
3. **量化能力**：有具体的压缩率、重复读取降低次数、pass rate 等数字
4. **评测方法论**：不只是跑通，有 benchmark 合约、对照实验、失败归因
5. **工程完整性**：trace.jsonl + state.json + report.json 三类运行工件，可回放可审计

---

## 6. Mico 接下来 3-5 个最有简历价值的迭代方向

### 方向 1：工具安全治理增强（简历价值：高，改动量：中）

**做什么**：ToolSpec 增加 risky 字段 + 重复调用检测 + trace 脱敏
**简历怎么说**：构建标准化工具调用安全边界，覆盖参数校验、工作区隔离、高风险审批、重复调用拦截和敏感信息脱敏
**量化点**：X 个治理场景中 Y 次拦截

### 方向 2：上下文治理（简历价值：高，改动量：大）

**做什么**：prompt 分段管理 + 预算裁剪 + prompt_metadata
**简历怎么说**：设计分层上下文管理与预算裁剪机制，将平均 prompt 长度压缩 X%
**前提**：需要接入真实模型 + 多轮任务才有意义

### 方向 3：结构化记忆（简历价值：高，改动量：大）

**做什么**：task_summary + recent_files + file_summaries + episodic_notes + freshness 校验
**简历怎么说**：将任务摘要、文件摘要和过程笔记分层管理，减少重复读文件次数从 X 次降到 Y 次
**前提**：需要多轮任务场景

### 方向 4：评测框架（简历价值：高，改动量：中）

**做什么**：固定 benchmark 任务集 + FakeModelClient 对照 + verifier + metrics 聚合
**简历怎么说**：建立固定 benchmark 与运行审计体系，覆盖 pass_rate / attempts / tool_steps / failure_category 的自动汇总与回归对比
**前提**：需要先有稳定的功能基线

### 方向 5：Checkpoint / Resume（简历价值：中，改动量：中）

**做什么**：session 状态保存 + workspace drift 检测 + 恢复时 freshness 校验
**简历怎么说**：设计 checkpoint/resume 机制，让 agent 在上下文超预算和中断场景下恢复任务状态
**前提**：需要交互式 REPL 或长时间任务

### 推荐优先级

对于 mico 当前 demo 阶段，最有性价比的路线：

1. **方向 1（安全治理）**— 独立可交付，改动量可控，简历可量化
2. **方向 4（评测框架）**— FakeModelClient 已有基础，可做确定性测试
3. **方向 2+3（上下文+记忆）**— 需要接入真实模型后才有意义，是 v2.0 重点

---

## 7. 建议的简历项目描述

### 项目名称

Mico：本地代码智能体 Harness

### 核心技术

Python、Agent Harness、Tool Calling、Context Management、Run Trace

### 项目描述（v1.0，当前可写）

面向代码仓库任务开发本地代码 Agent Harness，覆盖模型接入、工具调用、运行审计，重点解决工具副作用控制和运行可观测性问题。

### 核心职责与贡献（4-6 条 bullet）

1. **Agent Harness 架构设计**：负责本地代码 Agent 的整体设计与开发，统一模型接入、工具执行和运行工件落盘流程，形成可回放的任务执行链路；支持 2 类模型后端、4 类工具和 3 类运行工件。

2. **工具安全与运行治理**：构建标准化工具调用与安全边界，覆盖参数校验、工作区隔离（路径沙箱 + symlink 逃逸防护）、高风险审批和运行时错误捕获；patch_file 要求 old_text 恰好出现一次，确保替换操作确定性可解释。

3. **运行审计闭环**：每次任务执行自动生成 trace.jsonl（逐事件时间线）、state.json（运行快照）和 report.json（聚合摘要），支持任务过程回放与失败归因。

4. **多模型后端适配**：设计统一 ModelClient 接口，支持 FakeModelClient（确定性测试）和 OpenAI-compatible（真实模型）两类后端，通过 CLI 参数无缝切换；API key 作为私有字段，不进入 trace/report。

### 项目描述（v2.0，完善上下文、记忆和评测后可写）

面向代码仓库长链路任务开发本地代码 Agent Harness，围绕模型接入、工具调用、上下文管理、结构化记忆、运行审计和评测闭环做系统化设计，重点解决多轮任务里 prompt 膨胀、重复读文件、工具副作用不可控和结果难复盘的问题。

### 核心职责与贡献（v2.0 版本，6 条 bullet）

1. **Agent Harness 架构设计**：负责本地代码 Agent 的整体设计与开发，统一模型接入、工具执行、会话状态和运行工件落盘流程，形成可回放的任务执行链路；支持 2 类模型后端、4+ 类工具和 3 类运行工件。

2. **长上下文治理**：设计分层上下文管理与预算裁剪机制，将平均 prompt 长度压缩 X%，同时保证当前请求不被裁坏。

3. **结构化记忆系统**：将任务摘要、文件摘要和会话笔记分层管理，结合 freshness 校验减少重复读取；在记忆依赖任务中，重复读文件次数从 X 次降到 Y 次。

4. **工具安全与运行治理**：构建标准化工具调用与安全边界，覆盖参数校验、工作区隔离、高风险审批、重复调用拦截和敏感信息脱敏；在固定回归任务中保持 100% 通过率。

5. **评测与审计闭环**：建立固定 benchmark 与运行审计体系，支持 pass_rate / attempts / tool_steps / failure_category / trace 的自动汇总与回归对比。

6. **模型后端效果评估**：搭建多 provider 对照实验框架，支撑不同模型后端的效果与成本评估。

---

## 附录：Pico 作者的学习方法论建议

作者强调的方法论（适用于 mico 开发者自学）：

1. **先看简历描述** → 假设自己是面试官，想会追问什么
2. **带着问题看模块文档** → 对照核心代码 → 看测试
3. **每看完一章，强制输出三件事**：解决什么问题、怎么做的、为什么这样做而不是另一种
4. **整理成面试话术**：30 秒 / 1 分钟 / 3 分钟三种讲法
5. **亲手改一两个点**：让项目真正变成自己的（如改上下文裁剪策略、补记忆召回规则、加工具安全校验）
6. **不先看八股，直接看项目**：build first，边做边碰问题，再回头查知识

核心理念：**AI 的作用是帮你放大理解，不是替你理解。**
