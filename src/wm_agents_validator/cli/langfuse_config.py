from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

LANGFUSE_ENV_KEYS = (
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_BASE_URL",
)


def add_langfuse_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group(
        "Langfuse credentials",
        "Pass via flags, shell env vars, or .env/.env.local (flags override env, env overrides .env)",
    )
    group.add_argument(
        "--langfuse-secret-key",
        dest="langfuse_secret_key",
        metavar="KEY",
        help="Langfuse secret key (or set LANGFUSE_SECRET_KEY)",
    )
    group.add_argument(
        "--langfuse-public-key",
        dest="langfuse_public_key",
        metavar="KEY",
        help="Langfuse public key (or set LANGFUSE_PUBLIC_KEY)",
    )
    group.add_argument(
        "--langfuse-base-url",
        dest="langfuse_base_url",
        metavar="URL",
        help="Langfuse base URL (or set LANGFUSE_BASE_URL)",
    )
    group.add_argument(
        "--langfuse-environment",
        dest="langfuse_environment",
        metavar="ENV",
        help="Langfuse environment to filter by (or set LANGFUSE_ENVIRONMENT, default: default)",
    )


def init_langfuse_env(args: argparse.Namespace | None = None) -> None:
    """Load .env files then apply CLI flags. Does not override existing shell env vars from .env."""
    load_dotenv(".env.local", override=False)
    load_dotenv(".env", override=False)

    if args is not None:
        _apply_cli_overrides(args)

    require_langfuse_env()


def _apply_cli_overrides(args: argparse.Namespace) -> None:
    mapping = {
        "langfuse_secret_key": "LANGFUSE_SECRET_KEY",
        "langfuse_public_key": "LANGFUSE_PUBLIC_KEY",
        "langfuse_base_url": "LANGFUSE_BASE_URL",
        "langfuse_environment": "LANGFUSE_ENVIRONMENT",
    }
    for attr, env_key in mapping.items():
        value = getattr(args, attr, None)
        if value:
            os.environ[env_key] = value


def require_langfuse_env() -> None:
    missing = [key for key in LANGFUSE_ENV_KEYS if not os.getenv(key)]
    if missing:
        raise SystemExit(
            "Missing Langfuse credentials: "
            + ", ".join(missing)
            + "\nPass as shell env vars, --langfuse-* flags, or in .env/.env.local"
        )


def get_langfuse_environment() -> str:
    return os.environ.get("LANGFUSE_ENVIRONMENT") or "default"
