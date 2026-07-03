import pytest

from wm_agents_validator.cli.langfuse_config import init_langfuse_env, require_langfuse_env


def test_require_langfuse_env_missing(monkeypatch):
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    with pytest.raises(SystemExit):
        require_langfuse_env()


def test_cli_flags_override_env(monkeypatch):
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)

    args = argparse_namespace(
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
        langfuse_base_url="https://langfuse.example.com",
    )
    init_langfuse_env(args)

    import os

    assert os.environ["LANGFUSE_SECRET_KEY"] == "sk-test"
    assert os.environ["LANGFUSE_PUBLIC_KEY"] == "pk-test"
    assert os.environ["LANGFUSE_BASE_URL"] == "https://langfuse.example.com"


def argparse_namespace(**kwargs):
    from argparse import Namespace

    return Namespace(**kwargs)
