from __future__ import annotations

import re

from wm_agents_validator.models.plugin_result import EvalContext

_PLACEHOLDER_RE = re.compile(r"\{[^}]+\}")


def resolve_path_template(path: str, context: EvalContext | None) -> str:
    ctx = context or EvalContext()
    result = path
    for key, value in ctx.bindings.items():
        result = result.replace(f"{{{key}}}", str(value))
    # Unresolved placeholders become single-segment wildcards for path matching
    return _PLACEHOLDER_RE.sub("*", result)


def glob_match(pattern: str, path: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(path, _PLACEHOLDER_RE.sub("*", pattern))
