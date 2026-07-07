"""Rich console logging plus optional file logging.

When serving over stdio, all log output MUST go to stderr — stdout carries the
MCP protocol stream.
"""

from __future__ import annotations

import logging
import sys

from rich.console import Console
from rich.logging import RichHandler


def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    handlers: list[logging.Handler] = [
        RichHandler(
            console=Console(file=sys.stderr, force_terminal=False),
            show_path=False,
            rich_tracebacks=True,
        )
    ]
    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handlers.append(fh)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        handlers=handlers,
        force=True,
    )
    # paramiko is chatty at INFO
    logging.getLogger("paramiko").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
