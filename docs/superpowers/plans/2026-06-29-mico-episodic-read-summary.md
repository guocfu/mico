# Mico Episodic Note Read Summary Alignment Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:receiving-code-review`, then `superpowers:test-driven-development`, then `superpowers:verification-before-completion`. Claude Code 执行时必须先读取本计划并使用 Superpowers；不得把 Superpowers 加入 `mico` 运行时依赖。

**Goal:** 将 `read_file` 成功后的 episodic note `text` 从操作描述改为文件内容摘要，并与 Working Memory 的 `file_summaries` 摘要一致。

**Architecture:** 在 `mico.memory` 增加独立的 `summarize_read_result()`，由 `mico.runtime.Mico._after_tool_result()` 在 `read_file` 分支复用。只对齐 `read_file` 摘要语义，不改 Durable Memory、ContextManager、prompt 拼装或 tag 策略。

**Tech Stack:** Python、pytest、当前 `Mico` / `SessionMemoryState` / `ToolResult` 实现。

---

## 审查结论

反馈成立。

- 当前 `mico/runtime.py` 中 `read_file` 的 episodic note 是 `"read " + path`。
- `pico/pico/runtime.py` 中 `read_file` 会调用 `memorylib.summarize_read_result(result)`，并把同一个 `summary` 同时写入 file summary 和 episodic note。
- `pico/pico/features/memory.py` 的摘要逻辑会跳过 `# path` 头部，取前 3 个非空内容行，用 ` | ` 连接，限制 180 字符。
- mico 的 `ToolResult` 是 dataclass，没有自定义 `__str__`，所以 mico 版本应优先读取 `result.content`，不能直接照抄 pico 的 `str(result)`。

## Implementation Changes

### Task 1: 添加摘要函数与单元测试

**Files:**
- Modify: `mico/memory.py`
- Modify: `tests/test_memory.py`

- [ ] 在 `tests/test_memory.py` 修改 import：

```python
from mico.memory import SessionMemoryState, summarize_read_result
```

- [ ] 新增失败测试：

```python
class ReadResult:
    def __init__(self, content):
        self.content = content


def test_summarize_read_result_skips_read_file_header_and_uses_first_three_lines():
    result = ReadResult("# notes.txt\n   1: alpha\n   2: beta\n   3: gamma\n   4: delta")

    assert summarize_read_result(result) == "1: alpha | 2: beta | 3: gamma"


def test_summarize_read_result_returns_empty_when_only_header_or_blank_lines():
    result = ReadResult("# empty.txt\n\n   \n")

    assert summarize_read_result(result) == "(empty)"


def test_summarize_read_result_respects_limit():
    result = ReadResult("# long.txt\n   1: " + ("x" * 300))

    assert summarize_read_result(result, limit=20) == ("1: " + ("x" * 17))


def test_summarize_read_result_accepts_plain_string_fallback():
    assert summarize_read_result("alpha\n\nbeta\ngamma\ndelta") == "alpha | beta | gamma"
```

- [ ] 运行 RED：

```bash
python -m pytest tests/test_memory.py -k summarize_read_result -v
```

Expected: fail because `summarize_read_result` does not exist.

- [ ] 在 `mico/memory.py` 新增最小实现：

```python
def summarize_read_result(result, limit=180):
    content = result.content if hasattr(result, "content") else result
    if content is None:
        content = ""
    lines = [line.strip() for line in str(content).splitlines() if line.strip()]
    if not lines:
        return "(empty)"
    if lines[0].startswith("# "):
        lines = lines[1:]
    if not lines:
        return "(empty)"
    summary = " | ".join(lines[:3])
    return summary[:limit]
```

- [ ] 运行 GREEN：

```bash
python -m pytest tests/test_memory.py -k summarize_read_result -v
```

Expected: pass.

### Task 2: 让 read_file 的 file_summary 与 episodic note 复用同一摘要

**Files:**
- Modify: `mico/runtime.py`
- Modify: `tests/test_agent_loop.py`

- [ ] 在 `tests/test_agent_loop.py` 新增失败测试：

