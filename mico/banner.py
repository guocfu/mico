"""Mico CLI banner with ASCII art logo."""
import sys

MICO_ASCII_ART = [
    "          ▄██▄       ▄▀▀▄",
    "          ██████▀▀▀▀▀   █",
    "          █████▀        ▀",
    "         ███▀▀        ▀▄ █",
    "         ▀▀            ▀ █",
    "        █▄  ▄██ ▄ ▀█▀   ██▄",
    "        ▀█      ▀       ▄▀▄ ▄▀▄",
    "▄▀▀▀▀▀▀▀▀▀▀▄               ▀█ █",
    " █   ▄▄▄   ▀                █▄▀",
    " █   █ ▄    █   ▀▀         ▄▀",
    " ▀          ▀██▄▄█▀▀▀▀▀▀▀▀",
    "  ▀▀▀▀▀▀▀▀▀▀▀▀▀▀",
]


def build_banner(workspace: str, model: str, provider: str, approval: str, max_steps: int) -> str:
    """Generate banner string with border."""
    width = 70
    border_top = "+" + "=" * width + "+"
    border_mid = "|" + "-" * width + "|"
    border_bot = "+" + "=" * width + "+"

    lines = [border_top, "|" + " " * width + "|"]

    # Text lines on the left
    text_lines = [
        "mico",
        "local coding agent",
        "calm shell, ready for work",
    ]

    # Combine text and ASCII art
    art_start = 2  # Start ASCII art from line index 2
    for i, art_line in enumerate(MICO_ASCII_ART):
        line_num = art_start + i
        if line_num < len(text_lines) + art_start:
            text = text_lines[line_num - art_start]
        else:
            text = ""

        # Format: | text + padding + art + padding |
        if text:
            formatted = f"  {text:<28}{art_line}"
        else:
            formatted = f"{'':>32}{art_line}"

        # Pad to width
        formatted = f"|{formatted:<{width}}|"
        lines.append(formatted)

    lines.append("|" + " " * width + "|")
    lines.append(border_mid)

    # Info lines
    info_lines = [
        f" WORKSPACE  {workspace:<50}",
        f" MODEL      {model:<16} PROVIDER   {provider:<16}",
        f" APPROVAL   {approval:<16} MAX_STEPS  {max_steps:<16}",
    ]
    for info in info_lines:
        lines.append(f"|{info:<{width}}|")

    lines.append("|" + " " * width + "|")
    lines.append(border_bot)

    return "\n".join(lines)


def print_banner(workspace: str, model: str, provider: str, approval: str, max_steps: int) -> None:
    """Print banner to stdout."""
    banner = build_banner(workspace, model, provider, approval, max_steps)
    # Handle Windows console encoding
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    print(banner)