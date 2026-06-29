# Mico Durable Memory + Remember Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to execute this plan. Use `superpowers:test-driven-development` before production code changes. Use `superpowers:verification-before-completion` before reporting completion. Do not stop, close, or kill any `claude` process unless the user explicitly commands it.

## Summary

Mico already has session working memory, episodic notes, read-file summary alignment, and prompt context injection. This plan adds the first durable memory layer for a general coding agent: the model can explicitly call a `remember` tool to write cross-session notes, and future prompts can include a short memory index plus relevant durable notes.

This is v1 durable memory. It intentionally does not implement automatic long-term memory extraction, embeddings, vector search, background summarization, or checkpoint/resume.

## Key Changes

### Durable Memory Store

- Add `mico/memory_store.py` with a `DurableMemory` class.
- Store data under `.mico/memory/`.
- Use a fixed topic whitelist:
  - `profile`
  - `projects`
  - `preferences`
  - `decisions`
  - `conventions`
  - `notes`
- Maintain `MEMORY.md` as a short index plus one markdown file per topic.
- Provide these public methods:
  - `remember(topic, note, tags=None)` appends one durable note and updates the index.
  - `render_index(max_chars=...)` returns a short prompt-safe index.
  - `retrieve(query, limit=3)` returns relevant durable notes using deterministic topic/keyword matching.
- Validate topic, note, and tags before writing. Reject empty notes and non-string tags.

### Remember Tool

- Register `remember` in `TOOL_SPECS`.
- Schema:
  - `topic: str`
  - `note: str`
  - `tags?: list[str]`
- Tool policy:
  - `requires_approval=True`
  - `read_only=False`
  - `concurrency_safe=False`
- Do not route `remember` through normal `write_file`; `.mico/memory` is an internal agent state directory.
- Extend `ToolExecutor` with `custom_handlers` so `Mico` can handle `remember` using its `DurableMemory` instance after normal validation and approval.
- Keep existing `run_command` approval behavior compatible.
- Extend CLI approval callback to accept both the existing argv-style request and a dict-style generic tool approval request.

### Runtime And Context Injection

- Initialize `self.durable_memory` in `Mico`.
- Register a custom handler for `remember`.
- On successful `remember`, optionally append a short session episodic note such as `remembered <topic>: <note preview>` so the current run can refer to the action.
- Extend `ContextManager` to include durable memory without changing the rule that the current user request is the final prompt anchor.
- Prompt section order:
  - prefix
  - memory index
  - working memory
  - relevant memory
  - history
  - current request
- `memory index` should be short and derived from `DurableMemory.render_index()`.
- `relevant memory` should combine existing episodic notes with durable notes from `DurableMemory.retrieve(...)`.
- Add metadata for durable memory availability/usage and budget truncation.

## Test Plan

Write tests before production changes and watch them fail for the expected missing-feature reason.

- Add `tests/test_memory_store.py`:
  - initializes `.mico/memory`
  - creates `MEMORY.md` and topic files
  - appends a remembered note
  - rejects invalid topic, empty note, and invalid tags
  - retrieves relevant notes by topic/keyword
- Update tool tests:
  - `remember` appears in the catalog
  - validation accepts valid args and rejects invalid args
  - approval modes `auto`, `ask`, and `never` behave correctly
- Update agent/runtime tests:
  - model can call `remember`
  - durable memory files are written
  - a later run can see durable memory in the prompt
- Update context tests:
  - durable memory index appears before current request
  - current request remains the final section
  - relevant durable notes are included within budget
- Update CLI approval tests:
  - callback remains compatible with argv requests
  - callback handles dict-style `remember` approval requests

Verification commands:

```bash
python -m pytest tests/test_memory_store.py -v
python -m pytest tests/test_tools.py -k remember -v
python -m pytest tests/test_agent_loop.py -k memory -v
python -m pytest tests/test_context_manager.py -v
python -m pytest tests/test_cli_repl.py -k approval -v
python -m pytest
```

## Claude Code Execution Constraints

- Claude Code must read this plan, `CLAUDE.md`, and the relevant memory/context/tool code before editing.
- Claude Code must use Superpowers as required by the header.
- Claude Code must not modify reference projects such as `pico` or `claude-code`.
- Claude Code must not stop, close, or kill any `claude` process.
- Claude Code must not commit automatically.
- Codex will review the resulting diff and verification output before reporting final status.

## Assumptions

- The durable memory system is for a general coding agent, not a domain-specific interview assistant.
- v1 only supports explicit `remember` writes. Ordinary conversation, file reads, diffs, and command outputs are not automatically promoted into durable memory.
- `.mico/memory` is internal agent state and may be written by `DurableMemory` even though normal user-facing file tools should avoid `.mico`.
