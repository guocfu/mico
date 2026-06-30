"""Tests for ContextManager — Task 2 of Session ContextManager plan."""

import pytest
from mico.context_manager import ContextManager
from mico.memory_store import DurableMemory
from mico.prompt import PromptBuilder, PromptBundle
from mico.memory import SessionMemoryState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_catalog():
    return [
        {
            "name": "list_files",
            "description": "List files in the workspace.",
            "schema": '{"path": "str=."}',
            "requires_approval": False,
            "read_only": True,
            "concurrency_safe": True,
            "max_result_chars": 4000,
            "allowed": True,
            "approval_note": "always allowed",
        },
        {
            "name": "patch_file",
            "description": "Exact text replacement in a file.",
            "schema": '{"path": "str", "old_text": "str", "new_text": "str"}',
            "requires_approval": True,
            "read_only": False,
            "concurrency_safe": False,
            "max_result_chars": 4000,
            "allowed": False,
            "approval_note": "blocked under approval=never",
        },
    ]


def _empty_memory():
    return SessionMemoryState()


def _memory_with_summary():
    sm = SessionMemoryState()
    sm.set_task_summary("Refactor auth module")
    return sm


def _memory_with_files():
    sm = SessionMemoryState()
    sm.set_task_summary("Refactor auth module")
    sm.remember_file("src/auth.py")
    sm.remember_file("src/user.py")
    return sm


def _memory_with_episodic_notes():
    sm = SessionMemoryState()
    sm.set_task_summary("Refactor auth module")
    sm.remember_file("src/auth.py")
    sm.append_episodic_note("auth module uses bcrypt for hashing", tags=["auth", "security"], source="read_file src/auth.py")
    sm.append_episodic_note("user model defines User dataclass", tags=["user", "model"], source="read_file src/user.py")
    sm.append_episodic_note("tests/test_auth.py covers login flow", tags=["test", "auth"], source="read_file tests/test_auth.py")
    return sm


# ---------------------------------------------------------------------------
# Basic construction
# ---------------------------------------------------------------------------

class TestContextManagerConstruction:
    def test_instantiation_with_defaults(self):
        cm = ContextManager(PromptBuilder())
        assert cm.prompt_builder is not None
        assert cm.total_budget == 10000
        assert "prefix" in cm.section_budgets
        assert "history" in cm.section_budgets
        assert cm.section_floors["prefix"] == 1400

    def test_instantiation_with_custom_budget(self):
        cm = ContextManager(PromptBuilder(), total_budget=5000, section_budgets={"prefix": 2000})
        assert cm.total_budget == 5000
        assert cm.section_budgets["prefix"] == 2000
        assert "history" in cm.section_budgets


# ---------------------------------------------------------------------------
# build() returns PromptBundle
# ---------------------------------------------------------------------------

class TestContextManagerBuildReturnsBundle:
    def test_returns_prompt_bundle(self):
        cm = ContextManager(PromptBuilder())
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="hello",
            history=[],
            session_memory=_empty_memory(),
        )
        assert isinstance(bundle, PromptBundle)
        assert isinstance(bundle.text, str)
        assert isinstance(bundle.metadata, dict)


# ---------------------------------------------------------------------------
# Section order and content
# ---------------------------------------------------------------------------

class TestContextManagerSectionOrder:
    def test_current_request_is_last_section(self):
        cm = ContextManager(PromptBuilder())
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="inspect files",
            history=[],
            session_memory=_empty_memory(),
        )
        text = bundle.text.strip()
        assert text.endswith("User request: inspect files")

    def test_prefix_always_present(self):
        cm = ContextManager(PromptBuilder())
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="hello",
            history=[],
            session_memory=_empty_memory(),
        )
        assert "You are mico" in bundle.text

    def test_history_always_present(self):
        cm = ContextManager(PromptBuilder())
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="hello",
            history=[],
            session_memory=_empty_memory(),
        )
        assert "Recent history:" in bundle.text

    def test_current_request_always_present(self):
        cm = ContextManager(PromptBuilder())
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="do something",
            history=[],
            session_memory=_empty_memory(),
        )
        assert "User request: do something" in bundle.text


# ---------------------------------------------------------------------------
# Working memory section
# ---------------------------------------------------------------------------

