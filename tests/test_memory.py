from mico.memory import SessionMemoryState


def test_default_state_has_empty_fields():
    state = SessionMemoryState()
    assert state.task_summary == ""
    assert state.recent_files == []
    assert state.file_summaries == {}
    assert state.episodic_notes == []


def test_set_task_summary():
    state = SessionMemoryState()
    state.set_task_summary("fix auth bug")
    assert state.task_summary == "fix auth bug"


def test_set_task_summary_truncates():
    state = SessionMemoryState()
    long = "x" * 500
    state.set_task_summary(long)
    assert len(state.task_summary) == 300


def test_remember_file_adds_to_recent():
    state = SessionMemoryState()
    state.remember_file("src/main.py")
    assert state.recent_files == ["src/main.py"]


def test_remember_file_deduplicates():
    state = SessionMemoryState()
    state.remember_file("a.py")
    state.remember_file("b.py")
    state.remember_file("a.py")
    assert state.recent_files == ["b.py", "a.py"]


def test_remember_file_respects_limit():
    state = SessionMemoryState()
    for i in range(12):
        state.remember_file(f"file_{i}.py")
    assert len(state.recent_files) == 8
    assert state.recent_files[0] == "file_4.py"
    assert state.recent_files[-1] == "file_11.py"


def test_remember_file_normalizes_to_posix():
    state = SessionMemoryState()
    state.remember_file("src\\main.py")
    assert state.recent_files == ["src/main.py"]


def test_record_file_summary():
    state = SessionMemoryState()
    state.record_file_summary("main.py", "FastAPI app entry", freshness="abc123")
    assert "main.py" in state.file_summaries
    entry = state.file_summaries["main.py"]
    assert entry["summary"] == "FastAPI app entry"
    assert entry["freshness"] == "abc123"


def test_invalidate_file_removes_summary():
    state = SessionMemoryState()
    state.record_file_summary("main.py", "some summary", freshness="x")
    state.invalidate_file("main.py")
    assert "main.py" not in state.file_summaries


def test_invalidate_file_re_adds_to_recent():
    state = SessionMemoryState()
    state.remember_file("old.py")
    state.invalidate_file("main.py")
    assert state.recent_files[-1] == "main.py"


def test_append_episodic_note():
    state = SessionMemoryState()
    state.append_episodic_note("read main.py", tags=["file", "py"], source="read_file:main.py")
    assert len(state.episodic_notes) == 1
    note = state.episodic_notes[0]
    assert note["text"] == "read main.py"
    assert note["tags"] == ["file", "py"]
    assert note["source"] == "read_file:main.py"
    assert "created_at" in note
    assert note["note_index"] == 0


def test_episodic_notes_fifo_limit():
    state = SessionMemoryState()
    for i in range(20):
        state.append_episodic_note(f"note {i}", tags=[], source="test")
    assert len(state.episodic_notes) == 15
    assert state.episodic_notes[0]["text"] == "note 5"
    assert state.episodic_notes[-1]["text"] == "note 19"


def test_episodic_notes_index_monotonic():
    state = SessionMemoryState()
    for i in range(20):
        state.append_episodic_note(f"note {i}", tags=[], source="test")
    indices = [n["note_index"] for n in state.episodic_notes]
    assert indices == list(range(5, 20))


def test_episodic_notes_dedup_same_text():
    state = SessionMemoryState()
    state.append_episodic_note("same text", tags=["a"], source="x")
    state.append_episodic_note("same text", tags=["b"], source="y")
    assert len(state.episodic_notes) == 1
    assert state.episodic_notes[0]["tags"] == ["b"]
    assert state.episodic_notes[0]["note_index"] == 1


def test_to_dict_and_from_dict_roundtrip():
    state = SessionMemoryState()
    state.set_task_summary("test task")
    state.remember_file("a.py")
    state.record_file_summary("a.py", "file A", freshness="f1")
    state.append_episodic_note("note 1", tags=["t"], source="s")
    d = state.to_dict()
    restored = SessionMemoryState.from_dict(d)
    assert restored.task_summary == "test task"
    assert restored.recent_files == ["a.py"]
    assert restored.file_summaries["a.py"]["summary"] == "file A"
    assert len(restored.episodic_notes) == 1
    assert restored.episodic_notes[0]["text"] == "note 1"


def test_from_dict_with_missing_fields():
    state = SessionMemoryState.from_dict({})
    assert state.task_summary == ""
    assert state.recent_files == []
    assert state.file_summaries == {}
    assert state.episodic_notes == []


def test_from_dict_with_none():
    state = SessionMemoryState.from_dict(None)
    assert state.task_summary == ""


def test_from_dict_with_invalid_note_index_uses_default():
    state = SessionMemoryState.from_dict({"next_note_index": "not-a-number"})

    assert state.next_note_index == 0


def test_render_memory_text_empty():
    state = SessionMemoryState()
    text = state.render_memory_text()
    assert "(no task)" in text


def test_render_memory_text_with_content():
    state = SessionMemoryState()
    state.set_task_summary("fix auth")
    state.remember_file("main.py")
    state.record_file_summary("main.py", "FastAPI entry", freshness="f")
    text = state.render_memory_text()
    assert "fix auth" in text
    assert "main.py" in text
    assert "FastAPI entry" in text
