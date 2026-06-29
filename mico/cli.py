import argparse
import os
import sys
from pathlib import Path

from .banner import print_banner
from .dotenv import load_dotenv
from .providers import FakeModelClient, OpenAICompatibleModelClient
from .runtime import Mico
from .state import RunStore
from .verification import run_verification, write_verification_json
from .workspace import Workspace, clip, clip_artifact


def build_arg_parser():
    parser = argparse.ArgumentParser(description="mico - a local coding agent that creates, modifies, runs and verifies code.")
    parser.add_argument("prompt", nargs="*", help="One-shot prompt.")
    parser.add_argument("--cwd", default=".", help="Workspace directory.")
    parser.add_argument("--max-steps", type=int, default=8, help="Maximum model/tool iterations.")
    parser.add_argument(
        "--approval",
        choices=("auto", "ask", "never"),
        default="ask",
        help="Tool approval policy; ask: confirm shell commands; auto: allow all; never: block write tools.",
    )
    parser.add_argument(
        "--provider",
        choices=("fake", "openai-compatible"),
        default=None,
        help="Model provider. Auto-detected from env when all three configs are present.",
    )
    parser.add_argument("--model", default=None, help="Model name (required for openai-compatible).")
    parser.add_argument("--base-url", default=None, help="API base URL (required for openai-compatible).")
    parser.add_argument(
        "--api-key-env",
        default="MICO_API_KEY",
        help="Environment variable name for API key (default: MICO_API_KEY).",
    )
    parser.add_argument(
        "--model-timeout",
        type=int,
        default=120,
        help="HTTP timeout in seconds for model requests (default: 120).",
    )
    parser.add_argument(
        "--verify-cmd",
        default=None,
        help="Verification command to run after agent completes (e.g. 'python verify.py').",
    )
    parser.add_argument(
        "--verify-timeout",
        type=int,
        default=120,
        help="Timeout in seconds for the verification command (default: 120).",
    )
    return parser


def _canonical_shell_name(name):
    prog = Path(str(name)).name.lower()
    if prog.endswith(".exe"):
        prog = prog[:-4]
    return prog


def _first_command_token(command):
    text = str(command).strip()
    if not text:
        return "(empty)"
    quote = text[0] if text[0] in ("'", '"') else None
    if quote:
        end = text.find(quote, 1)
        if end > 1:
            return text[1:end].lower()
        text = text[1:]
    return text.split()[0].lower() if text.split() else "(empty)"


def _approval_prefix(argv):
    if not argv:
        return "(empty)"
    shell = _canonical_shell_name(argv[0])
    flag = ""
    command = ""
    if len(argv) >= 2:
        candidate = str(argv[1]).lower()
        if shell == "cmd" and candidate in ("/c", "/k"):
            flag = candidate
            command = argv[2] if len(argv) >= 3 else ""
        elif shell in ("powershell", "pwsh") and candidate in ("-command", "-c"):
            flag = candidate
            command = argv[2] if len(argv) >= 3 else ""
        elif shell in ("bash", "sh") and candidate == "-c":
            flag = candidate
            command = argv[2] if len(argv) >= 3 else ""
        else:
            command = argv[1]
    token = _first_command_token(command)
    return " ".join(part for part in (shell, flag, token) if part)


def make_approval_callback(interactive, cwd=None):
    """Create an approval callback for shell command authorization.

    Returns a callable(argv) -> bool.
    In interactive mode, prompts user with cwd/argv and supports:
    y/yes for one-time approval, a/always for session prefix approval.
    In non-interactive mode, always denies shell commands.
    """
    allowed_prefixes = set()

    def _callback(argv):
        if not interactive:
            return False
        prefix = _approval_prefix(argv)
        if prefix in allowed_prefixes:
            return True
        prompt = (
            f"Allow shell command? cwd={cwd} argv={argv}\n"
            f"  Similar prefix: {prefix}\n"
            "  Confirm [y/yes], always allow similar [a/always], deny [n/no]: "
        )
        try:
            answer = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if answer in ("a", "always"):
            allowed_prefixes.add(prefix)
            return True
        return answer in ("y", "yes")

    return _callback


def _resolve_config(args):
    """Resolve final configuration from CLI args > system env > .env.

    Returns (provider, base_url, model, api_key_env) with all gaps filled.
    Assumes load_dotenv() has already been called so .env values are in os.environ.
    """
    provider = args.provider
    api_key_env = args.api_key_env
    base_url = args.base_url
    model = args.model

    # Fill base_url: CLI > system env > .env (already in os.environ)
    if base_url is None:
        base_url = os.environ.get("MICO_BASE_URL", "")

    # Fill model: CLI > system env > .env (already in os.environ)
    if model is None:
        model = os.environ.get("MICO_MODEL", "")

    # Check if API key is available
    has_api_key = bool(os.environ.get(api_key_env))

    # Auto-detect provider when not explicitly set
    if provider is None:
        if has_api_key and base_url and model:
            provider = "openai-compatible"
        else:
            provider = "fake"

    return provider, base_url, model, api_key_env


