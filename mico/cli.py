import argparse

from .providers import FakeModelClient
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
        help="Reserved for future write tools.",
    )
    return parser


def build_agent(args):
    workspace = Workspace.build(args.cwd)
    return Mico(
        model_client=FakeModelClient(),
        workspace=workspace,
        run_store=RunStore(workspace.root / ".mico" / "runs"),
        approval_policy=args.approval,
        max_steps=args.max_steps,
    )


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        raise SystemExit("mico requires a one-shot prompt for v0")
    agent = build_agent(args)
    print(agent.ask(prompt))
    return 0
