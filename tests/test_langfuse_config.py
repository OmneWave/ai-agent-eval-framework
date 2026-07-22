import pytest

from wm_agents_validator.cli.langfuse_config import get_langfuse_environment, init_langfuse_env, require_langfuse_env


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


def test_langfuse_environment_defaults_to_default(monkeypatch):
    monkeypatch.delenv("LANGFUSE_ENVIRONMENT", raising=False)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example.com")

    init_langfuse_env(argparse_namespace())

    assert get_langfuse_environment() == "default"


def test_langfuse_environment_env_var_respected(monkeypatch):
    monkeypatch.setenv("LANGFUSE_ENVIRONMENT", "prod")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example.com")

    init_langfuse_env(argparse_namespace())

    assert get_langfuse_environment() == "prod"


def test_langfuse_environment_cli_flag_overrides(monkeypatch):
    monkeypatch.setenv("LANGFUSE_ENVIRONMENT", "prod")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example.com")

    init_langfuse_env(argparse_namespace(langfuse_environment="qa"))

    import os

    assert os.environ["LANGFUSE_ENVIRONMENT"] == "qa"


def argparse_namespace(**kwargs):
    from argparse import Namespace

    return Namespace(**kwargs)
