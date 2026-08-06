import pytest
from pydantic import ValidationError

from wm_agents_validator.models.workflow_contract import ResourceEntry, ResourceRegistry


@pytest.fixture
def registry() -> ResourceRegistry:
    return ResourceRegistry(
        api=[ResourceEntry(name="hrdb", path="services/hrdb/designtime/hrdb_API.json")],
        javaservice=[ResourceEntry(name="MyJavaService", path="services/MyJavaService/src/com/test/myjavaservice/MyJavaService.java")],
        db=[ResourceEntry(name="hrdb", path="services/hrdb/designtime/hrdb_published_dataModel.json")],
        design_tokens=[ResourceEntry(name="CreateProduct", path="src/main/webapp/pages/CreateProduct/CreateProduct.tokens-plan.json")],
        page=[ResourceEntry(name="CreateProduct", path="src/main/webapp/pages/CreateProduct/CreateProduct.html")],
        variable=[ResourceEntry(name="product_variable", path="src/main/webapp/pages/CreateProduct/CreateProduct.variables.json")],
        widget=[ResourceEntry(name="main", path="src/main/webapp/pages/CreateProduct/CreateProduct.html")],
        javascript=[ResourceEntry(name="main", path="src/main/webapp/pages/CreateProduct/CreateProduct.js")],
    )


def test_resolve_flat_type_uses_explicit_path(registry):
    path, qualifiers = registry.resolve("api.hrdb")
    assert path == "services/hrdb/designtime/hrdb_API.json"
    assert qualifiers == []


def test_resolve_flat_type_with_qualifier(registry):
    path, qualifiers = registry.resolve("api.hrdb.VacationController_getVacation")
    assert path == "services/hrdb/designtime/hrdb_API.json"
    assert qualifiers == ["VacationController_getVacation"]


def test_resolve_flat_type_multi_segment_qualifier(registry):
    path, qualifiers = registry.resolve("javaservice.MyJavaService.MyJavaController.sampleMethod")
    assert path == "services/MyJavaService/src/com/test/myjavaservice/MyJavaService.java"
    assert qualifiers == ["MyJavaController", "sampleMethod"]


def test_resolve_flat_type_uses_explicit_path_override(registry):
    path, _ = registry.resolve("javaservice.MyJavaService")
    assert path == "services/MyJavaService/src/com/test/myjavaservice/MyJavaService.java"


def test_resolve_db_type_with_table_and_column_qualifiers(registry):
    path, qualifiers = registry.resolve("db.hrdb.Employee.salary")
    assert path == "services/hrdb/designtime/hrdb_published_dataModel.json"
    assert qualifiers == ["Employee", "salary"]


def test_resolve_design_tokens_flat_type(registry):
    path, qualifiers = registry.resolve("design_tokens.CreateProduct")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.tokens-plan.json"
    assert qualifiers == []


def test_resolve_page_own_file(registry):
    # `page` is not a fixed/special type anymore -- it's just another registered
    # entry, resolved exactly like `api`/`db`/anything else.
    path, qualifiers = registry.resolve("page.CreateProduct")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.html"
    assert qualifiers == []


def test_resolve_variable_type(registry):
    path, qualifiers = registry.resolve("variable.product_variable")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.variables.json"
    assert qualifiers == []


def test_resolve_widget_type(registry):
    path, _ = registry.resolve("widget.main")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.html"


def test_resolve_javascript_type(registry):
    path, _ = registry.resolve("javascript.main")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.js"


def test_resolve_variable_with_qualifier(registry):
    path, qualifiers = registry.resolve("variable.product_variable.VacationController_createVacation")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.variables.json"
    assert qualifiers == ["VacationController_createVacation"]


def test_resolve_unknown_flat_name_raises(registry):
    with pytest.raises(KeyError):
        registry.resolve("api.unknown_service")


def test_resolve_unknown_page_raises(registry):
    with pytest.raises(KeyError):
        registry.resolve("page.UnknownPage")


def test_resolve_unknown_widget_name_raises(registry):
    with pytest.raises(KeyError):
        registry.resolve("widget.unknown_widget")


def test_resolve_malformed_reference_raises(registry):
    with pytest.raises(KeyError):
        registry.resolve("not_a_real_type.foo")


