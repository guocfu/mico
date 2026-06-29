import pytest

from mico.memory_store import DurableMemory


def test_durable_memory_initializes_index_and_topic_files(tmp_path):
    store = DurableMemory(tmp_path / ".mico" / "memory")

    assert (tmp_path / ".mico" / "memory" / "MEMORY.md").exists()
    for topic in DurableMemory.TOPICS:
        assert (tmp_path / ".mico" / "memory" / f"{topic}.md").exists()


def test_remember_appends_note_and_updates_index(tmp_path):
    store = DurableMemory(tmp_path / ".mico" / "memory")

    result = store.remember(
        "preferences",
        "Prefer pytest for verification.",
        tags=["testing", "python"],
    )

    assert result["topic"] == "preferences"
    topic_text = (tmp_path / ".mico" / "memory" / "preferences.md").read_text(encoding="utf-8")
    index_text = (tmp_path / ".mico" / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    assert "Prefer pytest for verification." in topic_text
    assert '"tags":["testing","python"]' in topic_text
    assert "preferences" in index_text
    assert "Prefer pytest for verification." in index_text


def test_remember_rejects_invalid_topic(tmp_path):
    store = DurableMemory(tmp_path / ".mico" / "memory")

    with pytest.raises(ValueError, match="Invalid topic"):
        store.remember("../../../outside", "bad")


def test_remember_rejects_empty_note(tmp_path):
    store = DurableMemory(tmp_path / ".mico" / "memory")

    with pytest.raises(ValueError, match="note"):
        store.remember("notes", "   ")


def test_remember_rejects_invalid_tags(tmp_path):
    store = DurableMemory(tmp_path / ".mico" / "memory")

    with pytest.raises(ValueError, match="tags"):
        store.remember("notes", "hello", tags=["ok", 1])


def test_retrieve_returns_relevant_notes(tmp_path):
    store = DurableMemory(tmp_path / ".mico" / "memory")
    store.remember("preferences", "Prefer pytest for Python verification.", tags=["testing"])
    store.remember("projects", "Mico durable memory lives under .mico/memory.", tags=["mico"])

    notes = store.retrieve("How should mico run python tests?", limit=3)

    assert any(note["topic"] == "preferences" for note in notes)
    assert any("pytest" in note["text"] for note in notes)


def test_render_index_is_prompt_safe_and_limited(tmp_path):
    store = DurableMemory(tmp_path / ".mico" / "memory")
    store.remember("notes", "x" * 500)

    rendered = store.render_index(max_chars=120)

    assert rendered.startswith("# Durable Memory Index")
    assert len(rendered) <= 120


def test_retrieve_matches_chinese_query_and_note(tmp_path):
    store = DurableMemory(tmp_path / ".mico" / "memory")
    store.remember("preferences", "默认使用中文回复，解释要简洁。", tags=["中文"])

    notes = store.retrieve("请用中文回复", limit=3)

    assert len(notes) >= 1
    assert notes[0]["topic"] == "preferences"
    assert "中文回复" in notes[0]["text"]


def test_note_text_can_contain_note_heading_without_splitting(tmp_path):
    store = DurableMemory(tmp_path / ".mico" / "memory")
    store.remember("notes", "first line\n## Note\nthis is user text")
    store.remember("notes", "second real note")

    notes = store.read_topic("notes")

    assert len(notes) == 2
    assert notes[0]["text"] == "first line\n## Note\nthis is user text"
    assert notes[1]["text"] == "second real note"


def test_remember_truncates_overlong_note(tmp_path):
    store = DurableMemory(tmp_path / ".mico" / "memory")
    result = store.remember("notes", "x" * 2500)

    notes = store.read_topic("notes")

    assert result["truncated"] is True
    assert len(result["note"]) == 2000
    assert len(notes[0]["text"]) == 2000
    assert notes[0]["truncated"] is True


def test_retrieve_clips_note_text_for_prompt(tmp_path):
    store = DurableMemory(tmp_path / ".mico" / "memory")
    store.remember("notes", "python " + ("x" * 1000))

    notes = store.retrieve("python", limit=1, max_text_chars=120)

    assert len(notes[0]["text"]) == 120
    assert notes[0]["text"].endswith("...")
    assert notes[0]["truncated"] is True