class TestContextManagerWorkingMemory:
    def test_working_memory_included_when_task_summary_set(self):
        cm = ContextManager(PromptBuilder())
        sm = _memory_with_summary()
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="hello",
            history=[],
            session_memory=sm,
        )
        assert "Working memory:" in bundle.text
        assert "Task: Refactor auth module" in bundle.text

    def test_working_memory_included_when_files_present(self):
        cm = ContextManager(PromptBuilder())
        sm = _memory_with_files()
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="hello",
            history=[],
            session_memory=sm,
        )
        assert "Recent files:" in bundle.text
        assert "src/auth.py" in bundle.text

    def test_working_memory_skipped_when_empty(self):
        cm = ContextManager(PromptBuilder())
        sm = _empty_memory()
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="hello",
            history=[],
            session_memory=sm,
        )
        # Empty memory: task_summary is "" and recent_files is []
        # render_memory_text() still produces "Task: (no task)" but we skip it
        # because neither task_summary nor recent_files is non-empty
        assert "Task: (no task)" not in bundle.text


# ---------------------------------------------------------------------------
# Episodic notes retrieval
# ---------------------------------------------------------------------------

class TestContextManagerEpisodicNotes:
    def test_episodic_notes_retrieved_by_keyword(self):
        cm = ContextManager(PromptBuilder())
        sm = _memory_with_episodic_notes()
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="refactor the auth module",
            history=[],
            session_memory=sm,
        )
        assert "Relevant memory:" in bundle.text
        assert "auth" in bundle.text.lower()

    def test_episodic_notes_not_shown_when_no_match(self):
        cm = ContextManager(PromptBuilder())
        sm = _memory_with_episodic_notes()
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="xyzzy nothing matches",
            history=[],
            session_memory=sm,
        )
        assert "Relevant memory:" not in bundle.text

    def test_episodic_notes_not_shown_when_no_notes_exist(self):
        cm = ContextManager(PromptBuilder())
        sm = _empty_memory()
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="auth",
            history=[],
            session_memory=sm,
        )
        assert "Relevant memory:" not in bundle.text

    def test_episodic_notes_top_3_limit(self):
        cm = ContextManager(PromptBuilder())
        sm = SessionMemoryState()
        sm.set_task_summary("test")
        # Add 5 notes, all matching "auth"
        for i in range(5):
            sm.append_episodic_note(f"auth note {i}", tags=["auth"], source=f"src/file{i}.py")
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="auth",
            history=[],
            session_memory=sm,
        )
        assert "Relevant memory:" in bundle.text
        # Should have at most 3 note lines
        relevant_start = bundle.text.index("Relevant memory:")
        relevant_section = bundle.text[relevant_start:]
        note_lines = [line for line in relevant_section.split("\n") if line.startswith("- ")]
        assert len(note_lines) <= 3

    def test_episodic_notes_scored_by_hit_count(self):
        """Notes with more token matches should appear first."""
        cm = ContextManager(PromptBuilder())
        sm = SessionMemoryState()
        sm.set_task_summary("test")
        # note with 1 match (security tag matches one query token)
        sm.append_episodic_note("user model", tags=["model", "security"], source="src/user.py")
        # note with 2 matches (auth + security in text and tags)
        sm.append_episodic_note("auth security module", tags=["auth", "security"], source="src/auth.py")
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="auth security",
            history=[],
            session_memory=sm,
        )
        assert "Relevant memory:" in bundle.text
        relevant_start = bundle.text.index("Relevant memory:")
        relevant_section = bundle.text[relevant_start:]
        # The 2-match note should come before the 1-match note
        pos_auth = relevant_section.find("auth security module")
        pos_user = relevant_section.find("user model")
        assert pos_auth < pos_user, "Higher-scored note should appear first"