```python
def test_session_memory_read_file_note_text_matches_content_summary(tmp_path):
    (tmp_path / "notes.txt").write_text(
        "alpha\nbeta\ngamma\ndelta\n",
        encoding="utf-8",
    )
    workspace = Workspace.build(tmp_path)
    agent = Mico(
        model_client=FakeModelClient([
            '<tool>{"name":"read_file","args":{"path":"notes.txt","start":1,"end":80}}</tool>',
            "<final>done</final>",
        ]),
        workspace=workspace,
        run_store=RunStore(tmp_path / ".mico" / "runs"),
    )

    agent.ask("read file")

    data = json.loads((tmp_path / ".mico" / "sessions" / "default.json").read_text(encoding="utf-8"))
    memory = data["memory"]
    expected = "1: alpha | 2: beta | 3: gamma"

    assert memory["file_summaries"]["notes.txt"]["summary"] == expected
    assert memory["episodic_notes"][-1]["text"] == expected
    assert memory["episodic_notes"][-1]["source"] == "read_file:notes.txt"
    assert memory["episodic_notes"][-1]["tags"] == ["file", "txt"]
```

- [ ] 运行 RED：

```bash
python -m pytest tests/test_agent_loop.py::test_session_memory_read_file_note_text_matches_content_summary -v
```

Expected: fail because current note text is `read notes.txt` and file summary is raw `result.content[:200]`.

- [ ] 修改 `mico/runtime.py`：

```python
import hashlib

from .agent_loop import AgentLoop
from .memory import SessionMemoryState, summarize_read_result
```

把 `_after_tool_result()` 的 `read_file` 分支改为：

```python
if name == "read_file":
    path = args.get("path", "")
    self.session_memory.remember_file(path)
    summary = summarize_read_result(result)
    freshness = hashlib.sha256(summary.encode()).hexdigest()[:16]
    self.session_memory.record_file_summary(path, summary, freshness=freshness)
    ext = path.rsplit(".", 1)[-1] if "." in path else ""
    self.session_memory.append_episodic_note(
        summary, tags=["file", ext], source="read_file:" + path)
elif name in ("write_file", "patch_file"):
    path = args.get("path", "")
    self.session_memory.invalidate_file(path)
```

保留 `write_file`、`patch_file`、`run_command` 的现有 episodic note 行为不变。

- [ ] 运行 GREEN：

```bash
python -m pytest tests/test_agent_loop.py::test_session_memory_read_file_note_text_matches_content_summary -v
```

Expected: pass.

## Test Plan

- [ ] 运行 memory 单元测试：

```bash
python -m pytest tests/test_memory.py -v
```

- [ ] 运行 session memory 集成测试：

```bash
python -m pytest tests/test_agent_loop.py -k session_memory -v
```

- [ ] 运行完整测试：

```bash
python -m pytest
```

- [ ] 如完整测试仍出现既有 benchmark 失败，必须报告失败用例和是否为本变更引入；不得直接声明全量通过。

- [ ] 手动检查一次 session 文件内容：读取一个 4 行文件后，`.mico/sessions/default.json` 中同一 `read_file` 的 `file_summaries[path].summary` 与最新 `episodic_notes[-1].text` 应完全一致，且不包含 `# notes.txt` header。

## Claude Code Execution Handoff

Claude Code 应在 `E:\Project\ai\my-coding-agent\mico` 仓库完成。执行提示应包含：

```text
你在 E:\Project\ai\my-coding-agent\mico 工作。必须使用 Superpowers：先使用 superpowers:receiving-code-review 验证反馈，再使用 superpowers:test-driven-development 按 RED/GREEN 实现，完成前使用 superpowers:verification-before-completion。

只执行 “Mico Episodic Note Read Summary Alignment Plan”。不要实现 Durable Memory、remember、ContextManager、prompt 重排或其他记忆系统阶段。不要 git commit，除非用户另行明确要求。

必须先写失败测试：
1. tests/test_memory.py 中 summarize_read_result 的摘要行为测试；
2. tests/test_agent_loop.py 中 read_file 后 file_summary 与 episodic note text 相同的集成测试。

然后修改：
- mico/memory.py：新增 summarize_read_result(result, limit=180)
- mico/runtime.py：read_file 分支复用 summarize_read_result，同时写 file_summary 和 episodic note

验证命令：
- python -m pytest tests/test_memory.py -v
- python -m pytest tests/test_agent_loop.py -k session_memory -v
- python -m pytest

完成后报告：修改文件、RED/GREEN 证据、测试结果、是否有全量测试既有失败。
```

## Assumptions

- 保持 mico 当前 tag 语义：`["file", ext]`，不照搬 pico 的 path tag，避免扩大行为变化。
- `summary` 对 mico 的 `read_file` 输出包含行号，例如 `1: alpha | 2: beta | 3: gamma`。
- `freshness` 继续使用 `sha256(summary.encode()).hexdigest()[:16]`。
- 这次只修 episodic note 内容对齐，不改设计文档；如后续要求文档同步，再单独更新。
