import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class TaskState:
    user_message: str
    run_id: str
    status: str = "running"
    attempts: int = 0
    tool_steps: int = 0
    tools: list[str] = field(default_factory=list)
    final_answer: str = ""
    stop_reason: str = ""
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    checkpoint_id: str = ""
    resume_status: str = ""

    @classmethod
    def create(cls, user_message):
        return cls(user_message=user_message, run_id=uuid.uuid4().hex[:12])

    def record_attempt(self):
        self.attempts += 1
        self.updated_at = now()

    def record_tool(self, name):
        self.tool_steps += 1
        self.tools.append(name)
        self.updated_at = now()

    def finish_success(self, final_answer):
        self.status = "success"
        self.stop_reason = "final"
        self.final_answer = final_answer
        self.updated_at = now()

    def stop_retry_limit(self, final_answer):
        self.status = "stopped"
        self.stop_reason = "retry_limit"
        self.final_answer = final_answer
        self.updated_at = now()

    def stop_step_limit(self, final_answer):
        self.status = "stopped"
        self.stop_reason = "step_limit"
        self.final_answer = final_answer
        self.updated_at = now()

    def stop_model_error(self, final_answer):
        self.status = "stopped"
        self.stop_reason = "model_error"
        self.final_answer = final_answer
        self.updated_at = now()

    def to_dict(self):
        return asdict(self)


class RunStore:
    def __init__(self, root):
        self.root = Path(root)

    def run_dir(self, task_state):
        return self.root / task_state.run_id

    def start_run(self, task_state):
        self.run_dir(task_state).mkdir(parents=True, exist_ok=True)
        self.write_task_state(task_state)

    def write_task_state(self, task_state):
        self._write_json(self.run_dir(task_state) / "state.json", task_state.to_dict())

    def write_report(self, task_state, report):
        self._write_json(self.run_dir(task_state) / "report.json", report)

    def append_trace(self, task_state, event):
        path = self.run_dir(task_state) / "trace.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    @staticmethod
    def _write_json(path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