class TestContextManagerDurableMemory:
    def test_memory_index_is_included_before_current_request(self, tmp_path):
        store = DurableMemory(tmp_path / ".mico" / "memory")
        store.remember("preferences", "Prefer pytest for verification.", tags=["testing"])
        cm = ContextManager(PromptBuilder())

        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="use pytest",
            history=[],
            session_memory=_empty_memory(),
            durable_memory=store,
        )

        assert "Memory index:" in bundle.text
        assert bundle.text.index("Memory index:") < bundle.text.index("User request: use pytest")
        assert bundle.text.rstrip().endswith("User request: use pytest")

    def test_relevant_memory_includes_durable_notes(self, tmp_path):
        store = DurableMemory(tmp_path / ".mico" / "memory")
        store.remember("preferences", "Prefer pytest for Python verification.", tags=["testing"])
        cm = ContextManager(PromptBuilder())

        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="python tests",
            history=[],
            session_memory=_empty_memory(),
            durable_memory=store,
        )

        assert "Relevant memory:" in bundle.text
        relevant_start = bundle.text.index("Relevant memory:")
        history_start = bundle.text.index("Recent history:")
        relevant_section = bundle.text[relevant_start:history_start]
        assert "[durable:preferences]" in relevant_section
        assert "Prefer pytest for Python verification." in relevant_section

    def test_durable_memory_metadata_is_reported(self, tmp_path):
        store = DurableMemory(tmp_path / ".mico" / "memory")
        store.remember("preferences", "Prefer pytest for Python verification.", tags=["testing"])
        cm = ContextManager(PromptBuilder())

        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="pytest",
            history=[],
            session_memory=_empty_memory(),
            durable_memory=store,
        )

        assert bundle.metadata["durable_memory_notes_available"] == 1
        assert bundle.metadata["durable_memory_notes_used"] == 1
        assert "memory_index" in bundle.metadata["section_chars"]

    def test_relevant_durable_memory_is_clipped_and_reported(self, tmp_path):
        store = DurableMemory(tmp_path / ".mico" / "memory")
        store.remember("notes", "python " + ("x" * 1000))
        cm = ContextManager(PromptBuilder())

        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="python",
            history=[],
            session_memory=_empty_memory(),
            durable_memory=store,
        )

        assert bundle.metadata["durable_memory_notes_truncated"] == 1
        assert len(bundle.text) < 10000


# ---------------------------------------------------------------------------
# History limiting
# ---------------------------------------------------------------------------

class TestContextManagerHistoryLimiting:
    def test_history_recent_window_and_older_summary(self):
        cm = ContextManager(PromptBuilder())
        history = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="hello",
            history=history,
            session_memory=_empty_memory(),
        )
        # Recent 6 items should be in "Recent history"
        assert "msg9" in bundle.text
        assert "msg4" in bundle.text
        # Older items should appear in "Older history summary"
        assert "Older history summary:" in bundle.text
        assert "msg3" in bundle.text  # older item summarized
        assert bundle.metadata["history_items_compacted"] == 4


class TestContextManagerHistoryGovernance:
    def test_older_write_and_patch_history_redacts_large_args(self):
        cm = ContextManager(PromptBuilder(), total_budget=3200)
        history = [
            {"role": "tool", "name": "write_file", "args": {"path": "src/a.py", "content": "SECRET_CONTENT" * 50}, "content": "wrote", "metadata": {"ok": True}},
            {"role": "tool", "name": "patch_file", "args": {"path": "src/b.py", "old_text": "OLD_SECRET" * 50, "new_text": "NEW_SECRET" * 50}, "content": "patched", "metadata": {"ok": True}},
            {"role": "user", "content": "later user message"},
            {"role": "assistant", "content": "later assistant message"},
            {"role": "user", "content": "recent user message"},
            {"role": "assistant", "content": "recent assistant message"},
            {"role": "tool", "name": "run_command", "args": {"argv": ["python", "-m", "pytest"]}, "content": "ok", "metadata": {"ok": True, "exit_code": 0}},
        ]

        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="continue",
            history=history,
            session_memory=_empty_memory(),
        )

        assert "SECRET_CONTENT" not in bundle.text
        assert "OLD_SECRET" not in bundle.text
        assert "NEW_SECRET" not in bundle.text
        assert "write_file path=src/a.py" in bundle.text
        assert "patch_file path=src/b.py" in bundle.text

    def test_older_read_file_ranges_are_deduplicated_and_limited(self):
        cm = ContextManager(PromptBuilder(), total_budget=3600)
        history = []
        for i in range(10):
            history.append({
                "role": "tool",
                "name": "read_file",
                "args": {"path": "src/large.py", "start": i * 10, "end": i * 10 + 9},
                "content": "line content " + ("x" * 100),
                "metadata": {"ok": True},
            })
        history.extend([
            {"role": "user", "content": "recent user"},
            {"role": "assistant", "content": "recent assistant"},
            {"role": "user", "content": "recent user 2"},
            {"role": "assistant", "content": "recent assistant 2"},
            {"role": "user", "content": "recent user 3"},
            {"role": "assistant", "content": "recent assistant 3"},
        ])

        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="continue",
            history=history,
            session_memory=_empty_memory(),
        )

        assert bundle.text.count("read_file path=src/large.py") <= 3
        assert "line content" not in bundle.text
        assert bundle.metadata["older_read_file_entries_used"] <= 3

    def test_history_compression_preserves_recent_block_over_older_summary(self):
        cm = ContextManager(PromptBuilder(), total_budget=2200)
        history = [
            {"role": "user", "content": f"older-{i} " + ("x" * 300)}
            for i in range(20)
        ]
        history.extend([
            {"role": "user", "content": f"recent-critical-{i}"}
            for i in range(6)
        ])

        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="continue",
            history=history,
            session_memory=_empty_memory(),
        )

        assert "history" in bundle.metadata["sections_truncated"]
        assert "Recent history:" in bundle.text
        assert "recent-critical-5" in bundle.text


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

