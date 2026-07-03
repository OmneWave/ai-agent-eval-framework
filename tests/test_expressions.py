from pathlib import Path

from wm_agents_validator.contracts.expressions import glob_match, resolve_path_template
from wm_agents_validator.contracts.loader import load_contract
from wm_agents_validator.models.plugin_result import EvalContext
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.plugins.file_mutability import FileMutabilityPlugin

CARDS_SNAPSHOT = (
    Path(__file__).parent.parent / "trace-artifacts" / "c4739a2868e2b7aca6430aeae2f7ea0a_snapshot.json"
)


def test_resolve_path_template_substitutes_bindings():
    ctx = EvalContext(bindings={"page": "Cards_1", "serviceId": "weavr"})
    assert (
        resolve_path_template("src/main/webapp/pages/{page}/{page}.html", ctx)
        == "src/main/webapp/pages/Cards_1/Cards_1.html"
    )


def test_resolve_path_template_unresolved_placeholders_become_wildcards():
    ctx = EvalContext(bindings={})
    assert (
        resolve_path_template("src/main/webapp/pages/{page}/{page}.html", ctx)
        == "src/main/webapp/pages/*/*.html"
    )
    assert (
        resolve_path_template("services/{serviceId}/designtime/{serviceId}_API_REST_SERVICE.json", ctx)
        == "services/*/designtime/*_API_REST_SERVICE.json"
    )


def test_glob_match_resolves_unresolved_placeholders():
    pattern = "src/main/webapp/pages/{page}/{page}.html"
    path = "src/main/webapp/pages/Cards_1/Cards_1.html"
    assert glob_match(pattern, path)


def test_file_mutability_allows_page_html_without_context_bindings():
    snapshot = TraceSnapshot.model_validate_json(CARDS_SNAPSHOT.read_text(encoding="utf-8"))
    contract = load_contract("contracts/ui_to_api_binding_v1.yaml")
    result = FileMutabilityPlugin().evaluate(snapshot, contract, EvalContext(bindings={}))
    unrelated = [v for v in result.violations if v.code == "unrelated_file_changed"]
    assert unrelated == []
