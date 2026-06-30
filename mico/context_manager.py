"""ContextManager assembles prompt sections from PromptBuilder and SessionMemoryState."""

import re

from mico.prompt import PromptBuilder, PromptBundle
from mico.memory import SessionMemoryState

MAX_HISTORY_ITEMS = 6
DEFAULT_TOTAL_BUDGET = 10000

DEFAULT_SECTION_BUDGETS = {
    "prefix": 2400,
    "memory_index": 800,
    "checkpoint": 1200,
    "working_memory": 1000,
    "relevant_memory": 2000,
    "history": 3800,
}

DEFAULT_SECTION_FLOORS = {
    "prefix": 1400,
    "memory_index": 300,
    "checkpoint": 200,
    "working_memory": 300,
    "relevant_memory": 400,
    "history": 1000,
}

REDUCTION_ORDER = ("history", "relevant_memory", "working_memory", "checkpoint", "memory_index", "prefix")
RECENT_WINDOW = 6
RECENT_ITEM_LIMIT = 900
OLDER_MSG_LIMIT = 80
OLDER_TOOL_LIMIT = 120
MAX_OLDER_READ_RANGES_PER_FILE = 3
MAX_OLDER_READ_FILE_ENTRIES = 12


def _clip_with_marker(text, limit):
    text = str(text or "")
    if limit is None or limit <= 0 or len(text) <= limit:
        return text
    if limit <= 15:
        return text[:limit]
    return text[: limit - 15] + "... [truncated]"