class TestContextManagerMetadata:
    def test_metadata_fields_present(self):
        cm = ContextManager(PromptBuilder())
        sm = _memory_with_files()
        history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="never",
            workspace_root="/tmp/ws",
            user_message="do something",
            history=history,
            session_memory=sm,
        )
        meta = bundle.metadata
        assert meta["prompt_chars"] == len(bundle.text)
        assert meta["total_budget"] == 10000
        assert isinstance(meta["over_budget"], bool)
        assert meta["history_items_total"] == 2
        assert meta["history_items_used"] == 2
        assert meta["current_request_chars"] == len("do something")
        assert meta["current_request_preserved_rate"] == 1.0

    def test_metadata_section_chars(self):
        cm = ContextManager(PromptBuilder())
        sm = _memory_with_files()
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="hello",
            history=[],
            session_memory=sm,
        )
        meta = bundle.metadata
        section_chars = meta["section_chars"]
        assert "prefix" in section_chars
        assert "working_memory" in section_chars
        assert "relevant_memory" in section_chars
        assert "history" in section_chars
        assert "current_request" in section_chars
        # Sum of sections should equal total prompt_chars (plus newlines between sections)
        # Since we join with "\n", the total should be at least sum of sections
        total_section_chars = sum(section_chars.values())
        assert meta["prompt_chars"] >= total_section_chars

    def test_metadata_episodic_notes_available_and_used(self):
        cm = ContextManager(PromptBuilder())
        sm = _memory_with_episodic_notes()
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="auth",
            history=[],
            session_memory=sm,
        )
        meta = bundle.metadata
        assert meta["episodic_notes_available"] == 3
        assert meta["episodic_notes_used"] >= 1
        assert meta["episodic_notes_used"] <= 3

    def test_metadata_episodic_notes_used_zero_when_no_match(self):
        cm = ContextManager(PromptBuilder())
        sm = _memory_with_episodic_notes()
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="xyzzy nothing",
            history=[],
            session_memory=sm,
        )
        meta = bundle.metadata
        assert meta["episodic_notes_available"] == 3
        assert meta["episodic_notes_used"] == 0

    def test_over_budget_false_when_under(self):
        cm = ContextManager(PromptBuilder(), total_budget=100000)
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="hello",
            history=[],
            session_memory=_empty_memory(),
        )
        assert bundle.metadata["over_budget"] is False

    def test_over_budget_true_when_exceeded(self):
        cm = ContextManager(PromptBuilder(), total_budget=10)
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="hello",
            history=[],
            session_memory=_empty_memory(),
        )
        assert bundle.metadata["over_budget"] is True

    def test_budget_metadata_reports_original_and_final_section_chars(self):
        cm = ContextManager(PromptBuilder(), total_budget=1200)
        sm = SessionMemoryState()
        sm.set_task_summary("Refactor auth module")
        sm.remember_file("src/auth.py")
        sm.record_file_summary("src/auth.py", "auth summary " + ("x" * 400))
        history = [{"role": "user", "content": "msg " + ("y" * 400)} for _ in range(8)]

        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="keep this current request intact",
            history=history,
            session_memory=sm,
        )

        meta = bundle.metadata
        assert "section_chars_original" in meta
        assert "section_budgets" in meta
        assert "section_floors" in meta
        assert "sections_truncated" in meta
        assert isinstance(meta["sections_truncated"], list)
        assert meta["current_request_preserved_rate"] == 1.0
        assert bundle.text.rstrip().endswith("User request: keep this current request intact")

    def test_current_request_preserved_when_budget_tiny(self):
        cm = ContextManager(PromptBuilder(), total_budget=500)
        history = [{"role": "user", "content": "old " + ("x" * 1000)} for _ in range(20)]
        sm = SessionMemoryState()
        sm.set_task_summary("summary " + ("y" * 1000))
        sm.remember_file("src/a.py")
        sm.record_file_summary("src/a.py", "file summary " + ("z" * 1000))

        request = "this exact current request must be preserved"
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message=request,
            history=history,
            session_memory=sm,
        )

        assert bundle.text.rstrip().endswith("User request: " + request)
        assert bundle.metadata["current_request_preserved_rate"] == 1.0

    def test_budget_reduces_history_before_memory_sections(self):
        cm = ContextManager(PromptBuilder(), total_budget=2500)
        sm = SessionMemoryState()
        sm.set_task_summary("important working memory")
        sm.remember_file("src/auth.py")
        sm.record_file_summary("src/auth.py", "important file summary")
        history = [{"role": "user", "content": "old " + ("x" * 500)} for _ in range(20)]

        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="continue",
            history=history,
            session_memory=sm,
        )

        assert "Working memory:" in bundle.text
        assert "important working memory" in bundle.text
        assert "history" in bundle.metadata["sections_truncated"]

    def test_prefix_compaction_keeps_response_contract(self):
        large_catalog = []
        for i in range(40):
            large_catalog.append({
                "name": f"tool_{i}",
                "description": "description " + ("x" * 200),
                "schema": '{"path": "str"}',
                "requires_approval": False,
                "read_only": True,
                "concurrency_safe": True,
                "max_result_chars": 4000,
                "allowed": True,
                "approval_note": "always allowed",
            })
        cm = ContextManager(PromptBuilder(), total_budget=1800)

        bundle = cm.build(
            tool_catalog=large_catalog,
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="continue",
            history=[],
            session_memory=_empty_memory(),
        )

        assert "Respond with exactly one XML block per turn:" in bundle.text
        assert "Reminder: respond with exactly one <tool> or <final> block." in bundle.text
        assert bundle.text.rstrip().endswith("User request: continue")


