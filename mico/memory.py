import time
from pathlib import Path

WORKING_FILE_LIMIT = 8
TASK_SUMMARY_LIMIT = 300
FILE_SUMMARY_LIMIT = 6
EPISODIC_NOTE_LIMIT = 15
NOTE_TEXT_LIMIT = 500


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _posix_rel(path_str):
    return Path(path_str.replace(chr(92), chr(47))).as_posix()


class SessionMemoryState:
    def __init__(self):
        self.task_summary = ""
        self.recent_files = []
        self.file_summaries = {}
        self.episodic_notes = []
        self.next_note_index = 0
        self.updated_at = _now_iso()

    def set_task_summary(self, text):
        if len(text) > TASK_SUMMARY_LIMIT:
            text = text[:TASK_SUMMARY_LIMIT]
        self.task_summary = text
        self.updated_at = _now_iso()

    def remember_file(self, path_str):
        rel = _posix_rel(path_str)
        if rel in self.recent_files:
            self.recent_files.remove(rel)
        self.recent_files.append(rel)
        if len(self.recent_files) > WORKING_FILE_LIMIT:
            self.recent_files = self.recent_files[-WORKING_FILE_LIMIT:]
        self.updated_at = _now_iso()

    def record_file_summary(self, path_str, summary, freshness=None):
        rel = _posix_rel(path_str)
        if len(summary) > NOTE_TEXT_LIMIT:
            summary = summary[:NOTE_TEXT_LIMIT]
        self.file_summaries[rel] = {
            "summary": summary,
            "freshness": freshness,
            "updated_at": _now_iso(),
        }
        self.updated_at = _now_iso()

    def invalidate_file(self, path_str):
        rel = _posix_rel(path_str)
        self.file_summaries.pop(rel, None)
        self.remember_file(rel)
        self.updated_at = _now_iso()

    def append_episodic_note(self, text, tags=None, source=""):
        if tags is None:
            tags = []
        if len(text) > NOTE_TEXT_LIMIT:
            text = text[:NOTE_TEXT_LIMIT]
        self.episodic_notes = [n for n in self.episodic_notes if n["text"] != text]
        note = {
            "text": text,
            "tags": list(tags),
            "source": source,
            "created_at": _now_iso(),
            "note_index": self.next_note_index,
        }
        self.next_note_index += 1
        self.episodic_notes.append(note)
        if len(self.episodic_notes) > EPISODIC_NOTE_LIMIT:
            self.episodic_notes = self.episodic_notes[-EPISODIC_NOTE_LIMIT:]
        self.updated_at = _now_iso()

    def render_memory_text(self):
        parts = []
        parts.append("Task: " + (self.task_summary or "(no task)"))
        if self.recent_files:
            parts.append("Recent files: " + ", ".join(self.recent_files))
        summaries = []
        for path in self.recent_files[:FILE_SUMMARY_LIMIT]:
            entry = self.file_summaries.get(path)
            if entry:
                summaries.append("  - " + path + " -> " + entry["summary"])
        if summaries:
            parts.append("File summaries:")
            parts.extend(summaries)
        return chr(10).join(parts)

    def to_dict(self):
        return {
            "task_summary": self.task_summary,
            "recent_files": list(self.recent_files),
            "file_summaries": dict(self.file_summaries),
            "episodic_notes": list(self.episodic_notes),
            "next_note_index": self.next_note_index,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data):
        state = cls()
        if not isinstance(data, dict):
            return state
        state.task_summary = str(data.get("task_summary", ""))
        state.recent_files = list(data.get("recent_files", []))
        state.file_summaries = dict(data.get("file_summaries", {}))
        state.episodic_notes = list(data.get("episodic_notes", []))
        try:
            state.next_note_index = int(data.get("next_note_index", 0))
        except (TypeError, ValueError):
            state.next_note_index = 0
        state.updated_at = str(data.get("updated_at", _now_iso()))
        return state
