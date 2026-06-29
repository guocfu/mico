"""ContextManager assembles prompt sections from PromptBuilder and SessionMemoryState."""

import re

from mico.prompt import PromptBuilder, PromptBundle
from mico.memory import SessionMemoryState

MAX_HISTORY_ITEMS = 6
DEFAULT_TOTAL_BUDGET = 10000


class ContextManager:
    """Assembles a full prompt from prefix, working memory, episodic notes, history,
    and current request sections.

    Budget v1: tracks over_budget flag only, no compression.
    """

    def __init__(self, prompt_builder, total_budget=DEFAULT_TOTAL_BUDGET, section_budgets=None):
        self.prompt_builder = prompt_builder
        self.total_budget = total_budget
        self.section_budgets = section_budgets or {}

    def build(self, *, tool_catalog, approval_policy, workspace_root,
              user_message, history, session_memory):
        """Assemble all prompt sections and return a PromptBundle with metadata."""
        # 1. Prefix — always included
        prefix = self.prompt_builder.prefix_text(
            tool_catalog=tool_catalog,
            approval_policy=approval_policy,
            workspace_root=workspace_root,
        )

        # 2. Working memory — only if task_summary or recent_files present
        if session_memory.task_summary or session_memory.recent_files:
            working_memory_text = "Working memory:\n" + session_memory.render_memory_text()
        else:
            working_memory_text = ""

        # 3. Relevant memory (episodic notes) — only if retrieval returns matches
        retrieved_notes = self._retrieve_episodic_notes(session_memory, user_message, limit=3)
        if retrieved_notes:
            relevant_memory_text = "Relevant memory:\n" + "\n".join(
                "- " + note["text"] for note in retrieved_notes
            )
        else:
            relevant_memory_text = ""

        # 4. History — always included
        recent_history = history[-MAX_HISTORY_ITEMS:]
        history_text = self.prompt_builder.history_text(recent_history)

        # 5. Current request — always included, always last
        current_request_text = self.prompt_builder.current_request_text(user_message)

        # Concatenate all non-empty sections with newlines
        sections = [prefix, working_memory_text, relevant_memory_text, history_text, current_request_text]
        non_empty = [s for s in sections if s]
        text = "\n".join(non_empty) + "\n"

        # Metadata
        tool_count = len(tool_catalog)
        restricted_tool_count = sum(1 for t in tool_catalog if not t["allowed"])

        metadata = {
            "prompt_chars": len(text),
            "total_budget": self.total_budget,
            "over_budget": len(text) > self.total_budget,
            "section_chars": {
                "prefix": len(prefix),
                "working_memory": len(working_memory_text),
                "relevant_memory": len(relevant_memory_text),
                "history": len(history_text),
                "current_request": len(current_request_text),
            },
            "history_items_total": len(history),
            "history_items_used": len(recent_history),
            "tool_count": tool_count,
            "restricted_tool_count": restricted_tool_count,
            "approval_policy": approval_policy,
            "episodic_notes_available": len(session_memory.episodic_notes),
            "episodic_notes_used": len(retrieved_notes),
            "current_request_chars": len(user_message),
            "current_request_preserved_rate": 1.0,
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
