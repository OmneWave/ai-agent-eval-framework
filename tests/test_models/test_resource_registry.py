import pytest

from wm_agents_validator.models.workflow_contract import PageEntry, ResourceEntry, ResourceRegistry


@pytest.fixture
def registry() -> ResourceRegistry:
    return ResourceRegistry(
        api=[ResourceEntry(name="hrdb")],
        javaservice=[ResourceEntry(name="MyJavaService", path="services/MyJavaService/src/com/test/myjavaservice/MyJavaService.java")],
        db=[ResourceEntry(name="hrdb")],
        design_tokens=[ResourceEntry(name="CreateProduct")],
        page=[
            PageEntry(
                name="CreateProduct",
                variable=[ResourceEntry(name="product_variable")],
                widget=[ResourceEntry(name="main")],
                javascript=[ResourceEntry(name="main")],
            )
        ],
    )


def test_resolve_flat_type_auto_derives_path(registry):
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
    path, qualifiers = registry.resolve("page.CreateProduct")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.html"
    assert qualifiers == []


def test_resolve_page_scoped_variable(registry):
    path, qualifiers = registry.resolve("page.CreateProduct.variable.product_variable")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.variables.json"
    assert qualifiers == []


def test_resolve_page_scoped_widget_shares_page_file(registry):
    path, _ = registry.resolve("page.CreateProduct.widget.main")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.html"


def test_resolve_page_scoped_javascript(registry):
    path, _ = registry.resolve("page.CreateProduct.javascript.main")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.js"


def test_resolve_page_scoped_with_qualifier(registry):
    path, qualifiers = registry.resolve(
        "page.CreateProduct.variable.product_variable.VacationController_createVacation"
    )
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.variables.json"
    assert qualifiers == ["VacationController_createVacation"]


def test_resolve_unknown_flat_name_raises(registry):
    with pytest.raises(KeyError):
        registry.resolve("api.unknown_service")


def test_resolve_unknown_page_raises(registry):
    with pytest.raises(KeyError):
        registry.resolve("page.UnknownPage")


def test_resolve_unknown_page_scoped_name_raises(registry):
    with pytest.raises(KeyError):
        registry.resolve("page.CreateProduct.widget.unknown_widget")


def test_resolve_malformed_reference_raises(registry):
    with pytest.raises(KeyError):
        registry.resolve("not_a_real_type.foo")


def test_resolve_malformed_page_reference_raises(registry):
    with pytest.raises(KeyError):
        registry.resolve("page.CreateProduct.not_a_subtype.foo")


def test_resolve_page_scoped_nameless_variable_no_entry_required(registry):
    # Policy-constrained reference: 3 parts, no name segment. Resolves to the
    # same convention path as any name-qualified entry of this subtype, with
    # no registry entry required to look up (this page's `variable` list
    # already has `product_variable`, but the nameless form doesn't touch it).
    path, qualifiers = registry.resolve("page.CreateProduct.variable")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.variables.json"
    assert qualifiers == []


def test_resolve_page_scoped_nameless_works_with_empty_bucket():
    registry = ResourceRegistry(page=[PageEntry(name="CreateProduct")])  # no variable entries at all
    path, qualifiers = registry.resolve("page.CreateProduct.variable")
    assert path == "src/main/webapp/pages/CreateProduct/CreateProduct.variables.json"
    assert qualifiers == []


def test_resolve_page_scoped_nameless_malformed_subtype_raises(registry):
    with pytest.raises(KeyError):
        registry.resolve("page.CreateProduct.not_a_subtype")