# ---------------------------------------------------------------------------
# _retrieve_episodic_notes (unit tests for the retrieval algorithm)
# ---------------------------------------------------------------------------

class TestRetrieveEpisodicNotes:
    def test_empty_notes_returns_empty(self):
        cm = ContextManager(PromptBuilder())
        sm = _empty_memory()
        notes = cm._retrieve_episodic_notes(sm, "auth", limit=3)
        assert notes == []

    def test_no_matching_tokens_returns_empty(self):
        cm = ContextManager(PromptBuilder())
        sm = _memory_with_episodic_notes()
        notes = cm._retrieve_episodic_notes(sm, "xyzzy nothing matches", limit=3)
        assert notes == []

    def test_matching_token_returns_notes(self):
        cm = ContextManager(PromptBuilder())
        sm = _memory_with_episodic_notes()
        notes = cm._retrieve_episodic_notes(sm, "auth", limit=3)
        assert len(notes) >= 1
        assert any("auth" in n["text"].lower() for n in notes)

    def test_limit_applied(self):
        cm = ContextManager(PromptBuilder())
        sm = SessionMemoryState()
        sm.set_task_summary("test")
        for i in range(5):
            sm.append_episodic_note(f"auth note {i}", tags=["auth"], source=f"src/file{i}.py")
        notes = cm._retrieve_episodic_notes(sm, "auth", limit=3)
        assert len(notes) == 3

    def test_scoring_prefers_more_matches(self):
        cm = ContextManager(PromptBuilder())
        sm = SessionMemoryState()
        sm.set_task_summary("test")
        sm.append_episodic_note("user model", tags=["model", "security"], source="src/user.py")
        sm.append_episodic_note("auth security", tags=["auth", "security"], source="src/auth.py")
        notes = cm._retrieve_episodic_notes(sm, "auth security", limit=3)
        assert len(notes) == 2
        # The 2-match note should come first
        assert "auth security" in notes[0]["text"]

    def test_case_insensitive_matching(self):
        cm = ContextManager(PromptBuilder())
        sm = SessionMemoryState()
        sm.set_task_summary("test")
        sm.append_episodic_note("AUTH module uses Bcrypt", tags=["AUTH"], source="src/Auth.py")
        notes = cm._retrieve_episodic_notes(sm, "auth", limit=3)
        assert len(notes) == 1

    def test_tag_matching(self):
        cm = ContextManager(PromptBuilder())
        sm = SessionMemoryState()
        sm.set_task_summary("test")
        sm.append_episodic_note("some text about models", tags=["auth", "models"], source="src/models.py")
        notes = cm._retrieve_episodic_notes(sm, "auth", limit=3)
        assert len(notes) == 1

    def test_source_matching(self):
        cm = ContextManager(PromptBuilder())
        sm = SessionMemoryState()
        sm.set_task_summary("test")
        sm.append_episodic_note("some unrelated text", tags=[], source="read_file src/auth.py")
        notes = cm._retrieve_episodic_notes(sm, "auth", limit=3)
        assert len(notes) == 1


