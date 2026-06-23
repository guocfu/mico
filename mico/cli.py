import argparse
import os
from pathlib import Path

from .dotenv import load_dotenv
from .providers import FakeModelClient, OpenAICompatibleModelClient
from .runtime import Mico
from .state import RunStore
from .workspace import Workspace


def build_arg_parser():
    parser = argparse.ArgumentParser(description="A tiny local coding agent demo.")
    parser.add_argument("prompt", nargs="*", help="One-shot prompt.")
    parser.add_argument("--cwd", default=".", help="Workspace directory.")
    parser.add_argument("--max-steps", type=int, default=4, help="Maximum model/tool iterations.")
    parser.add_argument(
        "--approval",
        choices=("auto", "never"),
        default="auto",
        help="Tool approval policy; approval=never blocks tools that require approval, such as patch_file.",
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
    return parser


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


def build_agent(args):
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
    )


def main(argv=None):
    load_dotenv(Path.cwd())
    args = build_arg_parser().parse_args(argv)
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        raise SystemExit("mico requires a one-shot prompt for v0")
    agent = build_agent(args)
    print(agent.ask(prompt))
    return 0
