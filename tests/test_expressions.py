from wm_agents_validator.contracts.expressions import glob_match, resolve_path_template
from wm_agents_validator.models.plugin_result import EvalContext


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
