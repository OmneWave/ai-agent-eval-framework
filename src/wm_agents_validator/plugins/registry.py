from __future__ import annotations

from wm_agents_validator.plugins.base import EvaluatorPlugin
from wm_agents_validator.plugins.blocking_checks import BlockingChecksPlugin
from wm_agents_validator.plugins.file_mutability import FileMutabilityPlugin
from wm_agents_validator.plugins.intent_verification import IntentVerificationPlugin
from wm_agents_validator.plugins.metadata_gate import MetadataGatePlugin
from wm_agents_validator.plugins.resource_coverage import ResourceCoveragePlugin
from wm_agents_validator.plugins.tool_policy import ToolPolicyPlugin
from wm_agents_validator.plugins.trace_health import TraceHealthPlugin

DEFAULT_PLUGINS = [
    "metadata_gate",
    "intent_verification",
    "resource_coverage",
    "tool_policy",
    "file_mutability",
    "trace_health",
]

PLUGIN_WEIGHTS: dict[str, float] = {
    "metadata_gate": 0.05,
    "intent_verification": 0.20,
    "resource_coverage": 0.20,
    "tool_policy": 0.20,
    "file_mutability": 0.15,
    "trace_health": 0.10,
    "blocking_checks": 0.10,
}

_PLUGIN_CLASSES: dict[str, type] = {
    "metadata_gate": MetadataGatePlugin,
    "intent_verification": IntentVerificationPlugin,
    "resource_coverage": ResourceCoveragePlugin,
    "tool_policy": ToolPolicyPlugin,
    "file_mutability": FileMutabilityPlugin,
    "trace_health": TraceHealthPlugin,
    "blocking_checks": BlockingChecksPlugin,
}


def list_plugins() -> list[str]:
    return list(_PLUGIN_CLASSES.keys())


def get_plugin(name: str) -> EvaluatorPlugin:
    if name not in _PLUGIN_CLASSES:
        raise KeyError(f"Unknown plugin: {name}. Available: {', '.join(list_plugins())}")
    return _PLUGIN_CLASSES[name]()
