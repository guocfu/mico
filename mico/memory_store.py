"""Cross-session durable memory backed by .mico/memory markdown files."""

import re
import time
from pathlib import Path


TOPICS = ("profile", "projects", "preferences", "decisions", "conventions", "notes")


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _invalid_topic_message(topic):
    return f"Invalid topic {topic!r}. Must be one of: {', '.join(TOPICS)}"


class DurableMemory:
    """Persistent memory that survives across sessions."""

    TOPICS = TOPICS

    def __init__(self, memory_dir):
        self.memory_dir = Path(memory_dir).resolve()
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_files()

    def _ensure_files(self):
        index_path = self.memory_dir / "MEMORY.md"
        if not index_path.exists():
            index_path.write_text("# Durable Memory Index\n", encoding="utf-8")
        for topic in self.TOPICS:
            topic_path = self.memory_dir / f"{topic}.md"
            if not topic_path.exists():
                topic_path.write_text(f"# {topic}\n", encoding="utf-8")

    def remember(self, topic, note, tags=None):
        if topic not in self.TOPICS:
            raise ValueError(_invalid_topic_message(topic))
        if not isinstance(note, str) or not note.strip():
            raise ValueError("note must be a non-empty string")
        if tags is not None:
            if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
                raise ValueError("tags must be None or a list of strings")

        created_at = _now_iso()
        tags_list = list(tags or [])
        entry = {
            "created_at": created_at,
            "tags": tags_list,
            "text": note.strip(),
        }

        topic_path = self.memory_dir / f"{topic}.md"
        notes = self._read_notes_from_file(topic_path)
        notes.append(entry)
        self._write_notes_to_file(topic_path, topic, notes)
        self._update_index()

        return {
            "topic": topic,
            "note": entry["text"],
            "tags": tags_list,
            "created_at": created_at,
        }

    def render_index(self, max_chars=2000):
        index_path = self.memory_dir / "MEMORY.md"
        if not index_path.exists():
            return ""
        content = index_path.read_text(encoding="utf-8")
        if not re.search(r"^## ", content, re.MULTILINE):
            return ""
        return content[:max_chars]

    def retrieve(self, query, limit=3):
        query_tokens = set(re.findall(r"[A-Za-z0-9_]+", str(query).lower()))
        if not query_tokens:
            return []

        scored = []
        for topic in self.TOPICS:
            for note in self.read_topic(topic):
                score = 0
                text_lower = note.get("text", "").lower()
                tags_set = {tag.lower() for tag in note.get("tags", [])}
                for token in query_tokens:
                    if token == topic:
                        score += 2
                    if token in text_lower or token in tags_set:
                        score += 1
                if score > 0:
                    scored.append((score, note.get("created_at", ""), topic, note))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [
            {
                "topic": topic,
                "text": note.get("text", ""),
                "tags": note.get("tags", []),
                "created_at": note.get("created_at", ""),
            }
            for _, _, topic, note in scored[:limit]
        ]

    def count_notes(self):
        return sum(len(self.read_topic(topic)) for topic in self.TOPICS)

    def read_topic(self, topic):
        if topic not in self.TOPICS:
            raise ValueError(_invalid_topic_message(topic))
        return self._read_notes_from_file(self.memory_dir / f"{topic}.md")

    def _read_notes_from_file(self, filepath):
        if not filepath.exists():
            return []
        content = filepath.read_text(encoding="utf-8")
        if not content.strip():
            return []

        notes = []
        blocks = re.split(r"^## Note\s*$", content, flags=re.MULTILINE)
        for block in blocks:
            block = block.strip()
            if not block or block.startswith("# "):
                continue

            created_at = ""
            tags = []
            text_lines = []
            in_metadata = True
            for line in block.splitlines():
                stripped = line.strip()
                if in_metadata and stripped.startswith("- created_at:"):
                    created_at = stripped.split(":", 1)[1].strip()
                    continue
                if in_metadata and stripped.startswith("- tags:"):
                    tag_text = stripped.split(":", 1)[1].strip()
                    tags = [tag.strip() for tag in tag_text.split(",") if tag.strip()]
                    continue
                if in_metadata and stripped == "":
                    in_metadata = False
                    continue
                in_metadata = False
                text_lines.append(line)

            text = "\n".join(text_lines).strip()
            if text:
                notes.append({"created_at": created_at, "tags": tags, "text": text})

        return notes

    def _write_notes_to_file(self, filepath, topic, notes):
        parts = [f"# {topic}", ""]
        for note in notes:
            parts.append("## Note")
            parts.append(f"- created_at: {note.get('created_at', '')}")
            tags = note.get("tags", [])
            if tags:
                parts.append(f"- tags: {', '.join(tags)}")
            parts.append("")
            parts.append(note.get("text", ""))
            parts.append("")
        filepath.write_text("\n".join(parts), encoding="utf-8")

    def _update_index(self):
        lines = ["# Durable Memory Index", ""]
        for topic in self.TOPICS:
            notes = self.read_topic(topic)
            if not notes:
                continue

            label = "note" if len(notes) == 1 else "notes"
            lines.append(f"## {topic} ({len(notes)} {label})")
            for note in notes:
                preview = note.get("text", "").split("\n", 1)[0].strip() or "(empty)"
                if len(preview) > 100:
                    preview = preview[:97] + "..."
                lines.append(f"- {preview}")
            lines.append("")

        (self.memory_dir / "MEMORY.md").write_text("\n".join(lines), encoding="utf-8")