# ---------------------------------------------------------------------------
# Checkpoint section (Task 3)
# ---------------------------------------------------------------------------

class TestContextManagerCheckpoint:
    def test_checkpoint_text_before_working_memory(self):
        cm = ContextManager(PromptBuilder())
        sm = _memory_with_summary()
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="hello",
            history=[],
            session_memory=sm,
            checkpoint_text="Task checkpoint:\n  goal: build login\n",
        )
        text = bundle.text
        cp_pos = text.find("Task checkpoint:")
        wm_pos = text.find("Working memory:")
        assert cp_pos >= 0
        assert wm_pos >= 0
        assert cp_pos < wm_pos

    def test_checkpoint_metadata_present(self):
        cm = ContextManager(PromptBuilder())
        sm = _memory_with_summary()
        resume_state = {
            "status": "partial-stale",
            "stale_paths": ["src/a.py"],
            "runtime_identity_mismatch_fields": [],
        }
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="hello",
            history=[],
            session_memory=sm,
            checkpoint_text="Task checkpoint:\n  stale\n",
            resume_state=resume_state,
        )
        meta = bundle.metadata
        assert meta["resume_status"] == "partial-stale"
        assert meta["checkpoint_chars"] > 0
        assert "src/a.py" in meta["stale_paths"]
        assert meta["runtime_identity_mismatch_fields"] == []

    def test_current_request_still_last_with_checkpoint(self):
        cm = ContextManager(PromptBuilder())
        sm = _memory_with_summary()
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="do stuff",
            history=[],
            session_memory=sm,
            checkpoint_text="Task checkpoint:\n",
        )
        assert bundle.text.strip().endswith("User request: do stuff")

    def test_no_checkpoint_text_means_no_checkpoint_section(self):
        cm = ContextManager(PromptBuilder())
        sm = _memory_with_summary()
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="hello",
            history=[],
            session_memory=sm,
        )
        assert "Task checkpoint:" not in bundle.text
        assert bundle.metadata.get("resume_status", "no-checkpoint") == "no-checkpoint"

    def test_tiny_budget_truncates_checkpoint_not_current_request(self):
        cm = ContextManager(PromptBuilder(), total_budget=500, section_budgets={
            "prefix": 100,
            "memory_index": 10,
            "checkpoint": 50,
            "working_memory": 10,
            "relevant_memory": 10,
            "history": 10,
        })
        sm = _memory_with_summary()
        long_checkpoint = "Task checkpoint:\n" + "  detail: " + "x" * 500 + "\n"
        bundle = cm.build(
            tool_catalog=_sample_catalog(),
            approval_policy="auto",
            workspace_root="/tmp/ws",
            user_message="my request",
            history=[],
            session_memory=sm,
            checkpoint_text=long_checkpoint,
        )
        assert bundle.text.strip().endswith("User request: my request")
