"""Checkpoint/resume support for mico sessions."""

import hashlib
import os
import time
import uuid
from pathlib import Path

CHECKPOINT_SCHEMA_VERSION = "checkpoint-v1"
CHECKPOINT_NONE_STATUS = "no-checkpoint"
CHECKPOINT_FULL_VALID_STATUS = "full-valid"
CHECKPOINT_PARTIAL_STALE_STATUS = "partial-stale"
CHECKPOINT_WORKSPACE_MISMATCH_STATUS = "workspace-mismatch"
CHECKPOINT_SCHEMA_MISMATCH_STATUS = "schema-mismatch"

RUNTIME_IDENTITY_KEYS = (
    "cwd",
    "model",
    "model_client",
    "approval_policy",
    "max_steps",
    "workspace_fingerprint",
    "tool_signature",
)

_IGNORED_DIRS = {".git", ".mico", "__pycache__", ".pytest_cache", ".venv", "node_modules"}


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def file_freshness(path, workspace_root):
    """Return freshness token for a path: 'missing', 'dir', or 'sha256:<16hex>'."""
    root = Path(workspace_root).resolve()
    candidate = Path(path)
    p = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        common = os.path.commonpath([str(root), str(p)])
    except ValueError:
        return "outside"
    if common != str(root):
        return "outside"
    if not p.exists():
        return "missing"
    if p.is_dir():
        return "dir"
    h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return "sha256:" + h


def workspace_fingerprint(workspace_root):
    """Hash relative paths and file freshness under workspace root, ignoring common dirs."""
    root = Path(workspace_root)
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            rel = fpath.relative_to(root).as_posix()
            freshness = file_freshness(str(fpath), workspace_root)
            entries.append(rel + ":" + freshness)
    entries.sort()
    return hashlib.sha256("\n".join(entries).encode()).hexdigest()[:16]


def tool_signature(tool_catalog):
    """Hash stable fields from tool catalog."""
    parts = []
    for item in sorted(tool_catalog, key=lambda x: x.get("name", "")):
        parts.append("|".join([
            str(item.get("name", "")),
            str(item.get("schema", "")),
            str(item.get("requires_approval", "")),
            str(item.get("read_only", "")),
            str(item.get("allowed", "")),
        ]))
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def current_runtime_identity(agent):
    """Build a runtime identity dict from the agent."""
    return {
        "cwd": str(agent.workspace.root),
        "model": (
            getattr(agent, "model", "")
            or getattr(getattr(agent, "model_client", None), "model", "")
            or getattr(getattr(agent, "model_client", None), "model_id", "")
        ),
        "model_client": type(getattr(agent, "model_client", None)).__name__,
        "approval_policy": agent.approval_policy,
        "max_steps": agent.max_steps,
        "workspace_fingerprint": workspace_fingerprint(str(agent.workspace.root)),
        "tool_signature": tool_signature(agent.tool_executor.tool_catalog()),
    }


def ensure_checkpoint_shape(session):
    """Ensure session has a well-formed checkpoints structure."""
    if "checkpoints" not in session:
        session["checkpoints"] = {"current_id": None, "history": [], "items": {}}
    cp = session["checkpoints"]
    cp.setdefault("current_id", None)
    cp.setdefault("history", [])
    if "items" not in cp and "store" in cp:
        cp["items"] = cp.pop("store")
    cp.setdefault("items", {})
    session.setdefault("resume_state", {
        "status": CHECKPOINT_NONE_STATUS,
        "stale_paths": [],
        "runtime_identity_mismatch_fields": [],
    })
    session.setdefault("runtime_identity", {})
    return cp


def current_checkpoint(session):
    """Return the current checkpoint dict or None."""
    cp = session.get("checkpoints", {})
    cid = cp.get("current_id")
    if cid is None:
        return None
    return cp.get("items", {}).get(cid)


