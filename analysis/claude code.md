 Here is Claude's plan:
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
 项目重定位：从 Demo 到可用 Coding Agent

 Context

 mico 当前只能读文件、搜索和精确替换，不能创建新文件或执行命令。用 fake provider
 跑预设输出，无法完成真实编码任务。这导致项目无法实际使用，简历价值大打折扣。

 本次改动的目标：让 mico 成为真正能用的 coding agent，同时保留治理和评测能力。

 改动总览

 1. 新增 write_file 和 shell 工具 — 让 agent 能创建文件、执行命令
 2. Provider 优先级调整 — 有 API key 就用真实模型，缺参数给默认值
 3. 更新项目文档 — CLAUDE.md、AGENTS.md、README、路线图

 Step 1: 新增 write_file 工具

 文件: mico/tools.py

 在 TOOL_SPECS 中添加：
 "write_file": ToolSpec(
     "Create or overwrite a file with UTF-8 content.",
     '{"path": "str", "content": "str"}',
     requires_approval=True,
     read_only=False,
     concurrency_safe=False,
 ),

 在 validate_tool() 中添加分支：
 if name == "write_file":
     if "path" not in args:
         raise ValueError("path field is required")
     workspace.path(args["path"])
     if "content" not in args:
         raise ValueError("content field is required")
     return

 在 execute_validated_tool() 中添加 dispatch：
 if name == "write_file":
     return _write_file(workspace, args)

 实现 _write_file()：
 def _write_file(workspace, args):
     path = workspace.path(args["path"])
     content = str(args["content"])
     path.parent.mkdir(parents=True, exist_ok=True)
     path.write_text(content, encoding="utf-8")
     return f"wrote {len(content)} chars to {workspace.relative(path)}"

 Step 2: 新增 shell 工具

 文件: mico/tools.py

 在 TOOL_SPECS 中添加：
 "shell": ToolSpec(
     "Run a shell command in the workspace root.",
     '{"command": "str", "timeout": "int=30"}',
     requires_approval=True,
     read_only=False,
     concurrency_safe=False,
     max_result_chars=8000,
 ),

 在 validate_tool() 中添加分支：
 if name == "shell":
     command = str(args.get("command", "")).strip()
     if not command:
         raise ValueError("command must not be empty")
     timeout = int(args.get("timeout", 30))
     if timeout < 1 or timeout > 300:
         raise ValueError("timeout must be between 1 and 300 seconds")
     return

 在 execute_validated_tool() 中添加 dispatch：
 if name == "shell":
     return _shell(workspace, args)

 实现 _shell()：
 def _shell(workspace, args):
     command = str(args["command"])
     timeout = int(args.get("timeout", 30))
     try:
         result = subprocess.run(
             command,
             shell=True,
             cwd=str(workspace.root),
             capture_output=True,
             text=True,
             timeout=timeout,
         )
         parts = []
         if result.stdout.strip():
             parts.append(result.stdout.strip())
         if result.stderr.strip():
             parts.append(result.stderr.strip())
         output = "\n".join(parts) or "(no output)"
         return f"exit_code={result.returncode}\n{output}"
     except subprocess.TimeoutExpired:
         return f"error: command timed out after {timeout}s"
     except OSError as exc:
         return f"error: {exc}"

 设计决策：shell=True 是有意的，因为 shell 工具需要支持管道、重定向等。安全由
 requires_approval=True 保证，approval_policy="never" 会完全阻断。

 Step 3: 更新 prompt 静态前缀

 文件: mico/prompt.py (第 44-45 行)

 # 旧
 return "You are mico, a tiny local coding agent."
 # 新
 return "You are mico, a local coding agent. You can read, write, patch files, search
 the workspace, and run shell commands."

 Step 4: Provider 优先级调整

 文件: mico/cli.py

 修改 _resolve_config() (第 80-84 行)：

 # 旧
 if provider is None:
     if has_api_key and base_url and model:
         provider = "openai-compatible"
     else:
         provider = "fake"

 # 新
 if provider is None:
     if has_api_key:
         provider = "openai-compatible"
     else:
         provider = "fake"

 if provider == "openai-compatible":
     if not base_url:
         base_url = "https://api.openai.com/v1"
     if not model:
         model = "gpt-4o-mini"

 更新 --provider help 文本 (第 28 行)：
 help="Model provider. Auto-detected: if MICO_API_KEY is set, uses openai-compatible;
 otherwise fake.",

 Step 5: 更新 CLAUDE.md

 文件: CLAUDE.md

 1. "允许实现的工具" 部分添加 write_file 和 shell
 2. "严格禁止加入" 部分删除 write_file 工具 和 shell 工具
 3. "真实模型 API 作为默认配置" 改为 "真实模型 API 作为可选配置（只需设置
 MICO_API_KEY）"

 Step 6: 更新 AGENTS.md

 文件: AGENTS.md

 1. "当前实现边界" 工具列表添加 write_file 和 shell
 2. "暂不实现" 删除 不加入 write_file 工具或 shell 工具
 3. "不把真实模型 API 作为默认配置" 改为 "真实模型 API 作为可选配置（只需设置
 MICO_API_KEY）"

 Step 7: 更新 README.md

 文件: README.md

 1. 开头描述改为 "mico is a local coding agent that can read, write, patch files,
 search the workspace, and run shell commands."
 2. Tools 部分添加 write_file 和 shell
 3. OpenAI-compatible 部分简化为只需设置 MICO_API_KEY

 Step 8: 更新路线图

 文件: analysis/mico-resume-project-roadmap.md

 1. "禁止范围" 删除 shell tool 和 write_file 工具
 2. 项目定位从 "Verified Coding Agent Harness" 更新为强调"可用的 coding agent"
 3. 当前步骤更新

 Step 9: 新增 benchmark cases

 文件: benchmarks/tasks.json

 新增 4 个 case：

 ┌────────────────────┬────────────────────┬───────────────────────────────────┐
 │        name        │       group        │               说明                │
 ├────────────────────┼────────────────────┼───────────────────────────────────┤
 │ write_file_success │ harness_regression │ write_file 创建新文件             │
 ├────────────────────┼────────────────────┼───────────────────────────────────┤
 │ write_file_denied  │ tool_governance    │ write_file 被 approval=never 阻断 │
 ├────────────────────┼────────────────────┼───────────────────────────────────┤
 │ shell_success      │ harness_regression │ shell 执行 echo 命令              │
 ├────────────────────┼────────────────────┼───────────────────────────────────┤
 │ shell_denied       │ tool_governance    │ shell 被 approval=never 阻断      │
 └────────────────────┴────────────────────┴───────────────────────────────────┘

 Step 10: 新增工具单元测试

 文件: tests/test_tools.py

 新增 TestWriteFile 类：success、creates_parent_dirs、overwrites_existing、missing_pat
 h、missing_content、path_escape、requires_approval

 新增 TestShell 类：success、captures_stderr、nonzero_exit、timeout、empty_command、in
 valid_timeout、requires_approval

 Step 11: 更新 benchmark 测试

 文件: tests/test_benchmarks.py

 - case 总数 12 → 16
 - tool_governance_total 4 → 6
 - 新增 write_file/shell 相关 case 断言

 Step 12: 更新 CLI 测试

 文件: tests/test_cli_env.py

 - test_resolve_partial_env_stays_fake → 改为
 test_resolve_partial_env_auto_detects_openai_compatible（只有 API key 时应自动检测为
  openai-compatible）
 - 新增 test_resolve_no_api_key_stays_fake

     │                                                                                │
     │ 文件: tests/test_cli_env.py                                                    │
     │                                                                                │
     │ - test_resolve_partial_env_stays_fake → 改为                                   │
     │ test_resolve_partial_env_auto_detects_openai_compatible（只有 API key          │
     │ 时应自动检测为 openai-compatible）                                             │
     │ - 新增 test_resolve_no_api_key_stays_fake                                      │
     │                                                                                │
     │ Step 13: 更新 live smoke 测试                                                  │
     │                                                                                │
     │ 文件: benchmarks/live.py + tests/test_benchmarks_live.py                       │
     │                                                                                │
     │ - _LIVE_SMOKE_CASES 添加 write_file 和 shell case                              │
     │ - _REQUIRED_KEYS 改为只检查 MICO_API_KEY                                       │
     │ - _default_model_client_factory 使用默认 base_url 和 model                     │
     │ - _ScriptedLiveModelClient 添加 write_file 和 shell handler                    │
     │ - 测试中 total 3 → 5                                                           │
     │                                                                                │
     │ 验证                                                                           │
     │                                                                                │
     │ python -m pytest --basetemp .tmp/pytest-basetemp                               │
     │ python -m mico "列出当前目录"                                                  │
     │                                                                                │
     │ 确认所有测试通过，.mico/runs/ 下有 trace.jsonl、state.json、report.json。      │
     │                                                                                │
     │ 实施顺序                                                                       │
     │                                                                                │
     │ 1. tools.py (Step 1-2) — 核心工具实现                                          │
     │ 2. prompt.py (Step 3) — 更新前缀                                               │
     │ 3. cli.py (Step 4) — Provider 优先级                                           │
     │ 4. test_tools.py (Step 10) — 工具测试                                          │
     │ 5. tasks.json (Step 9) — Benchmark cases                                       │
     │ 6. test_benchmarks.py (Step 11) — Benchmark 测试                               │
     │ 7. test_cli_env.py (Step 12) — CLI 测试                                        │
     │ 8. live.py + test (Step 13) — Live smoke                                       │
     │ 9. 文档 (Step 5-8) — CLAUDE.md、AGENTS.md、README、路线图   