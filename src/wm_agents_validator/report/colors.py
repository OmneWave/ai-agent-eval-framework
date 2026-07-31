from __future__ import annotations

import os
import sys

RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"


def _colors_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


def colorize(text: str, color: str) -> str:
    if not _colors_enabled():
        return text
    return f"{color}{text}{RESET}"


def red(text: str) -> str:
    return colorize(text, RED)


def green(text: str) -> str:
    return colorize(text, GREEN)


def yellow(text: str) -> str:
    return colorize(text, YELLOW)
