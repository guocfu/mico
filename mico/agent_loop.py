import time

from .state import TaskState, now
from .tools import TOOL_SPECS
from .workspace import clip, clip_artifact


def _summarize_tool_args(name, args):
    """Return a UI-safe short summary of tool arguments."""
    if name in ("write_file", "patch_file"):
        return {"path": args.get("path", "?")}
    if name == "run_command":
        argv = args.get("argv", [])
        return {"argv": clip_artifact(argv, 200)}
    return clip_artifact(args, 120)


class AgentLoop:
    def __init__(self, agent):
        self.agent = agent

    def run(self, user_message):
        agent = self.agent
        started_at = time.monotonic()
        task_state = TaskState.create(user_message)
        agent.run_store.start_run(task_state)
        agent.record({"role": "user", "content": user_message, "created_at": now()})
        agent.emit_trace(
            task_state,
            "run_started",
            {
                "user_request": clip(user_message, 300),
                "approval_policy": agent.approval_policy,
                "tool_summary": agent.tool_executor.tool_summary(),
            },
        )

        max_attempts = agent.max_steps + 3
        step_limit_reached = False
        while task_state.attempts < max_attempts:
            task_state.record_attempt()
            agent.run_store.write_task_state(task_state)
            bundle = agent.build_prompt_bundle(user_message)
            prompt = bundle.text
            agent.emit_trace(task_state, "model_requested", {
                "attempts": task_state.attempts,
                "prompt_metadata": bundle.metadata,
            })
            agent.emit_ui_event("thinking")
            try:
                raw = agent.model_client.complete(prompt)
            except Exception as exc:
                final = f"Stopped after model error: {exc}"
                task_state.stop_model_error(final)
                agent.record({"role": "assistant", "content": final, "created_at": now()})
                agent.run_store.write_task_state(task_state)
                agent.emit_trace(
                    task_state,
                    "run_finished",
                    {
                        "status": task_state.status,
                        "stop_reason": task_state.stop_reason,
                        "final_answer": final,
                        "run_duration_ms": int((time.monotonic() - started_at) * 1000),
                    },
                )
                agent.emit_ui_event("run_finished", {"final_summary": clip(final, 120)})
                agent.run_store.write_report(task_state, agent.build_report(task_state))
                agent._last_task_state = task_state
                return final
            parsed = agent.parse_output(raw)
            kind, payload = parsed.kind, parsed.payload
            trace_payload = {"kind": kind}
            if kind == "retry" and parsed.error_kind is not None:
                trace_payload["error_kind"] = parsed.error_kind
            agent.emit_trace(task_state, "model_parsed", trace_payload)

            if kind == "tool":
                name = payload.get("name", "")
                args = payload.get("args", {})
                if task_state.tool_steps >= agent.max_steps:
                    step_limit_reached = True
                    break
                agent.emit_ui_event("tool_started", {
                    "name": name,
                    "args": _summarize_tool_args(name, args),
                })
                t0 = time.monotonic()
                result = agent.execute_tool(name, args)
                duration_ms = int((time.monotonic() - t0) * 1000)
                task_state.record_tool(name)
                spec = TOOL_SPECS.get(name)
                max_chars = spec.max_result_chars if spec else 4000
                agent.record(
                    {
                        "role": "tool",
                        "name": name,
                        "args": args,
                        "content": clip(result.content, max_chars),
                        "metadata": dict(result.metadata),
                        "created_at": now(),
                    }
                )
                agent.emit_trace(
                    task_state,
                    "tool_executed",
                    {"name": name, "args": clip_artifact(args, 500), "result": clip(result.content, 500), **result.metadata},
                )
                tool_finished_payload = {
                    "name": name,
                    "ok": result.metadata.get("ok", False),
                    "error_kind": result.metadata.get("error_kind", "unknown"),
                    "duration_ms": duration_ms,
                }
                meta = result.metadata
                if "exit_code" in meta:
                    tool_finished_payload["exit_code"] = meta["exit_code"]
                if "timed_out" in meta:
                    tool_finished_payload["timed_out"] = meta["timed_out"]
                agent.emit_ui_event("tool_finished", tool_finished_payload)
                continue

            if kind == "retry":
                error_kind = parsed.error_kind or "unknown_block"
                agent.emit_ui_event("retry", {"error_kind": error_kind, "message": clip(str(payload), 120)})
                agent.record({"role": "assistant", "content": payload, "created_at": now()})
                continue

            final = str(payload).strip()
            task_state.finish_success(final)
            agent.record({"role": "assistant", "content": final, "created_at": now()})
            agent.run_store.write_task_state(task_state)
            agent.emit_trace(
                task_state,
                "run_finished",
                {
                    "status": task_state.status,
                    "stop_reason": task_state.stop_reason,
                    "final_answer": final,
                    "run_duration_ms": int((time.monotonic() - started_at) * 1000),
                },
            )
            agent.emit_ui_event("run_finished", {"final_summary": clip(final, 120)})
            agent.run_store.write_report(task_state, agent.build_report(task_state))
            agent._last_task_state = task_state
            return final

        if task_state.attempts >= max_attempts:
            final = "Stopped after too many malformed model responses."
            task_state.stop_retry_limit(final)
        else:
            final = "Stopped after reaching the step limit."
            task_state.stop_step_limit(final)
        agent.record({"role": "assistant", "content": final, "created_at": now()})
        agent.run_store.write_task_state(task_state)
        agent.emit_trace(
            task_state,
            "run_finished",
            {
                "status": task_state.status,
                "stop_reason": task_state.stop_reason,
                "final_answer": final,
                "run_duration_ms": int((time.monotonic() - started_at) * 1000),
                "step_limit_reached": step_limit_reached,
            },
        )
        agent.emit_ui_event("run_finished", {"final_summary": clip(final, 120)})
        agent.run_store.write_report(task_state, agent.build_report(task_state))
        agent._last_task_state = task_state
        return final