class ContextManager:
    """Assembles a full prompt from prefix, working memory, episodic notes, history,
    and current request sections.

    Budget v1 uses character-based section compression and reports any
    remaining over-budget prompt via metadata.
    """

    def __init__(self, prompt_builder, total_budget=DEFAULT_TOTAL_BUDGET, section_budgets=None):
        self.prompt_builder = prompt_builder
        self.total_budget = total_budget
        self.section_budgets = dict(DEFAULT_SECTION_BUDGETS)
        self.section_budgets.update(section_budgets or {})
        self.section_floors = dict(DEFAULT_SECTION_FLOORS)

    def build(self, *, tool_catalog, approval_policy, workspace_root,
              user_message, history, session_memory, durable_memory=None,
              checkpoint_text="", resume_state=None):
        """Assemble all prompt sections and return a PromptBundle with metadata."""
        # 1. Prefix — always included
        prefix = self.prompt_builder.prefix_text(
            tool_catalog=tool_catalog,
            approval_policy=approval_policy,
            workspace_root=workspace_root,
        )

        # 2. Durable memory index — short cross-session index, if available
        memory_index_text = ""
        durable_notes_available = 0
        if durable_memory is not None:
            index = durable_memory.render_index()
            if index:
                memory_index_text = "Memory index:\n" + index
            if hasattr(durable_memory, "count_notes"):
                durable_notes_available = durable_memory.count_notes()

        # 3. Checkpoint — only when resume is requested
        checkpoint_section = checkpoint_text if checkpoint_text else ""

        # 4. Working memory — only if task_summary or recent_files present
        if session_memory.task_summary or session_memory.recent_files:
            working_memory_text = "Working memory:\n" + session_memory.render_memory_text()
        else:
            working_memory_text = ""

        # 5. Relevant memory — episodic notes plus matching durable notes
        retrieved_notes = self._retrieve_episodic_notes(session_memory, user_message, limit=3)
        durable_notes = []
        if durable_memory is not None:
            durable_notes = durable_memory.retrieve(user_message, limit=3)

        relevant_lines = ["- " + note["text"] for note in retrieved_notes]
        relevant_lines.extend(
            "- [durable:" + note["topic"] + "] " + note["text"]
            for note in durable_notes
        )
        if relevant_lines:
            relevant_memory_text = "Relevant memory:\n" + "\n".join(relevant_lines)
        else:
            relevant_memory_text = ""

        # 5. History — always included
        history_text, older_history_used, older_read_file_entries_used = self._history_text(history)
        history_items_compacted = max(0, len(history) - RECENT_WINDOW)
        history_items_used = min(len(history), RECENT_WINDOW) + older_history_used

        # 6. Current request — always included, always last
        current_request_text = self.prompt_builder.current_request_text(user_message)

        # Capture original section sizes before compression
        section_chars_original = {
            "prefix": len(prefix),
            "memory_index": len(memory_index_text),
            "checkpoint": len(checkpoint_section),
            "working_memory": len(working_memory_text),
            "relevant_memory": len(relevant_memory_text),
            "history": len(history_text),
            "current_request": len(current_request_text),
        }

        # Section compression
        section_texts = {
            "prefix": prefix,
            "memory_index": memory_index_text,
            "checkpoint": checkpoint_section,
            "working_memory": working_memory_text,
            "relevant_memory": relevant_memory_text,
            "history": history_text,
        }
        sections_truncated = []
        effective_budgets = self._effective_section_budgets(section_texts, current_request_text)

        # Prefix: use compact prefix instead of blind clipping to preserve protocol
        prefix_budget = effective_budgets.get("prefix", len(prefix))
        if len(prefix) > prefix_budget:
            prefix = self._compact_prefix_text(
                tool_catalog=tool_catalog,
                approval_policy=approval_policy,
                workspace_root=workspace_root,
                budget=prefix_budget,
            )
            section_texts["prefix"] = prefix
            if "prefix" not in sections_truncated:
                sections_truncated.append("prefix")

        # Other sections: clip normally
        for section_name in REDUCTION_ORDER:
            if section_name == "prefix":
                continue
            section_texts[section_name] = self._clip_section(
                section_name,
                section_texts[section_name],
                effective_budgets.get(section_name, len(section_texts[section_name])),
                sections_truncated,
            )
        memory_index_text = section_texts["memory_index"]
        checkpoint_section = section_texts["checkpoint"]
        working_memory_text = section_texts["working_memory"]
        relevant_memory_text = section_texts["relevant_memory"]
        history_text = section_texts["history"]

        # Concatenate all non-empty sections with newlines
        sections = [prefix, memory_index_text, checkpoint_section, working_memory_text, relevant_memory_text, history_text, current_request_text]
        non_empty = [s for s in sections if s]
        text = "\n".join(non_empty) + "\n"

        # Metadata
        tool_count = len(tool_catalog)
        restricted_tool_count = sum(1 for t in tool_catalog if not t["allowed"])

        section_chars = {
            "prefix": len(prefix),
            "memory_index": len(memory_index_text),
            "checkpoint": len(checkpoint_section),
            "working_memory": len(working_memory_text),
            "relevant_memory": len(relevant_memory_text),
            "history": len(history_text),
            "current_request": len(current_request_text),
        }

        # Checkpoint metadata
        resume_status = "no-checkpoint"
        stale_paths = []
        runtime_identity_mismatch_fields = []
        if resume_state is not None:
            resume_status = resume_state.get("status", "no-checkpoint")
            stale_paths = resume_state.get("stale_paths", [])
            runtime_identity_mismatch_fields = resume_state.get("runtime_identity_mismatch_fields", [])

        metadata = {
            "prompt_chars": len(text),
            "total_budget": self.total_budget,
            "over_budget": len(text) > self.total_budget,
            "section_chars": section_chars,
            "section_chars_original": section_chars_original,
            "section_budgets": dict(self.section_budgets),
            "section_floors": dict(self.section_floors),
            "sections_truncated": sections_truncated,
            "history_items_compacted": history_items_compacted,
            "older_read_file_entries_used": older_read_file_entries_used,
            "history_items_total": len(history),
            "history_items_used": history_items_used,
            "tool_count": tool_count,
            "restricted_tool_count": restricted_tool_count,
            "approval_policy": approval_policy,
            "episodic_notes_available": len(session_memory.episodic_notes),
            "episodic_notes_used": len(retrieved_notes),
            "durable_memory_notes_available": durable_notes_available,
            "durable_memory_notes_used": len(durable_notes),
            "durable_memory_notes_truncated": sum(1 for note in durable_notes if note.get("truncated")),
            "current_request_chars": len(user_message),
            "current_request_preserved_rate": 1.0,
            "resume_status": resume_status,
            "checkpoint_chars": len(checkpoint_section),
            "stale_paths": stale_paths,
            "runtime_identity_mismatch_fields": runtime_identity_mismatch_fields,
        }

        return PromptBundle(text=text, metadata=metadata)

    def _retrieve_episodic_notes(self, session_memory, query, limit=3):
        """Retrieve top episodic notes matching query tokens.

        Scoring: each token hit on note text, source, or tags adds 1.
        Sorted by (score desc, note_index desc).
        """
        query_tokens = set(re.findall(r'[A-Za-z0-9_]+', query.lower()))
        if not query_tokens:
            return []

        scored = []
        for note in session_memory.episodic_notes:
            score = 0
            note_text = note.get("text", "").lower()
            note_source = note.get("source", "").lower()
            note_tags = set(note.get("tags", []))
            for token in query_tokens:
                if token in note_text or token in note_source or token in note_tags:
                    score += 1
            if score > 0:
                scored.append((score, note.get("note_index", 0), note))

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [note for _, _, note in scored[:limit]]

    def _summarize_tool_history_item(self, item, *, older):
        name = item.get("name", "unknown_tool")
        args = item.get("args", {}) or {}
        meta = item.get("metadata", {}) or {}

        if name == "read_file":
            path = args.get("path", "?")
            start = args.get("start")
            end = args.get("end")
            range_text = ""
            if start is not None or end is not None:
                range_text = " start=" + str(start) + " end=" + str(end)
            return "read_file path=" + str(path) + range_text

        if name == "write_file":
            return "write_file path=" + str(args.get("path", "?"))

        if name == "patch_file":
            return "patch_file path=" + str(args.get("path", "?"))

        if name == "run_command":
            argv = args.get("argv", [])
            if isinstance(argv, list):
                argv_text = " ".join(str(part) for part in argv[:4])
            else:
                argv_text = str(argv)
            status = " exit_code=" + str(meta.get("exit_code")) if "exit_code" in meta else ""
            if meta.get("timed_out"):
                status += " timed_out=True"
            return "run_command argv=" + _clip_with_marker(argv_text, OLDER_TOOL_LIMIT) + status

        return name + " args=" + _clip_with_marker(str(args), OLDER_TOOL_LIMIT)

    def _select_older_history(self, older_history):
        selected = []
        read_seen = set()
        read_counts_by_file = {}
        read_entries = 0

        for item in older_history:
            if item.get("role") == "tool" and item.get("name") == "read_file":
                args = item.get("args", {}) or {}
                path = str(args.get("path", "?"))
                key = (path, args.get("start"), args.get("end"))
                if key in read_seen:
                    continue
                if read_counts_by_file.get(path, 0) >= MAX_OLDER_READ_RANGES_PER_FILE:
                    continue
                if read_entries >= MAX_OLDER_READ_FILE_ENTRIES:
                    continue
                read_seen.add(key)
                read_counts_by_file[path] = read_counts_by_file.get(path, 0) + 1
                read_entries += 1
            selected.append(item)
        return selected, read_entries

    def _history_text(self, history):
        if not history:
            return "Recent history:\n(empty)", 0, 0

        older = history[:-RECENT_WINDOW]
        recent = history[-RECENT_WINDOW:]
        selected_older, older_read_file_entries_used = self._select_older_history(older)
        lines = []

        if selected_older:
            lines.append("Older history summary:")
            for item in selected_older:
                role = item.get("role", "unknown")
                if role == "tool":
                    lines.append("- tool: " + self._summarize_tool_history_item(item, older=True))
                else:
                    content = _clip_with_marker(item.get("content", ""), OLDER_MSG_LIMIT)
                    lines.append("- " + role + ": " + content)

        lines.append("Recent history:")
        if not recent:
            lines.append("(empty)")
        for item in recent:
            role = item.get("role", "unknown")
            if role == "tool":
                summary = self._summarize_tool_history_item(item, older=False)
                content = _clip_with_marker(item.get("content", ""), RECENT_ITEM_LIMIT)
                if content:
                    lines.append("Tool result from " + str(item.get("name")) + ": " + summary + " -> " + content)
                else:
                    lines.append("Tool result from " + str(item.get("name")) + ": " + summary)
            else:
                content = _clip_with_marker(item.get("content", ""), RECENT_ITEM_LIMIT)
                lines.append(role + ": " + content)

        return "\n".join(lines), len(selected_older), older_read_file_entries_used

    def _clip_section(self, section_name, text, budget, sections_truncated):
        if not text or len(text) <= budget:
            return text
        floor = self.section_floors.get(section_name, 0)
        limit = max(floor, budget)
        if section_name == "history":
            clipped = self._clip_history_section(text, limit)
        else:
            clipped = _clip_with_marker(text, limit)
        if section_name not in sections_truncated:
            sections_truncated.append(section_name)
        return clipped

    def _clip_history_section(self, text, limit):
        marker = "\nRecent history:\n"
        split_at = text.find(marker)
        if split_at == -1:
            return _clip_with_marker(text, limit)

        older_text = text[:split_at]
        recent_text = text[split_at + 1:]
        if len(recent_text) >= limit:
            return self._clip_recent_history_block(recent_text, limit)

        older_limit = limit - len(recent_text) - 1
        if older_limit <= 0:
            return recent_text
        older_clipped = _clip_with_marker(older_text, older_limit)
        if not older_clipped:
            return recent_text
        return older_clipped + "\n" + recent_text

    def _clip_recent_history_block(self, text, limit):
        header = "Recent history:\n"
        if len(text) <= limit:
            return text
        if not text.startswith(header):
            return _clip_with_marker(text, limit)
        marker = "... [truncated]\n"
        body_limit = limit - len(header) - len(marker)
        if body_limit <= 0:
            return _clip_with_marker(text, limit)
        return header + marker + text[-body_limit:]

    def _effective_section_budgets(self, section_texts, current_request_text):
        budgets = dict(self.section_budgets)
        fixed_total = len(current_request_text)
        total = fixed_total + sum(len(section_texts.get(name, "")) for name in budgets)
        overflow = max(0, total - self.total_budget)

        for name in REDUCTION_ORDER:
            if overflow <= 0:
                break
            current_len = len(section_texts.get(name, ""))
            floor = self.section_floors.get(name, 0)
            current_budget = min(budgets.get(name, current_len), current_len)
            reducible = max(0, current_budget - floor)
            reduction = min(reducible, overflow)
            budgets[name] = current_budget - reduction
            overflow -= reduction

        return budgets

    def _compact_prefix_text(self, *, tool_catalog, approval_policy, workspace_root, budget):
        pb = self.prompt_builder
        compact_catalog = []
        for item in tool_catalog:
            compact_catalog.append({
                **item,
                "description": _clip_with_marker(item.get("description", ""), 60),
                "schema": _clip_with_marker(item.get("schema", ""), 80),
            })
        text = pb.prefix_text(
            tool_catalog=compact_catalog,
            approval_policy=approval_policy,
            workspace_root=workspace_root,
        )
        if len(text) <= budget:
            return text
        required = (
            pb._static_prefix() + "\n" +
            pb._response_contract() + "\n\n" +
            pb._runtime_policy(approval_policy) + "\n" +
            "Available tools:\n" +
            "\n".join("- " + item["name"] for item in compact_catalog) + "\n\n" +
            pb._system_context() + "\n" +
            pb._workspace_context(workspace_root) + "\n" +
            pb._format_reminder()
        )
        return required
