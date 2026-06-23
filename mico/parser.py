import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedModelOutput:
    kind: str
    payload: Any
    error_kind: str | None = None


class ModelOutputParser:
    _TOOL_RE = re.compile(r"<tool>(.*?)</tool>", re.DOTALL)
    _FINAL_RE = re.compile(r"<final>(.*?)</final>", re.DOTALL)

    def parse(self, raw):
        text = str(raw or "")
        tool_match = self._TOOL_RE.search(text)
        if tool_match:
            try:
                payload = json.loads(tool_match.group(1).strip())
            except json.JSONDecodeError as exc:
                return ParsedModelOutput(
                    kind="retry",
                    payload=f"model returned malformed tool JSON: {exc}",
                    error_kind="malformed_tool_json",
                )
            return ParsedModelOutput(kind="tool", payload=payload)
        final_match = self._FINAL_RE.search(text)
        if final_match:
            final = final_match.group(1).strip()
            if final:
                return ParsedModelOutput(kind="final", payload=final)
            return ParsedModelOutput(
                kind="retry",
                payload="model returned an empty final answer",
                error_kind="empty_final",
            )
        return ParsedModelOutput(
            kind="retry",
            payload="model returned neither <tool> nor <final>",
            error_kind="unknown_block",
        )