def build_agent(args, approval_callback=None, event_callback=None):
    provider, base_url, model, api_key_env = _resolve_config(args)
    workspace = Workspace.build(args.cwd)
    if provider == "fake":
        model_client = FakeModelClient()
    elif provider == "openai-compatible":
        if not base_url:
            raise SystemExit("--base-url is required for openai-compatible provider")
        if not model:
            raise SystemExit("--model is required for openai-compatible provider")
        try:
            model_client = OpenAICompatibleModelClient.from_env(
                base_url=base_url,
                model=model,
                api_key_env=api_key_env,
                timeout=args.model_timeout,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
    else:
        raise SystemExit(f"unknown provider: {provider}")
    return Mico(
        model_client=model_client,
        workspace=workspace,
        run_store=RunStore(workspace.root / ".mico" / "runs"),
        approval_policy=args.approval,
        max_steps=args.max_steps,
        approval_callback=approval_callback,
        event_callback=event_callback,
    )


def build_console_renderer():
    """Return an event_callback that prints concise progress lines to stdout."""

    def _render(etype, payload):
        p = payload or {}
        if etype == "run_started":
            print(f"mico: run {p.get('run_id', '?')} log={p.get('run_dir', '?')}")
        elif etype == "thinking":
            print("mico: thinking...")
        elif etype == "tool_started":
            name = p.get("name", "?")
            args = p.get("args", {})
            if name in ("write_file", "patch_file"):
                path = args.get("path", "?")
                print(f"mico: tool {name} path={path}")
            elif name == "run_command":
                argv = args.get("argv", [])
                print(f"mico: tool {name} argv={clip_artifact(argv, 200)}")
            else:
                print(f"mico: tool {name} {clip(str(args), 100)}")
        elif etype == "tool_finished":
            name = p.get("name", "?")
            ok = p.get("ok", False)
            error_kind = p.get("error_kind", "unknown")
            if ok:
                extra = ""
                if name == "run_command":
                    extra = f" exit={p.get('exit_code')} duration={p.get('duration_ms')}ms"
                print(f"mico: ok {name}{extra}")
            else:
                extra = ""
                if error_kind == "command_failed":
                    extra = f" exit={p.get('exit_code')}"
                print(f"mico: error {name} {error_kind}{extra}")
        elif etype == "retry":
            error_kind = p.get("error_kind", "retry")
            print(f"mico: retry {error_kind}")
        elif etype == "run_finished":
            run_id = p.get("run_id")
            if run_id:
                print(f"mico: done run={run_id}")

    return _render


def run_repl(agent, config=None):
    if config:
        print_banner(
            workspace=config.get("workspace", "."),
            model=config.get("model", "unknown"),
            provider=config.get("provider", "unknown"),
            approval=config.get("approval", "auto"),
            max_steps=config.get("max_steps", 8),
        )
    else:
        print("mico interactive mode (Ctrl+C or Ctrl+D to exit)")
    try:
        while True:
            try:
                user_input = input("mico> ").strip()
            except EOFError:
                print("\nBye.")
                return 0
            if not user_input:
                continue
            final_answer = agent.ask(user_input)
            print(final_answer)
    except KeyboardInterrupt:
        print("\nBye.")
        return 0


def main(argv=None):
    load_dotenv(Path.cwd())
    args = build_arg_parser().parse_args(argv)
    prompt = " ".join(args.prompt).strip()

    interactive = sys.stdin.isatty()
    approval_cb = make_approval_callback(interactive, cwd=args.cwd) if args.approval == "ask" else None

    if not prompt:
        if args.verify_cmd:
            raise SystemExit("--verify-cmd is only supported in one-shot mode")
        renderer = build_console_renderer() if interactive else None
        agent = build_agent(args, approval_callback=approval_cb, event_callback=renderer)
        config = {
            "workspace": args.cwd,
            "model": args.model or "unknown",
            "provider": args.provider or "auto",
            "approval": args.approval,
            "max_steps": args.max_steps,
        }
        return run_repl(agent, config=config)
    agent = build_agent(args, approval_callback=approval_cb)
    final_answer = agent.ask(prompt)
    print(final_answer)

    if args.verify_cmd:
        if agent._last_task_state is None:
            raise SystemExit("no run state found for verification")
        run_dir = agent.run_store.run_dir(agent._last_task_state)
        vresult = run_verification(
            agent.workspace.root, args.verify_cmd, timeout=args.verify_timeout
        )
        write_verification_json(vresult, run_dir / "verification.json")
        report = agent.build_report(
            agent._last_task_state, verification_result=vresult
        )
        agent.run_store.write_report(agent._last_task_state, report)

    return 0
