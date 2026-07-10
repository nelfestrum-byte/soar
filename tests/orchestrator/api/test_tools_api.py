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

BROKEN_IMPORT_MODULE = '''import nonexistent_package_xyz_does_not_exist


class BrokenTool:
    """A tool whose module cannot actually be imported."""

    def __init__(self, path):
        self.path = path
'''


def _write_tool(tmp_path, filename: str, content: str) -> None:
    (tmp_path / "tools" / filename).write_text(content, encoding="utf-8")


@pytest.mark.asyncio
async def test_list_tools_finds_known_classes(tmp_path):
    _write_tool(tmp_path, "widget.py", FIXTURE_MODULE)
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
async def test_get_tool_returns_docstring_and_signature(tmp_path):
    _write_tool(tmp_path, "widget.py", FIXTURE_MODULE)
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
async def test_get_tool_unknown_404(tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/tools/DoesNotExist")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_parse_module_does_not_import(tmp_path):
    """A tool module with an unresolvable top-level import must still be
    listed/describable — GET /tools uses static AST parsing, never import."""
    _write_tool(tmp_path, "broken.py", BROKEN_IMPORT_MODULE)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/tools")
        assert r.status_code == 200
        names = {t["name"] for t in r.json()}
        assert "BrokenTool" in names

        r = await c.get("/tools/BrokenTool")
        assert r.status_code == 200
        assert r.json()["constructor"] == "(path)"