def evaluate_resume_state(agent):
    """Evaluate checkpoint freshness and return a resume state dict."""
    ensure_checkpoint_shape(agent.session)
    cp = current_checkpoint(agent.session)
    current_id = current_runtime_identity(agent)
    if cp is None:
        result = {
            "status": CHECKPOINT_NONE_STATUS,
            "checkpoint": None,
            "stale_paths": [],
            "runtime_identity_mismatch_fields": [],
        }
        agent.session["resume_state"] = result
        agent.session["runtime_identity"] = current_id
        return result

    # Schema version check
    if cp.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        result = {
            "status": CHECKPOINT_SCHEMA_MISMATCH_STATUS,
            "checkpoint": cp,
            "stale_paths": [],
            "runtime_identity_mismatch_fields": [],
        }
        agent.session["resume_state"] = result
        agent.session["runtime_identity"] = current_id
        return result

    # Runtime identity check
    saved_id = cp.get("runtime_identity", {})
    mismatch_fields = []
    for key in RUNTIME_IDENTITY_KEYS:
        if current_id.get(key) != saved_id.get(key):
            mismatch_fields.append(key)

    # File freshness check
    stale_paths = []
    key_files = cp.get("key_files", {})
    workspace_root = str(agent.workspace.root)
    for path, saved_freshness in key_files.items():
        current_freshness = file_freshness(path, workspace_root)
        if current_freshness != saved_freshness:
            stale_paths.append(path)
            agent.session_memory.file_summaries.pop(path, None)

    if stale_paths and mismatch_fields == ["workspace_fingerprint"]:
        status = CHECKPOINT_PARTIAL_STALE_STATUS
    elif mismatch_fields:
        status = CHECKPOINT_WORKSPACE_MISMATCH_STATUS
    elif stale_paths:
        status = CHECKPOINT_PARTIAL_STALE_STATUS
    else:
        status = CHECKPOINT_FULL_VALID_STATUS

    result = {
        "status": status,
        "checkpoint": cp,
        "stale_paths": stale_paths,
        "runtime_identity_mismatch_fields": mismatch_fields,
    }
    agent.session["resume_state"] = result
    agent.session["runtime_identity"] = current_id
    return result


def _task_value(task_state, name, default=""):
    if isinstance(task_state, dict):
        return task_state.get(name, default)
    return getattr(task_state, name, default)


def infer_next_step(task_state):
    stop_reason = _task_value(task_state, "stop_reason", "")
    tools = _task_value(task_state, "tools", []) or []
    if stop_reason == "final":
        return "No next step recorded."
    if stop_reason == "step_limit":
        return "Resume from the latest checkpoint and continue the task."
    if tools:
        return "Decide the next action after " + str(tools[-1]) + "."
    return "Continue the task from the latest checkpoint."


def render_checkpoint_text(agent):
    """Render a human/machine-readable checkpoint section for prompt injection."""
    resume_state = getattr(agent, "resume_state", None)
    if resume_state is None:
        return ""

    status = resume_state.get("status", CHECKPOINT_NONE_STATUS)
    cp = resume_state.get("checkpoint")
    if cp is None:
        return ""

    lines = ["Task checkpoint:"]
    lines.append("  status: " + status)

    task_state = cp.get("task_state", {})
    if task_state.get("user_message"):
        lines.append("  goal: " + task_state["user_message"])
    if task_state.get("summary"):
        lines.append("  summary: " + task_state["summary"])
    if task_state.get("next_step"):
        lines.append("  next_step: " + task_state["next_step"])

    key_files = cp.get("key_files", {})
    if key_files:
        lines.append("  key_files:")
        for path, freshness in key_files.items():
            lines.append("    - " + path + " (" + freshness + ")")

    stale = resume_state.get("stale_paths", [])
    if stale:
        lines.append("  stale_paths:")
        for p in stale:
            lines.append("    - " + p + " (changed since checkpoint)")
        lines.append("  WARNING: stale file summaries are not trusted; re-read before use.")

    mismatch = resume_state.get("runtime_identity_mismatch_fields", [])
    if mismatch:
        lines.append("  runtime_mismatch: " + ", ".join(mismatch))
        lines.append("  WARNING: runtime environment changed; revalidate assumptions.")

    if status != CHECKPOINT_FULL_VALID_STATUS:
        lines.append("  NOTE: checkpoint is not fully valid; proceed with caution.")

    trigger = cp.get("trigger", "")
    if trigger:
        lines.append("  trigger: " + trigger)

    return "\n".join(lines) + "\n"


def create_checkpoint(agent, task_state, user_message, trigger):
    """Create a checkpoint and store it in the agent session."""
    ensure_checkpoint_shape(agent.session)

    key_files = {}
    workspace_root = str(agent.workspace.root)
    for path in agent.session_memory.recent_files:
        full = str(Path(workspace_root) / path)
        key_files[path] = file_freshness(full, workspace_root)

    checkpoint_id = uuid.uuid4().hex[:12]
    cp = {
        "checkpoint_id": checkpoint_id,
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "created_at": _now_iso(),
        "trigger": trigger,
        "key_files": key_files,
        "runtime_identity": current_runtime_identity(agent),
        "task_state": {
            "user_message": user_message,
            "summary": _task_value(task_state, "final_answer", "") or _task_value(task_state, "summary", ""),
            "next_step": _task_value(task_state, "next_step", "") or infer_next_step(task_state),
            "stop_reason": _task_value(task_state, "stop_reason", ""),
        },
    }

    checkpoints = agent.session["checkpoints"]
    checkpoints["current_id"] = checkpoint_id
    checkpoints["history"] = []
    checkpoints["items"] = {checkpoint_id: cp}
    agent.session["runtime_identity"] = cp["runtime_identity"]

    return cp
