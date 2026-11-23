"""The ``ai-briefing`` command.

Subcommands are added by the issues that implement them (RFC §3.5). Until then the command
only describes itself.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from ai_briefing import __version__

DESCRIPTION = (
    "Evidence-first briefings on developments in AI, machine learning, data science and "
    "software engineering."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-briefing", description=DESCRIPTION)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command. ``--help`` and ``--version`` exit through argparse with status 0."""
    parser = build_parser()
    parser.parse_args(argv)
    # No subcommand exists yet, so a bare invocation shows what the command is.
    parser.print_help()
    return 0
