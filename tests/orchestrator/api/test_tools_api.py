import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.main import app

FIXTURE_MODULE = '''"""Example tool module for tests."""


class Widget:
    """A small reusable widget.

    Extra detail line, not part of the summary.
    """

    def __init__(self, path, ttl=60):
        self.path = path
        self.ttl = ttl

    def get(self, key):
        """Fetch a value."""
        return None

    def _private(self):
        pass


class _Hidden:
    """Should not be listed — underscore-prefixed."""
'''

FACTORY_MODULE = '''"""Example factory module for tests."""


def new_widget(path: str, ttl: int = 60):
    """Build a Widget instance."""
    return None
'''

BROKEN_IMPORT_MODULE = '''import nonexistent_package_xyz_does_not_exist


class BrokenTool:
    """A tool whose module cannot actually be imported."""

    def __init__(self, path):
        self.path = path
'''


def _write_tool(tmp_path, filename: str, content: str) -> None:
    (tmp_path / "tools" / filename).write_text(content, encoding="utf-8")


def _write_registry(tmp_path, registry: dict) -> None:
    lines = ["TOOL_REGISTRY = {"]
    for name, meta in registry.items():
        meta_repr = ", ".join(f'"{k}": "{v}"' for k, v in meta.items())
        lines.append(f'    "{name}": {{{meta_repr}}},')
    lines.append("}")
    lines.append("__all__ = list(TOOL_REGISTRY)")
    (tmp_path / "tools" / "__init__.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_list_tools_kind_class(tmp_path):
    _write_tool(tmp_path, "widget.py", FIXTURE_MODULE)
    _write_registry(tmp_path, {"Widget": {"kind": "class", "module": "widget"}})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/tools")
        assert r.status_code == 200
        data = r.json()
        names = {t["name"] for t in data}
        assert "Widget" in names
        assert "_Hidden" not in names
        widget = next(t for t in data if t["name"] == "Widget")
        assert widget["module"] == "widget"
        assert widget["summary"] == "A small reusable widget."


@pytest.mark.asyncio
async def test_get_tool_kind_class_returns_docstring_and_signature(tmp_path):
    _write_tool(tmp_path, "widget.py", FIXTURE_MODULE)
    _write_registry(tmp_path, {"Widget": {"kind": "class", "module": "widget"}})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/tools/Widget")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Widget"
        assert data["module"] == "widget"
        assert data["constructor"] == "(path, ttl)"
        methods = {m["name"]: m for m in data["methods"]}
        assert "get" in methods
        assert methods["get"]["signature"] == "(key)"
        assert methods["get"]["docstring"] == "Fetch a value."
        assert "_private" not in methods


@pytest.mark.asyncio
async def test_list_tools_kind_instance_resolves_to_underlying_class(tmp_path):
    _write_tool(tmp_path, "widget.py", FIXTURE_MODULE)
    _write_registry(tmp_path, {
        "Widget": {"kind": "class", "module": "widget"},
        "the_widget": {"kind": "instance", "of": "Widget", "module": "widget"},
    })
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/tools")
        assert r.status_code == 200
        data = r.json()
        entry = next(t for t in data if t["name"] == "the_widget")
        assert entry["instance_of"] == "Widget"
        assert entry["summary"] == "A small reusable widget."
        assert entry["constructor"] == "(path, ttl)"
        methods = {m["name"] for m in entry["methods"]}
        assert "get" in methods


@pytest.mark.asyncio
async def test_get_tool_kind_instance(tmp_path):
    _write_tool(tmp_path, "widget.py", FIXTURE_MODULE)
    _write_registry(tmp_path, {
        "Widget": {"kind": "class", "module": "widget"},
        "the_widget": {"kind": "instance", "of": "Widget", "module": "widget"},
    })
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/tools/the_widget")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "the_widget"
        assert data["instance_of"] == "Widget"


@pytest.mark.asyncio
async def test_list_tools_kind_factory(tmp_path):
    _write_tool(tmp_path, "widget.py", FACTORY_MODULE)
    _write_registry(tmp_path, {"new_widget": {"kind": "factory", "module": "widget"}})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/tools")
        assert r.status_code == 200
        data = r.json()
        entry = next(t for t in data if t["name"] == "new_widget")
        assert entry["kind"] == "function"
        assert entry["signature"] == "(path, ttl)"
        assert entry["docstring"] == "Build a Widget instance."


@pytest.mark.asyncio
async def test_get_tool_kind_factory(tmp_path):
    _write_tool(tmp_path, "widget.py", FACTORY_MODULE)
    _write_registry(tmp_path, {"new_widget": {"kind": "factory", "module": "widget"}})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/tools/new_widget")
        assert r.status_code == 200
        data = r.json()
        assert data["kind"] == "function"
        assert data["signature"] == "(path, ttl)"


@pytest.mark.asyncio
async def test_list_tools_unresolved_entry_reports_error_not_silent_stub(tmp_path):
    """Registry names a class that doesn't exist in the module — this must
    surface as a flagged configuration error, not the old silent
    `{"summary": ""}` stub (spec [S2](a): the registry covers 100% of
    public names by construction, so "nothing found" only happens for a
    broken tool file and must be visible, not swallowed)."""
    _write_tool(tmp_path, "widget.py", FIXTURE_MODULE)
    _write_registry(tmp_path, {"NoSuchClass": {"kind": "class", "module": "widget"}})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/tools")
        assert r.status_code == 200
        data = r.json()
        entry = next(t for t in data if t["name"] == "NoSuchClass")
        assert entry["error"] == "unresolved"
        assert entry["summary"] == ""


@pytest.mark.asyncio
async def test_get_tool_unresolved_entry_reports_error(tmp_path):
    _write_tool(tmp_path, "widget.py", FIXTURE_MODULE)
    _write_registry(tmp_path, {"NoSuchClass": {"kind": "class", "module": "widget"}})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/tools/NoSuchClass")
        assert r.status_code == 200
        assert r.json()["error"] == "unresolved"


@pytest.mark.asyncio
async def test_get_tool_unknown_404(tmp_path):
    _write_registry(tmp_path, {})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/tools/DoesNotExist")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_parse_module_does_not_import(tmp_path):
    """A tool module with an unresolvable top-level import must still be
    listed/describable — GET /tools uses static AST parsing, never import."""
    _write_tool(tmp_path, "broken.py", BROKEN_IMPORT_MODULE)
    _write_registry(tmp_path, {"BrokenTool": {"kind": "class", "module": "broken"}})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/tools")
        assert r.status_code == 200
        names = {t["name"] for t in r.json()}
        assert "BrokenTool" in names

        r = await c.get("/tools/BrokenTool")
        assert r.status_code == 200
        assert r.json()["constructor"] == "(path)"


@pytest.mark.asyncio
async def test_list_tools_excludes_names_not_in_registry(tmp_path):
    """Widget is defined but not declared in TOOL_REGISTRY — must not show
    up (E5: internal mechanics like CacheBackend/InMemoryCache/RedisCache
    today)."""
    _write_tool(tmp_path, "widget.py", FIXTURE_MODULE)
    _write_registry(tmp_path, {})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/tools")
        assert r.status_code == 200
        assert r.json() == []


@pytest.mark.asyncio
async def test_real_soar_tools_registry_excludes_internals():
    """Exercise the actual soar/tools/__init__.py against the real /tools
    route (default app.state.config.soar.tools_dir) — CacheBackend/
    InMemoryCache/RedisCache/_validate_external_url must be absent,
    http_client/WatermarkStore/SeenStore/watermark_store/seen_store/
    new_client/LoggingHttpClient/CachingHttpClient must be present."""
    config = app.state.config
    original = config.soar.tools_dir
    config.soar.tools_dir = "soar/tools"
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/tools")
            assert r.status_code == 200
            names = {t["name"] for t in r.json()}
    finally:
        config.soar.tools_dir = original

    assert "CacheBackend" not in names
    assert "InMemoryCache" not in names
    assert "RedisCache" not in names
    assert "_validate_external_url" not in names
    assert names == {
        "http_client",
        "LoggingHttpClient",
        "CachingHttpClient",
        "new_client",
        "WatermarkStore",
        "SeenStore",
        "watermark_store",
        "seen_store",
    }