def test_resolve_unregistered_type_raises(registry):
    with pytest.raises(KeyError):
        registry.resolve("unregistered_type.foo")


def test_resource_entry_requires_explicit_path():
    # No built-in path convention exists for any type anymore -- `path` is a
    # required field, not something that can be silently derived.
    with pytest.raises(ValidationError):
        ResourceEntry(name="orderPlaced")


def test_resolve_generic_custom_type_not_in_fixed_vocabulary():
    # `resources:` isn't limited to a fixed set of type keys -- any name works
    # as long as it's registered with an explicit `path`.
    registry = ResourceRegistry(webhook=[ResourceEntry(name="orderPlaced", path="services/hooks/orderPlaced.json")])
    path, qualifiers = registry.resolve("webhook.orderPlaced")
    assert path == "services/hooks/orderPlaced.json"
    assert qualifiers == []


def test_resolve_generic_type_with_qualifier():
    registry = ResourceRegistry(webhook=[ResourceEntry(name="orderPlaced", path="services/hooks/orderPlaced.json")])
    path, qualifiers = registry.resolve("webhook.orderPlaced.retryPolicy")
    assert path == "services/hooks/orderPlaced.json"
    assert qualifiers == ["retryPolicy"]


@pytest.fixture
def nested_registry() -> ResourceRegistry:
    # Any entry can nest further typed sub-lists, not just `page` -- this fixture
    # exercises that with `page` since it's the real-world case (binding_with_widget.yaml).
    return ResourceRegistry(
        page=[
            ResourceEntry(
                name="CreateProduct",
                path="src/main/webapp/pages/CreateProduct/CreateProduct.html",
                variable=[ResourceEntry(name="product_variable", path="src/main/webapp/pages/CreateProduct/CreateProduct.variables.json")],
                widget=[ResourceEntry(name="main", path="src/main/webapp/pages/CreateProduct/CreateProduct.html")],
                javascript=[ResourceEntry(name="main", path="src/main/webapp/pages/CreateProduct/CreateProduct.js")],
            )
        ],
    )


def test_resolve_nested_page_scoped_variable(nested_registry):
    path, qualifiers = nested_registry.resolve("page.CreateProduct.variable.product_variable")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.variables.json"
    assert qualifiers == []


def test_resolve_nested_page_scoped_widget_shares_page_file(nested_registry):
    path, _ = nested_registry.resolve("page.CreateProduct.widget.main")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.html"


def test_resolve_nested_page_scoped_javascript(nested_registry):
    path, _ = nested_registry.resolve("page.CreateProduct.javascript.main")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.js"


def test_resolve_nested_page_scoped_with_qualifier(nested_registry):
    path, qualifiers = nested_registry.resolve(
        "page.CreateProduct.variable.product_variable.VacationController_createVacation"
    )
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.variables.json"
    assert qualifiers == ["VacationController_createVacation"]


def test_resolve_nested_unknown_name_raises(nested_registry):
    with pytest.raises(KeyError):
        nested_registry.resolve("page.CreateProduct.widget.unknown_widget")


def test_resolve_nested_unknown_subtype_becomes_qualifier(nested_registry):
    # "not_a_subtype" doesn't name any nested list on the CreateProduct entry --
    # descent stops there and it (plus anything after) becomes a plain qualifier,
    # not a KeyError, since it was never claiming to be a resource reference.
    path, qualifiers = nested_registry.resolve("page.CreateProduct.not_a_subtype.foo")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.html"
    assert qualifiers == ["not_a_subtype", "foo"]


def test_resolve_arbitrary_type_can_nest_arbitrarily_deep():
    # Nesting isn't special-cased to `page` -- any type, any depth.
    registry = ResourceRegistry(
        workflow_step=[
            ResourceEntry(
                name="onboarding",
                path="services/workflow/onboarding.json",
                sub_step=[
                    ResourceEntry(
                        name="verifyEmail",
                        path="services/workflow/onboarding/verifyEmail.json",
                    )
                ],
            )
        ]
    )
    path, qualifiers = registry.resolve("workflow_step.onboarding.sub_step.verifyEmail")
    assert path == "services/workflow/onboarding/verifyEmail.json"
    assert qualifiers == []
